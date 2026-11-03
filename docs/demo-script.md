# Demo video script (target 2:30, hard max 3:00)

Fictional data only: Jordan Lee, Lumen Pay, Northwind Logistics, Orbit Commerce. Never show `.env`, the terminal with the key, or any real résumé.

## Before recording

- `python3 -m grounded`, open http://127.0.0.1:8787 in a clean browser window (no bookmarks bar, no other tabs), zoom 125%.
- Click **Clear all**, then **Load demo candidate**.
- Do one full live pass first (≈ $0.10) so you know the timing; then **Clear all** and record for real.
- Record screen + voice. Cut every model wait down to ~1s with a "⏳ Muse Spark is grading…" caption. Plan takes ≈ 30s. Grading shows scores at ≈ 27s, then the checked rewrite ≈ 10s later. Keep a second or two of the "Checking each sentence…" placeholder on screen, because it shows the second pass.
- Have `reports/eval-20261102-2111.md` open in a second tab for the eval shot.

## Shot list

| Time | Screen | Voiceover |
|---|---|---|
| 0:00–0:15 | Title card: "Grounded: an interview coach that never invents your experience" | "Ask an AI to improve your interview answer and it'll add a 40% cost reduction you never achieved. Then the interviewer asks a follow-up, and you're done." |
| 0:15–0:35 | **1 · Your record**. Load demo candidate. Hover a fact, show draft vs confirmed. | "Grounded starts from your record. Muse Spark extracts facts from your résumé, each with a source quote. Nothing counts until you confirm it." |
| 0:35–0:55 | **2 · Target role**. Orbit Commerce JD is filled in, click **Predict questions**. Show 8 questions, a matched story, one gap. | "Paste a job description. Muse Spark predicts the questions, matches each to your best story, and tells you where you have no story at all." |
| 0:55–1:35 | **3 · Practice**. Pick "Tell me about a technical project you led end to end." Click **🎙 Speak** and say the inflated answer below. **Grade my answer**. | "Here's me answering the way people actually do under pressure: exaggerating." |
| | Grade result: scores, stray numbers flagged ($1M, 95%, 10 million), rewrite with citations, dropped sentences. | "Grounded catches every number that's not in my record. The rewrite is still strong, but every sentence cites a fact I confirmed. Sentences the model wrote that went beyond my facts get removed, and you can see them here." |
| 1:35–2:00 | Follow-up probe appears. Answer it honestly (below). Show the round-2 grade. | "Then it asks the follow-up a skeptical interviewer would ask. Saying 'I don't have that number' scores better than making one up." |
| 2:00–2:20 | Switch to the eval report tab, highlight the table. | "We measured it. On 20 fictional answers, a 'use only these facts' prompt still left unsupported claims in 7 of 20 rewrites. Grounded's verifier plus a per-sentence entailment check: 0 of 20. Our first run didn't win, and that's why we added the second check." |
| 2:20–2:35 | **4 · Brief**, scroll the one-page prep sheet. End card: repo URL, "Built with Muse Spark · Meta Model API". | "You walk in with a one-page brief, and every line of it is true. Grounded runs on localhost, and your record never leaves your machine except for the calls you make." |

## Lines to say on camera

**Inflated answer (spoken):**
> "I single-handedly re-architected webhooks onto Kafka for 10 million merchants. Latency dropped 95 percent and we saved 1 million dollars in infrastructure."

Say "1 million", not "a million": the number check only catches figures written as digits. Check the transcript before grading. If it says "a million", edit it to "$1M".

**Honest follow-up answer (adjust to the probe):**
> "Honestly, I don't have a measured cost number. What I can say is median delivery latency went from 40 seconds to 2 seconds, and I'd point to the dashboards for the rest."

## Fallbacks

- If speech recognition mishears, type the answer instead. That's fine on camera.
- If a live call fails or runs slow on the day, remove the key from `.env` and record the offline stub. Say on screen "offline stub, deterministic" and don't present it as live output.
- If the follow-up probe doesn't ask about cost, answer whatever it asks with the same honesty pattern.
