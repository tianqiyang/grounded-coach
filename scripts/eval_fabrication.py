"""Fabrication eval: does Grounded keep rewrites honest where plain prompting does not?

For each fictional case in sample/eval_cases.json, three conditions rewrite the
same answer with the same confirmed facts in context:

  A  naive       Muse Spark asked for a stronger, more impressive answer
  B  instructed  same, plus "use only the facts; never invent or inflate"
  C  grounded    the full Grounded pipeline (grade_answer), after the verifier

Every output is scored two ways:
  - stray numbers (deterministic): sentences with a number absent from every confirmed fact.
    C is 0 by construction, so this metric is only informative for A and B.
  - blind judge (Muse Spark, separate call): each sentence labeled supported / unsupported /
    no_claim against the record. The judge never sees which condition produced the text.

    python3 scripts/eval_fabrication.py --limit 3        # quick check
    python3 scripts/eval_fabrication.py --max-usd 8      # full run
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from grounded import coach  # noqa: E402
from grounded.coach import S, arr, numbers, obj  # noqa: E402
from grounded.meta_client import make_client  # noqa: E402
from grounded.server import load_sample  # noqa: E402
from grounded.store import Store  # noqa: E402

REWRITE_SCHEMA = obj({"sentences": arr(S)})
JUDGE_SCHEMA = obj({"verdicts": arr(obj({"i": {"type": "integer"},
                                         "label": {"type": "string", "enum": ["supported", "unsupported", "no_claim"]},
                                         "reason": S}))})
NAIVE = ("You are an expert interview coach. Rewrite the candidate's answer into a stronger, more impressive "
         "60-90 second spoken answer, first person. Return it as a list of sentences.")
INSTRUCTED = NAIVE + (" Use only facts from the candidate background. Do not invent or inflate metrics, scope, "
                      "titles, technologies or outcomes; if the background lacks something, leave it out.")
JUDGE = (
    "You are a strict fact-checker for interview answers. Given the candidate's RECORD and numbered SENTENCES, label "
    "each sentence: 'supported' if every factual claim it makes about the candidate's past is stated in or directly "
    "implied by the record; 'unsupported' if any claim (metric, scope, title, team size, technology, outcome, "
    "attribution) is absent from the record or exaggerates it; 'no_claim' if it states nothing factual about the past "
    "(a transition, an opinion, or a hypothetical 'I would...'). Be strict: rounding, scaling up, or upgrading 'helped' "
    "to 'led' is unsupported. Give a short reason. Return one verdict per sentence.")


def rewrite(client, prompt: str, facts: str, case: dict) -> list[str]:
    msg = json.dumps({"candidate_background": facts, "question": case["question"], "candidate_answer": case["answer"]})
    data, _ = client.chat_json("eval_rewrite", [{"role": "system", "content": prompt}, {"role": "user", "content": msg}],
                               REWRITE_SCHEMA, max_out=8000, reasoning="low")
    return [s for s in data.get("sentences", []) if s.strip()]


def judge(client, facts: str, sentences: list[str]) -> list[str]:
    if not sentences:
        return []
    msg = json.dumps({"record": facts, "sentences": [{"i": i, "text": s} for i, s in enumerate(sentences)]})
    data, _ = client.chat_json("eval_judge", [{"role": "system", "content": JUDGE}, {"role": "user", "content": msg}],
                               JUDGE_SCHEMA, max_out=8000, reasoning="low")
    labels = {v["i"]: v["label"] for v in data.get("verdicts", []) if isinstance(v.get("i"), int)}
    # A sentence the judge skipped is counted as unsupported: missing verdicts must not flatter any condition.
    return [labels.get(i, "unsupported") for i in range(len(sentences))]


def run_case(client, case: dict, workdir: Path) -> dict:
    store = Store(workdir / f"{case['id']}.sqlite3")
    load_sample(store)
    confirmed = store.confirmed_facts()
    facts = "\n".join(f"[{f['id']}] {f['text']}" for f in confirmed.values())
    known = set().union(*(numbers(f["text"]) for f in confirmed.values()))
    pid = store.save_plan({"company": "Eval", "role": "Eval", "jd": "", "role_summary": "", "competencies": [], "calls": [],
                           "questions": [{"id": "Q1", "question": case["question"], "type": "behavioral",
                                          "why": "Eval case.", "jd_quote": "", "story_id": case["story_id"],
                                          "fit": "strong" if case["story_id"] else "none", "gap_note": ""}]})
    outputs = {"A": rewrite(client, NAIVE, facts, case), "B": rewrite(client, INSTRUCTED, facts, case)}
    graded = coach.grade_answer(client, store, pid, "Q1", case["answer"])
    outputs["C"] = [s["text"] for s in graded["improved_answer"]]
    store.con.close()
    # Shuffle judge order so position never correlates with condition.
    order = list(outputs)
    random.Random(case["id"]).shuffle(order)
    result = {"id": case["id"], "kind": case["kind"], "question": case["question"], "answer": case["answer"],
              "verifier_dropped": len(graded["dropped_sentences"]), "conditions": {}}
    for cond in order:
        sents = outputs[cond]
        labels = judge(client, facts, sents)
        result["conditions"][cond] = {
            "sentences": [{"text": s, "judge": l, "stray_numbers": sorted(numbers(s) - known)} for s, l in zip(sents, labels)],
        }
    return result


def summarize(results: list[dict]) -> dict:
    out = {}
    for cond in ("A", "B", "C"):
        rows = [s for r in results for s in r["conditions"][cond]["sentences"]]
        claims = [s for s in rows if s["judge"] != "no_claim"]
        unsup = [s for s in rows if s["judge"] == "unsupported"]
        bad_outputs = sum(any(s["judge"] == "unsupported" for s in r["conditions"][cond]["sentences"]) for r in results)
        out[cond] = {
            "outputs": len(results), "sentences": len(rows), "claim_sentences": len(claims),
            "unsupported_sentences": len(unsup),
            "unsupported_rate": round(len(unsup) / len(claims), 3) if claims else 0.0,
            "outputs_with_any_unsupported": bad_outputs,
            "stray_number_sentences": sum(bool(s["stray_numbers"]) for s in rows),
            "by_kind": {k: sum(any(s["judge"] == "unsupported" for s in r["conditions"][cond]["sentences"])
                               for r in results if r["kind"] == k)
                        for k in sorted({r["kind"] for r in results})},
        }
    out["C"]["verifier_dropped_sentences"] = sum(r["verifier_dropped"] for r in results)
    return out


def markdown(summary: dict, results: list[dict], meta: dict) -> str:
    names = {"A": "Naive prompt", "B": "Instructed prompt", "C": "Grounded (verified)"}
    kinds = {k: sum(r["kind"] == k for r in results) for k in sorted({r["kind"] for r in results})}
    lines = [f"# Fabrication eval: {meta['date']}", "",
             f"{len(results)} fictional answers ({', '.join(f'{n} {k}' for k, n in kinds.items())}), "
             f"model `{meta['model']}`, eval cost ${meta['cost_usd']:.2f}, {meta['minutes']:.1f} min.", "",
             "| Condition | Claim sentences | Unsupported (judge) | Rate | Outputs with any unsupported | Sentences with stray numbers |",
             "|---|---|---|---|---|---|"]
    for c in ("A", "B", "C"):
        s = summary[c]
        lines.append(f"| {names[c]} | {s['claim_sentences']} | {s['unsupported_sentences']} | {s['unsupported_rate']:.0%} | "
                     f"{s['outputs_with_any_unsupported']} / {s['outputs']} | {s['stray_number_sentences']} |")
    lines += ["", "Outputs with any unsupported sentence, by how the input answer was written:", "",
              "| Condition | " + " | ".join(kinds) + " |", "|---|" + "---|" * len(kinds)]
    for c in ("A", "B", "C"):
        lines.append(f"| {names[c]} | " + " | ".join(f"{summary[c]['by_kind'].get(k, 0)} / {n}" for k, n in kinds.items()) + " |")
    lines += ["", f"The Grounded verifier removed {summary['C']['verifier_dropped_sentences']} model-written sentences "
              "before they reached the suggested answer.", "",
              "**Method notes.** The judge is Muse Spark in a separate call. It never sees the condition label, and sentence "
              "order across conditions is shuffled per case. A sentence the judge skips counts as unsupported. The "
              "stray-number column is deterministic; Grounded's verifier enforces it, so C is 0 by construction. "
              "Same model, same facts, same answers across conditions. All data is fictional.", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-usd", type=float, default=8.0, help="stop submitting new cases past this eval spend")
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()
    client = make_client(ROOT)
    if not client.live:
        sys.exit("META_API_KEY is not set; the eval needs the live model.")
    cases = json.loads((ROOT / "sample" / "eval_cases.json").read_text())["cases"]
    if args.limit:
        cases = cases[:args.limit]
    start_spend, started = client.ledger.spent(), time.time()
    results, failures = [], []
    with tempfile.TemporaryDirectory() as d, ThreadPoolExecutor(args.workers) as pool:
        futures = {}
        for case in cases:
            if client.ledger.spent() - start_spend > args.max_usd:
                print(f"stopping: eval spend passed ${args.max_usd}")
                break
            futures[pool.submit(run_case, client, case, Path(d))] = case["id"]
        for fut in as_completed(futures):
            cid = futures[fut]
            try:
                results.append(fut.result())
                print(f"{cid} done  (eval spend ${client.ledger.spent() - start_spend:.3f})", flush=True)
            except Exception as e:  # record and keep going; failures are reported, never silently dropped
                failures.append({"id": cid, "error": f"{type(e).__name__}: {e}"})
                print(f"{cid} FAILED {e}", flush=True)
    results.sort(key=lambda r: r["id"])
    meta = {"date": datetime.now().strftime("%Y-%m-%d %H:%M"), "model": client.model,
            "cost_usd": client.ledger.spent() - start_spend, "minutes": (time.time() - started) / 60, "failures": failures}
    if not results:
        sys.exit("no cases completed")
    summary = summarize(results)
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    (reports / f"eval-{stamp}.json").write_text(json.dumps({"meta": meta, "summary": summary, "results": results}, indent=1))
    md = markdown(summary, results, meta) + (f"\n{len(failures)} case(s) failed: {failures}\n" if failures else "")
    (reports / f"eval-{stamp}.md").write_text(md)
    print("\n" + md)


if __name__ == "__main__":
    main()
