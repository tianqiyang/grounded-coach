"""Deterministic stand-in for Muse Spark, used when META_API_KEY is unset.

It lets the UI, tests and demo run with no key and no spend. Its output is crude
on purpose (word-overlap heuristics); it also emits one fabricated claim per
grade so the grounding verifier has something to catch.
"""
from __future__ import annotations

import json
import re

WORD = re.compile(r"[a-z][a-z0-9+#.-]{2,}")
STOP = set("the and for with that this you your our are was were from have has will into about their they them "
           "what when how who why can not but all any its also more than over such per via using use used work".split())


def words(s: str) -> set[str]:
    return {w for w in WORD.findall((s or "").lower()) if w not in STOP}


def sentences(s: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", s or "") if len(x.strip()) > 12]


def parse_facts(block: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in re.finditer(r"\[(F-\d+)\]\s*(.+)", block or "")}


class OfflineClient:
    live = False
    model = "offline-stub"

    def __init__(self, ledger):
        self.ledger = ledger

    def chat_json(self, task, messages, schema, max_out=4000, reasoning="low"):
        content = messages[-1]["content"]
        if isinstance(content, list):
            content = content[0]["text"]
        p = json.loads(content)
        out = getattr(self, "_" + p["task"])(p)
        meta = {"task": task, "model": self.model, "usage": {}, "cost_usd": 0.0, "seconds": 0.0, "offline": True}
        self.ledger.record(meta)
        return out, meta

    def web_research(self, query, max_out=1200):
        return "", {"task": "research", "model": self.model, "cost_usd": 0.0, "offline": True}

    def _import(self, p):
        lines = [l.strip(" -•*\t") for l in p["resume_text"].splitlines()]
        lines = [l for l in lines if len(l) > 25]
        facts = [{"text": l, "source_quote": l} for l in lines]
        stories = [{"title": l[:60], "question_types": ["impact"], "situation": "", "task": "", "action": l,
                    "result": "", "fact_refs": [i]} for i, l in enumerate(lines) if re.search(r"\d", l)][:6]
        return {"facts": facts, "stories": stories}

    def _plan(self, p):
        jd = p["job_description"]
        sents = sentences(jd)
        ranked = sorted(sents, key=lambda s: -len(words(s)))[:8]
        stories = p["stories"]
        qs = []
        for i, s in enumerate(ranked):
            best, score = None, 0
            for st in stories:
                overlap = len(words(s) & words(json.dumps(st)))
                if overlap > score:
                    best, score = st, overlap
            kind = "behavioral" if i % 2 == 0 else "technical"
            topic = s.rstrip(".")
            question = (f"Tell me about a time you delivered on this: {topic[:120]}." if kind == "behavioral"
                        else f"How would you approach this part of the role: {topic[:120]}?")
            qs.append({"question": question, "type": kind, "why": "Directly stated in the job description.",
                       "jd_quote": s[:90], "story_id": best["id"] if best and score >= 2 else None,
                       "fit": "strong" if score >= 4 else "partial" if score >= 2 else "none",
                       "gap_note": "" if score >= 2 else "No story in your record overlaps this requirement."})
        comps = [{"name": " ".join(sorted(words(s), key=len)[-2:]).title() or "Core skill", "jd_quote": s[:70]} for s in ranked[:4]]
        return {"role_summary": f"{p.get('role') or 'The role'} at {p.get('company') or 'the company'} (offline stub summary).",
                "competencies": comps, "questions": qs}

    def _grade(self, p):
        facts = parse_facts(p["confirmed_facts"])
        claims = []
        for s in sentences(p["candidate_answer"]):
            best, score = None, 0
            for fid, text in facts.items():
                o = len(words(s) & words(text))
                if o > score:
                    best, score = fid, o
            if best and score >= 2:
                claims.append({"text": s, "fact_id": best, "quote": facts[best][:40]})
            else:
                claims.append({"text": s, "fact_id": None, "quote": None})
        story = p.get("matched_story") or {}
        cited = [f for f in story.get("fact_ids", []) if f in facts] or list(facts)[:2]
        improved = [{"text": "Here is a concrete example from my work.", "fact_id": None, "quote": None}]
        improved += [{"text": facts[f], "fact_id": f, "quote": facts[f][:40]} for f in cited[:3]]
        # A deliberately inflated sentence: the verifier must drop it.
        if cited:
            improved.append({"text": "That cut costs by 73% across the company.", "fact_id": cited[0], "quote": facts[cited[0]][:40]})
        n = len(p["candidate_answer"].split())
        return {"scores": {"structure": 3 if n > 60 else 2, "specificity": min(5, 1 + sum(c["fact_id"] is not None for c in claims)),
                           "relevance": 3, "ownership": 4 if " i " in f" {p['candidate_answer'].lower()} " else 2},
                "claims": claims, "strengths": ["Answer addresses the question directly."],
                "fixes": ["State the result with the number from your record.", "Say what *you* did, not the team."],
                "improved_answer": improved, "follow_up": "What would you do differently if you ran that project again?"}

    def _entail(self, p):
        verdicts = []
        for it in p["items"]:
            if not it["fact"]:
                verdicts.append({"i": it["i"], "label": "no_claim", "detail": ""})
                continue
            extra = words(it["sentence"]) - words(it["fact"]) - {"i", "my", "that", "then", "which"}
            label = "entailed" if len(extra) <= 3 else "adds_detail"
            verdicts.append({"i": it["i"], "label": label, "detail": ", ".join(sorted(extra)[:4])})
        return {"verdicts": verdicts}
