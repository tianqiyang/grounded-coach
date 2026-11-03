"""Interview-coach pipeline on Muse Spark, with deterministic grounding checks.

The model proposes; local code verifies. Every claim the model attributes to the
candidate must cite a *confirmed* fact id plus a verbatim quote from that fact,
and every number must appear in the cited fact. Anything that fails is shown as
unsupported and is never placed in a suggested answer.
"""
from __future__ import annotations

import json
import re

from .store import Store

S = {"type": "string"}
NS = {"type": ["string", "null"]}


def obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def arr(item: dict) -> dict:
    return {"type": "array", "items": item}


IMPORT_SCHEMA = obj({
    "facts": arr(obj({"text": S, "source_quote": S})),
    "stories": arr(obj({"title": S, "question_types": arr(S), "situation": S, "task": S, "action": S,
                        "result": S, "fact_refs": arr({"type": "integer"})})),
})

PLAN_SCHEMA = obj({
    "role_summary": S,
    "competencies": arr(obj({"name": S, "jd_quote": S})),
    "questions": arr(obj({
        "question": S, "type": {"type": "string", "enum": ["behavioral", "technical", "role"]},
        "why": S, "jd_quote": S, "story_id": NS,
        "fit": {"type": "string", "enum": ["strong", "partial", "none"]}, "gap_note": S,
    })),
})

SENTENCE = obj({"text": S, "fact_id": NS, "quote": NS})
GRADE_SCHEMA = obj({
    "scores": obj({k: {"type": "integer", "minimum": 1, "maximum": 5} for k in ("structure", "specificity", "relevance", "ownership")}),
    "claims": arr(SENTENCE),
    "strengths": arr(S),
    "fixes": arr(S),
    "improved_answer": arr(SENTENCE),
    "follow_up": S,
})

SYSTEM = (
    "You are Grounded, a rigorous interview coach. Hard rule: you may only attribute to the candidate "
    "what is written in their CONFIRMED FACTS. Never invent employers, metrics, scope, titles or outcomes. "
    "When you reference a fact, give its id and a quote copied character-for-character from that fact's text. "
    "If the record does not support something, say so plainly; a named gap is more useful than a polished fabrication."
)


# ---------------------------------------------------------------------------
# deterministic verification

def norm(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip()


def quote_in(quote: str | None, text: str) -> bool:
    q = norm(quote or "").strip(" .\"'")
    return len(q) >= 6 and q in norm(text)


NUM = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?\s*(?:%|x|k|m|b|ms|s|\+)?(?![\w])", re.I)
# Spoken answers spell units out ("40 seconds") where résumés abbreviate ("40s"); fold both to one form.
UNITS = [(r"milli-?seconds?|msecs?", "ms"), (r"seconds?|secs?", "s"), (r"percent|per cent", "%"),
         (r"thousand", "k"), (r"million", "m"), (r"billion", "b"), (r"times", "x")]
UNIT_RE = [(re.compile(r"(\d)\s*(?:" + pat + r")\b", re.I), rep) for pat, rep in UNITS]


def spoken_units(text: str) -> str:
    for rx, rep in UNIT_RE:
        text = rx.sub(lambda m: m.group(1) + rep, text)
    return text


def numbers(text: str) -> set[str]:
    return {re.sub(r"[\s,$]", "", m.group(0)).lower() for m in NUM.finditer(spoken_units(text or ""))}


def check_sentence(sent: dict, facts: dict[str, dict], all_facts: dict[str, dict]) -> dict:
    """Classify one claim. Returns a copy with `status` and `issues`."""
    out = {**sent, "issues": []}
    fid, quote = sent.get("fact_id"), sent.get("quote")
    fact = facts.get(fid or "")
    if fact is None:
        known = all_facts.get(fid or "")
        out["status"] = "draft_fact" if known and known["status"] == "draft" else "unsupported"
        out["issues"].append("cites an unconfirmed fact" if known else "no supporting fact in your record")
        return out
    if not quote_in(quote, fact["text"]):
        out["status"] = "unsupported"
        out["issues"].append(f"quote not found in {fid}")
        return out
    extra = numbers(sent.get("text", "")) - numbers(fact["text"])
    if extra:
        out["status"] = "unsupported"
        out["issues"].append("numbers not in your record: " + ", ".join(sorted(extra)))
        return out
    out["status"] = "grounded"
    return out


def stray_numbers(answer: str, facts: dict[str, dict]) -> list[str]:
    """Numbers the candidate said aloud that appear in none of their confirmed facts."""
    known = set().union(*(numbers(f["text"]) for f in facts.values())) if facts else set()
    seen, out = set(), []
    for m in NUM.finditer(spoken_units(answer or "")):
        key = re.sub(r"[\s,$]", "", m.group(0)).lower()
        if key not in known and key not in seen:
            seen.add(key)
            out.append(m.group(0).strip())
    return out


# ---------------------------------------------------------------------------
# pipeline steps

def _facts_block(store: Store) -> str:
    rows = store.confirmed_facts().values()
    return "\n".join(f"[{f['id']}] {f['text']}" for f in rows) or "(no confirmed facts yet)"


def _stories_block(store: Store) -> list[dict]:
    return [{k: s.get(k) for k in ("id", "title", "question_types", "situation", "task", "action", "result", "fact_ids")}
            for s in store.stories()]


def import_profile(client, store: Store, text: str = "", pdf_b64: str = "", filename: str = "resume.pdf") -> dict:
    if not text.strip() and not pdf_b64:
        raise ValueError("Paste résumé text or upload a PDF.")
    instruction = (
        "Extract the candidate's career record. facts: one atomic, checkable statement each (role, scope, "
        "action, metric, technology), with source_quote copied verbatim from the document. Do not merge or embellish. "
        "stories: STAR drafts built ONLY from those facts; fact_refs are 0-based indexes into your facts list. "
        "Leave a STAR field empty rather than guessing."
    )
    payload = {"task": "import", "instruction": instruction, "resume_text": text}
    content: list | str = json.dumps(payload)
    if pdf_b64:
        content = [{"type": "text", "text": json.dumps(payload)},
                   {"type": "file", "file": {"filename": filename, "file_data": "data:application/pdf;base64," + pdf_b64}}]
    data, meta = client.chat_json("import_profile", [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}],
                                  IMPORT_SCHEMA, max_out=16000)
    ids = []
    verified = 0
    for f in data.get("facts", []):
        ok = bool(text) and quote_in(f.get("source_quote"), text)
        verified += ok
        ids.append(store.add_fact(f.get("text", ""), f.get("source_quote", ""), "draft", ok))
    for s in data.get("stories", []):
        refs = [ids[i] for i in s.get("fact_refs", []) if isinstance(i, int) and 0 <= i < len(ids)]
        store.save_story({k: s.get(k, "") for k in ("title", "question_types", "situation", "task", "action", "result")} | {"fact_ids": refs})
    return {"facts_added": len(ids), "source_verified": verified, "stories_added": len(data.get("stories", [])), "call": meta}


def make_plan(client, store: Store, company: str, role: str, jd: str, research: bool = False) -> dict:
    if len(jd.strip()) < 80:
        raise ValueError("Paste the full job description (at least a paragraph).")
    calls = []
    company_notes = ""
    if research and getattr(client, "live", False) and company.strip():
        try:
            company_notes, meta = client.web_research(
                f"In 5 bullet points: what {company} builds, recent product or engineering news, and its engineering "
                f"interview style for a {role or 'software engineer'} role. Cite sources inline.")
            calls.append(meta)
        except Exception as e:  # research is optional; never block the plan on it
            company_notes = f"(web research unavailable: {e})"
    payload = {
        "task": "plan", "company": company, "role": role, "job_description": jd, "company_research": company_notes,
        "stories": _stories_block(store), "confirmed_facts": _facts_block(store),
        "instruction": (
            "Predict 8 interview questions this team is most likely to ask, mixing behavioral, technical and "
            "role-specific. For each: why it is likely, a jd_quote copied verbatim from the job description, the best "
            "matching story_id (or null), fit strong/partial/none, and gap_note: at most 25 words naming what the record lacks, "
            "no quotes (empty string if nothing is missing). "
            "competencies: the 4-6 skills the JD weighs most, each with a verbatim jd_quote."),
    }
    data, meta = client.chat_json("interview_plan", [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(payload)}],
                                  PLAN_SCHEMA, max_out=16000, reasoning="low")
    calls.append(meta)
    story_ids = {s["id"] for s in store.stories()}
    for c in data.get("competencies", []):
        c["jd_quote_verified"] = quote_in(c.get("jd_quote"), jd)
    for i, q in enumerate(data.get("questions", []), 1):
        q["id"] = f"Q{i}"
        q["jd_quote_verified"] = quote_in(q.get("jd_quote"), jd)
        if q.get("story_id") not in story_ids:
            if q.get("story_id"):
                q["gap_note"] = (q.get("gap_note") or "") + f" (model cited unknown story {q['story_id']})"
            q["story_id"], q["fit"] = None, "none"
    plan = {"company": company, "role": role, "jd": jd, "company_research": company_notes, **data, "calls": calls}
    store.save_plan(plan)
    return plan


GRADE_INSTRUCTION = (
    "Grade the spoken answer 1-5 on structure (STAR), specificity, relevance to the question, and ownership "
    "(I vs we). claims: split the answer into its factual claims about what the candidate did, owned or achieved "
    "(skip admissions of not knowing, opinions and hypotheticals like 'I would...'; those are not claims); cite fact_id and a verbatim quote when a "
    "confirmed fact supports it, otherwise fact_id null. strengths and fixes: 2-3 concrete items each. "
    "improved_answer: a 60-90 second answer the candidate could say out loud, first person, natural spoken English, "
    "that keeps the exact numbers, names and scope from the cited facts (specifics are the point; never soften or round them), "
    "as sentences each citing the fact it rests on (put the verbatim quote ONLY in the quote field, never inside text); transition "
    "sentences may use fact_id null but must contain no factual claim. follow_up: the probing question a "
    "skeptical interviewer would ask next.")

FOLLOWUP_INSTRUCTION = (
    " This is follow-up round {depth} of {max_depth}: `question` is the interviewer's probe and `earlier_turns` is the "
    "conversation so far. Judge relevance against the probe, not the original question. If the probe asks for something "
    "the record does not contain, the best answer says so plainly and explains how the candidate would find out; reward "
    "that honesty and never fill the gap with invented detail. improved_answer may be 20-40 seconds. follow_up: dig into "
    "the weakest point of this answer{last}.")
MAX_FOLLOWUPS = 3


def _grade(client, store: Store, question: str, qtype: str, why: str, story: dict | None, answer: str,
           history: list[dict] | None = None, depth: int = 0) -> dict:
    """One model call + local verification. Shared by first answers and follow-up rounds."""
    if len(answer.strip()) < 20:
        raise ValueError("Answer is too short to grade.")
    confirmed = store.confirmed_facts()
    every = {f["id"]: f for f in store.facts()}
    instruction = GRADE_INSTRUCTION
    if depth:
        instruction += FOLLOWUP_INSTRUCTION.format(
            depth=depth, max_depth=MAX_FOLLOWUPS, last="; this is the last round, so return an empty string" if depth >= MAX_FOLLOWUPS else "")
    payload = {
        "task": "grade", "question": question, "question_type": qtype, "why_asked": why,
        "matched_story": story, "confirmed_facts": _facts_block(store), "candidate_answer": answer,
        "earlier_turns": history or [], "instruction": instruction,
    }
    data, meta = client.chat_json("grade_followup" if depth else "grade_answer",
                                  [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(payload)}],
                                  GRADE_SCHEMA, max_out=12000, reasoning="low")
    claims = [check_sentence(c, confirmed, every) for c in data.get("claims", [])]
    improved, dropped = [], []
    for s in data.get("improved_answer", []):
        if s.get("fact_id") is None and not numbers(s.get("text", "")):
            improved.append({**s, "status": "connective", "issues": []})
            continue
        checked = check_sentence(s, confirmed, every)
        (improved if checked["status"] == "grounded" else dropped).append(checked)
    grounded = sum(c["status"] == "grounded" for c in claims)
    return {
        "question": question, "answer": answer, "depth": depth,
        "scores": data.get("scores", {}), "strengths": data.get("strengths", []), "fixes": data.get("fixes", []),
        "claims": claims, "grounding_rate": round(grounded / len(claims), 2) if claims else None,
        "stray_numbers": stray_numbers(answer, confirmed),
        "improved_answer": improved, "dropped_sentences": dropped,
        "follow_up": "" if depth >= MAX_FOLLOWUPS else data.get("follow_up", ""), "call": meta,
    }


def grade_answer(client, store: Store, plan_id: int, question_id: str, answer: str, seconds: int | None = None) -> dict:
    plan = store.plan(plan_id)
    if not plan:
        raise KeyError("plan not found")
    q = next((x for x in plan["questions"] if x["id"] == question_id), None)
    if not q:
        raise KeyError("question not found")
    story = next((s for s in store.stories() if s["id"] == q.get("story_id")), None)
    result = _grade(client, store, q["question"], q["type"], q["why"], story, answer)
    result |= {"seconds": seconds, "parent_id": None, "root_id": None}
    result["id"] = store.save_attempt(plan_id, question_id, result)
    return result


def grade_followup(client, store: Store, attempt_id: int, answer: str, seconds: int | None = None) -> dict:
    """Answer the interviewer's follow-up to an earlier attempt; chains up to MAX_FOLLOWUPS rounds."""
    parent = store.attempt(attempt_id)
    if not parent:
        raise KeyError("attempt not found")
    if not parent.get("follow_up"):
        raise ValueError("This round has no follow-up question.")
    chain = [parent]
    while chain[0].get("parent_id"):
        chain.insert(0, store.attempt(chain[0]["parent_id"]))
    root = chain[0]
    plan = store.plan(parent["plan_id"])
    q = next((x for x in plan["questions"] if x["id"] == parent["question_id"]), {})
    story = next((s for s in store.stories() if s["id"] == q.get("story_id")), None)
    history = [{"question": a["question"], "answer": a["answer"]} for a in chain]
    result = _grade(client, store, parent["follow_up"], q.get("type", "behavioral"), "Interviewer follow-up probe.",
                    story, answer, history, depth=parent.get("depth", 0) + 1)
    result |= {"seconds": seconds, "parent_id": parent["id"], "root_id": root["id"]}
    result["id"] = store.save_attempt(parent["plan_id"], parent["question_id"], result)
    return result


def brief_markdown(store: Store, plan_id: int) -> str:
    """One-page prep brief, rendered locally from the plan and attempts (no model call)."""
    plan = store.plan(plan_id)
    if not plan:
        raise KeyError("plan not found")
    stories = {s["id"]: s for s in store.stories()}
    latest, probes = {}, {}
    for a in store.attempts(plan_id):
        if a.get("depth"):
            probes.setdefault(a["question_id"], []).append(a)
        else:
            latest[a["question_id"]] = a
    lines = [f"# {plan.get('role') or 'Interview'} @ {plan.get('company') or 'Company'} — prep brief", "",
             plan.get("role_summary", ""), "", "## What they weigh most"]
    for c in plan.get("competencies", []):
        mark = "" if c.get("jd_quote_verified") else " *(quote unverified)*"
        lines.append(f"- **{c['name']}** — “{c['jd_quote']}”{mark}")
    lines += ["", "## Likely questions"]
    for q in plan.get("questions", []):
        s = stories.get(q.get("story_id") or "")
        lines.append(f"- **{q['id']} ({q['type']})** {q['question']}")
        lines.append(f"  - Story: {s['title'] if s else '— none —'} · fit: {q['fit']}")
        if q.get("gap_note"):
            lines.append(f"  - Gap: {q['gap_note']}")
        a = latest.get(q["id"])
        if a:
            sc = a.get("scores", {})
            lines.append(f"  - Last practice: structure {sc.get('structure')}/5, specificity {sc.get('specificity')}/5, "
                         f"grounding {int((a.get('grounding_rate') or 0) * 100)}%")
            if a.get("fixes"):
                lines.append(f"  - Fix next: {a['fixes'][0]}")
            drill = [p for p in probes.get(q["id"], []) if p.get("root_id") == a["id"]]
            if drill:
                lines.append(f"  - Follow-up drill: {len(drill)} round(s); hardest probe: “{drill[-1]['question']}”")
    gaps = [q for q in plan.get("questions", []) if q["fit"] == "none"]
    lines += ["", "## Honest gaps to prepare for"]
    lines += [f"- {q['question']} — {q.get('gap_note') or 'no matching story'}" for q in gaps] or ["- None flagged."]
    if plan.get("company_research"):
        lines += ["", "## Company notes (web research)", plan["company_research"]]
    return "\n".join(lines) + "\n"
