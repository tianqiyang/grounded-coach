# Demo video script (target 2:30, hard max 3:00)

Fictional data only: Jordan Lee, Lumen Pay, Northwind Logistics, Orbit Commerce. Never show `.env`, the terminal with the key, or any real résumé.

## Before recording

- `python3 -m grounded`, open http://127.0.0.1:8787 in a clean browser window (no bookmarks bar, no other tabs), zoom 125%.
- Click **Clear all**, then **Load demo candidate**.
- Do one full live pass first (about $0.06) so you know the timing; then **Clear all** and record for real.
- Record screen + voice. Cut every model wait down to ~1s with a "⏳ Muse Spark is grading…" caption. Dry-run timings (2026-11-03): plan 37s; grading shows scores at 29s and the rewrite at 38s; the follow-up shows scores at 16s and the rewrite at 23s. Keep a second or two of the "Checking each sentence…" placeholder on screen, because it shows the second pass.
- For the eval shot, open the README's **Fabrication eval** section on GitHub (after the repo is public) or in a Markdown preview. A raw `.md` file in the browser looks unfinished.

## Shot list

| Time | Screen | Voiceover |
|---|---|---|
| 0:00–0:15 | Title card: "Grounded: an interview coach that never invents your experience" | "Ask an AI to improve your interview answer and it'll add a 40% cost reduction you never achieved. Then the interviewer asks a follow-up, and you're done." |
| 0:15–0:35 | **1 · Your record**. Load demo candidate. Every demo fact loads confirmed, so click **?** on F-5 to show it switching to draft, then **✓** to confirm it again. | "Grounded starts from your record. Muse Spark extracts facts from your résumé, each with a source quote. Nothing counts until you confirm it." |
| 0:35–0:55 | **2 · Target role**. Orbit Commerce JD is filled in, click **Predict questions**. Show 8 questions, a matched story, one gap. | "Paste a job description. Muse Spark predicts the questions, matches each to your best story, and tells you where you have no story at all." |
| 0:55–1:35 | **3 · Practice**. Pick the "technical project you led end to end" question. Its number changes on each plan run (Q3 in the dry run). Click **🎙 Speak** and say the inflated answer below. **Grade my answer**. | "Here's me answering the way people actually do under pressure: exaggerating." |
| | Grade result: scores (1–2 out of 5), grounding 0%, red banner "You said 10m, 95%, 1m", every claim tagged unsupported. Hold on the "Checking each sentence…" placeholder for a beat, then the rewrite with fact tags. | "Grounded catches every number that's not in my record. The rewrite is still strong, but every sentence cites a fact I confirmed, and each one is checked against that fact before I see it." *Only if a "sentence(s) removed" line appears, open it and add:* "Here's what the model wrote that went beyond my facts. It never reached my answer." (The dry run removed none.) |
| 1:35–2:00 | The follow-up probe calls out "single-handedly". Answer it honestly (below). Show the round-2 grade. In the dry run, grounding went from 0% to 100% and ownership from 2 to 5. | "Then it asks the follow-up a skeptical interviewer would ask. Correcting myself and saying what I don't know took my grounding from zero to a hundred percent." |
| 2:00–2:20 | Switch to the eval report tab, highlight the table. | "We measured it. On 20 fictional answers, a 'use only these facts' prompt still left unsupported claims in 7 of 20 rewrites. Grounded's verifier plus a per-sentence entailment check: 0 of 20. Our first run didn't win, and that's why we added the second check." |
| 2:20–2:35 | **4 · Brief**, scroll the one-page prep sheet and pause on the practiced question's "Follow-up drill … last round grounded 100%" line. End card: repo URL, "Built with Muse Spark · Meta Model API". | "You walk in with a one-page brief, and every line of it is true. Grounded runs on localhost, and your record never leaves your machine except for the calls you make." |

## Lines to say on camera

**Inflated answer (spoken):**
> "I single-handedly re-architected webhooks onto Kafka for 10 million merchants. Latency dropped 95 percent and we saved 1 million dollars in infrastructure."

Say "1 million", not "a million": the number check only catches figures written as digits. Check the transcript before grading. If it says "a million", edit it to "$1M".

**Honest follow-up answer (used in the dry run; adjust to the probe):**
> "Honestly, I overstated it. I led the migration on a six-person team, so it wasn't single-handed. What I can stand behind is that median delivery latency went from 40 seconds to 2 seconds. I don't have the design doc details or a cost number in my record, so I won't guess."

## Fallbacks

- If speech recognition mishears, type the answer instead. That's fine on camera.
- If a live call fails or runs slow on the day, remove the key from `.env` and record the offline stub. Say on screen "offline stub, deterministic" and don't present it as live output.
- If the probe asks something else, answer it with the same pattern: correct the overstatement, give the one true number, and name what you don't know.
