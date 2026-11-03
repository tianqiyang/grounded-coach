# Grounded: an interview coach that never invents your experience

**Meta Global AI Developer Hackathon · Indie track · Theme: Build for Your World**

AI interview coaches are good at polish and bad at honesty. Ask one to improve a behavioral answer and it will add a "40% cost reduction" you never achieved. In a real interview, that is the follow-up question that sinks you.

Grounded uses **Muse Spark** (Meta Model API) to coach you, and **local, deterministic code checks every claim it makes about you** against a record of facts you confirmed yourself.

## How it works

1. **Your record.** Paste or upload your résumé. Muse Spark extracts atomic facts and STAR story drafts, each with a verbatim source quote. Every fact starts as a *draft*. Only facts you confirm can support a claim.
2. **Target role.** Paste a JD. Muse Spark predicts 8 likely questions, names the competencies the JD weighs most, matches each question to your best story, and names the gaps where you have no story. It can optionally run `web_search` on the company. Every JD quote is checked against the JD text.
3. **Practice.** Answer by voice (browser speech recognition) or by typing, with a timer. Muse Spark scores structure, specificity, relevance and ownership, splits your answer into claims, writes a 60–90 second rewrite, and asks the follow-up a skeptical interviewer would ask.
4. **Verify.** Local code, not the model, decides what is trustworthy:
   - A claim is **grounded** only if it cites a *confirmed* fact id **and** quotes that fact verbatim. Matching ignores case, whitespace and smart quotes, and a quote under 6 characters does not count.
   - **Every number** in a claim must appear in the cited fact. "Latency dropped 95%" fails even with a valid quote.
   - Numbers you said aloud that appear in none of your facts are flagged ("You said $2M…").
   - Rewrite sentences that fail verification are **removed** and listed separately, so a fabricated sentence never reaches your suggested answer.
5. **Brief.** A one-page markdown prep sheet is built locally from the plan and your latest scores, with no extra model call.

## Why Muse Spark

- **Structured outputs** (`response_format: json_schema`, strict) make every step machine-checkable. If a deployment rejects strict schemas, the client falls back to JSON mode and validates locally.
- **Native PDF input** for résumé import.
- **`web_search` via the Responses API** for optional company research.
- **`reasoning_effort`**: `low` for extraction, `medium` for planning and grading.
- The 1M-token context fits a whole story bank and JD in one call.

We deliberately do **not** use the `-contributor` model variants. Meta may train on those prompts, and résumés are personal.

## Cost control

All live calls go through `meta_client.Ledger`. Before each request it reserves a conservative worst-case cost, estimated from input size and `max_completion_tokens`. It refuses the call if the cumulative total in `data/spend.jsonl` would pass `GROUNDED_BUDGET_USD` (default **$100**). After each call it prices the real `usage` at Muse Spark rates (input $1.25 / cached $0.15 / output $4.25 per 1M tokens) and records it. The header shows live spend.

## Run it

Python 3.10+. Stdlib only: no `pip install`.

```bash
cp .env.example .env            # add META_API_KEY; leave it empty for the offline stub
python3 scripts/smoke_live.py   # optional: one ~$0.001 call to confirm key + model
python3 -m grounded             # http://127.0.0.1:8787
python3 -m unittest discover -s tests -v
```

Click **Load demo candidate** for a fictional engineer with a fictional JD. With no key, a deterministic **offline stub** stands in for the model. It deliberately emits one inflated rewrite sentence, so you can watch the verifier remove it.

## Layout

| Path | What |
|---|---|
| `grounded/meta_client.py` | Meta Model API client, spend ledger and budget gate |
| `grounded/coach.py` | Prompts, JSON schemas, pipeline, grounding verifier, brief renderer |
| `grounded/store.py` | SQLite: facts (draft/confirmed/rejected), stories, plans, attempts |
| `grounded/offline.py` | Deterministic model stand-in for tests and keyless demos |
| `grounded/server.py` | Localhost-only JSON API + static UI |
| `grounded/static/` | Single-page UI (no build step) |
| `sample/` | Fictional candidate and JD |
| `tests/` | Verifier, budget and pipeline tests |

## Privacy

Everything runs on `127.0.0.1`. Data lives in `data/` (git-ignored). The only outbound traffic is to the Meta Model API, and only when you click an action.

## Limits and next steps

- Grounding checks *attribution*, not truth: if you confirm a false fact, Grounded will faithfully defend it.
- Claim splitting is done by the model; a claim the model fails to extract is not checked. The stray-number scan on the raw answer is the deterministic backstop.
- Next: Muse Voice realtime transcription instead of browser speech, multi-turn follow-up drills, and spaced repetition across questions.
