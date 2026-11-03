"use strict";
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let state = null, currentQ = null, startedAt = null, tick = null;

function toast(msg, err) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (err ? " err" : ""); t.hidden = false;
  clearTimeout(t._h); t._h = setTimeout(() => (t.hidden = true), err ? 7000 : 2600);
}
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = (r.headers.get("content-type") || "").includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}
async function busy(btn, label, fn) {
  const old = btn.textContent; btn.disabled = true; btn.textContent = label;
  try { return await fn(); } catch (e) { toast(e.message, true); } finally { btn.disabled = false; btn.textContent = old; }
}
async function refresh() { state = await api("/api/state"); render(); }

function render() {
  const b = state.budget;
  $("#status").innerHTML = `<span class="pill ${state.mode}">${state.mode === "live" ? "LIVE · " + esc(state.model) : "OFFLINE STUB"}</span>
    <span>$${b.spent.toFixed(4)} / $${b.cap.toFixed(0)} · ${b.calls} calls</span>`;
  renderFacts(); renderStories(); renderPlan(); renderQuestions(); renderBrief();
}

function renderFacts() {
  const f = state.facts, c = f.filter((x) => x.status === "confirmed").length;
  $("#fact-count").textContent = `${c} confirmed / ${f.length}`;
  $("#facts").innerHTML = f.map((x) => `<li>
      <span class="fid">${esc(x.id)}</span>
      <div>${esc(x.text)}<div class="src">${esc(x.source)}${x.source_verified ? " · ✓ quote found in source" : ""}</div></div>
      <div class="seg">${["confirmed", "draft", "rejected"].map((s) => `<button data-fact="${esc(x.id)}" data-st="${s}" class="${s} ${x.status === s ? "on" : ""}" title="${s}">${s === "confirmed" ? "✓" : s === "draft" ? "?" : "✕"}</button>`).join("")}</div>
    </li>`).join("") || `<li class="muted">No facts yet. Load the demo candidate or import a résumé.</li>`;
}
function renderStories() {
  $("#stories").innerHTML = state.stories.map((s) => `<div class="story"><b>${esc(s.id)} · ${esc(s.title)}</b>
      <div class="muted">${esc([s.situation, s.action, s.result].filter(Boolean).join(" → "))}</div>
      <div class="chips">${(s.question_types || []).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}${(s.fact_ids || []).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div></div>`).join("")
    || `<p class="muted">No stories yet.</p>`;
}

function renderPlan() {
  const p = state.plan; if (!p) { $("#plan-out").innerHTML = ""; return; }
  const stories = Object.fromEntries(state.stories.map((s) => [s.id, s]));
  $("#plan-out").innerHTML = `<div class="card"><h3>${esc(p.role)} @ ${esc(p.company)}</h3><p>${esc(p.role_summary)}</p>
    <div class="chips">${p.competencies.map((c) => `<span class="chip" title="${esc(c.jd_quote)}">${esc(c.name)}${c.jd_quote_verified ? "" : " ⚠"}</span>`).join("")}</div>
    ${p.company_research ? `<details><summary>Company research</summary><p style="white-space:pre-wrap">${esc(p.company_research)}</p></details>` : ""}</div>
    <div class="card"><h3>Predicted questions</h3>${p.questions.map((q) => `<div class="story">
      <b>${esc(q.id)} · ${esc(q.question)}</b>
      <div class="muted">${esc(q.why)} ${q.jd_quote_verified ? `<i>“${esc(q.jd_quote)}”</i>` : `<span class="tag unsupported">quote not in JD</span>`}</div>
      <div class="chips"><span class="chip">${esc(q.type)}</span><span class="chip fit-${esc(q.fit)}">fit: ${esc(q.fit)}</span>
      ${q.story_id ? `<span class="chip">${esc(q.story_id)} · ${esc(stories[q.story_id]?.title)}</span>` : ""}</div>
      ${q.gap_note ? `<div class="muted">Gap: ${esc(q.gap_note)}</div>` : ""}</div>`).join("")}
      <div class="row between"><span class="cost">${costLine(p.calls)}</span><button onclick="switchTab('practice')">Practice these →</button></div></div>`;
}
function costLine(calls) {
  const list = Array.isArray(calls) ? calls : [calls];
  const cost = list.reduce((a, c) => a + (c?.cost_usd || 0), 0), secs = list.reduce((a, c) => a + (c?.seconds || 0), 0);
  return `${list.map((c) => esc(c?.model)).join(", ")} · $${cost.toFixed(4)} · ${secs.toFixed(1)}s`;
}

function renderQuestions() {
  const p = state.plan;
  if (!p) { $("#qlist").innerHTML = `<li class="muted">Create a plan first.</li>`; return; }
  const done = new Set(state.attempts.map((a) => a.question_id));
  $("#qlist").innerHTML = p.questions.map((q) => `<li data-q="${esc(q.id)}" class="${currentQ?.id === q.id ? "sel" : ""}">
    <b>${esc(q.id)}</b> ${esc(q.question)} <div class="chips"><span class="chip fit-${esc(q.fit)}">${esc(q.fit)}</span>${done.has(q.id) ? `<span class="chip">practiced</span>` : ""}</div></li>`).join("");
}
function selectQ(id) {
  currentQ = state.plan.questions.find((q) => q.id === id);
  const s = state.stories.find((x) => x.id === currentQ.story_id);
  $("#qhead").textContent = currentQ.question; $("#qhead").classList.remove("muted");
  $("#story-hint").innerHTML = s ? `<details class="muted"><summary>Suggested story: ${esc(s.title)}</summary>${esc([s.situation, s.task, s.action, s.result].filter(Boolean).join(" · "))}</details>`
    : `<p class="stray">No story in your record fits this. Practice naming the gap honestly.</p>`;
  $("#answer").value = ""; $("#grade-out").innerHTML = ""; resetTimer();
  const last = [...state.attempts].reverse().find((a) => a.question_id === id); if (last) renderGrade(last);
  renderQuestions();
}

function renderGrade(g) {
  const sc = g.scores || {}, gr = g.grounding_rate == null ? "–" : Math.round(g.grounding_rate * 100) + "%";
  const claim = (c) => `<div class="claim ${esc(c.status)}"><span class="tag ${esc(c.status)}">${esc(c.status === "draft_fact" ? "unconfirmed" : c.status)}</span>${esc(c.text)}
      <small>${c.fact_id ? esc(c.fact_id) + (c.quote ? ` · “${esc(c.quote)}”` : "") : ""}${c.issues?.length ? " · " + esc(c.issues.join("; ")) : ""}</small></div>`;
  $("#grade-out").innerHTML = `
    <div class="scores">${["structure", "specificity", "relevance", "ownership"].map((k) => `<div class="score"><b>${esc(sc[k] ?? "–")}</b><span>${k}</span></div>`).join("")}
      <div class="score"><b>${gr}</b><span>grounded</span></div></div>
    ${g.stray_numbers?.length ? `<div class="stray">You said <b>${g.stray_numbers.map(esc).join(", ")}</b> — not found in any confirmed fact. Expect an interviewer to probe it.</div>` : ""}
    <h3>What you claimed</h3>${g.claims.map(claim).join("")}
    <div class="grid2"><div><h3>Strengths</h3><ul>${g.strengths.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div>
      <div><h3>Fix next</h3><ul>${g.fixes.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div></div>
    <h3>Grounded rewrite</h3><div class="answer-out">${g.improved_answer.map((s) => `<p>${esc(s.text)} ${s.fact_id ? `<span class="tag grounded">${esc(s.fact_id)}</span>` : ""}</p>`).join("")}</div>
    ${g.dropped_sentences?.length ? `<details><summary>${g.dropped_sentences.length} model sentence(s) removed by the verifier</summary>${g.dropped_sentences.map(claim).join("")}</details>` : ""}
    <div class="followup"><b>Interviewer follow-up:</b> ${esc(g.follow_up)}</div>
    <div class="cost">${costLine(g.call)}${g.seconds ? ` · answered in ${g.seconds}s` : ""}</div>`;
}

async function renderBrief() {
  if (!state.plan) { $("#brief").innerHTML = `<p class="muted">No plan yet.</p>`; return; }
  const md = await api(`/api/brief/${state.plan.id}`);
  $("#brief").dataset.md = md;
  $("#dl-brief").href = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
  $("#brief").innerHTML = mdToHtml(md);
}
function mdToHtml(md) {
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>");
  let html = "", depth = 0;
  for (const line of md.split("\n")) {
    const m = line.match(/^(\s*)- (.*)/);
    const d = m ? (m[1].length >= 2 ? 2 : 1) : 0;
    while (depth < d) { html += "<ul>"; depth++; } while (depth > d) { html += "</ul>"; depth--; }
    if (m) html += `<li>${inline(m[2])}</li>`;
    else if (line.startsWith("## ")) html += `<h2>${inline(line.slice(3))}</h2>`;
    else if (line.startsWith("# ")) html += `<h1>${inline(line.slice(2))}</h1>`;
    else if (line.trim()) html += `<p>${inline(line)}</p>`;
  }
  return html + "</ul>".repeat(depth);
}

// timer + speech -----------------------------------------------------------
function resetTimer() { clearInterval(tick); tick = null; startedAt = null; $("#timer").textContent = "0:00"; }
function startTimer() {
  if (tick) return; startedAt = Date.now();
  tick = setInterval(() => { const s = Math.floor((Date.now() - startedAt) / 1000); $("#timer").textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }, 500);
}
let rec = null;
function toggleMic() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return toast("Speech input needs Chrome or Safari; type your answer instead.", true);
  if (rec) { rec.stop(); return; }
  rec = new SR(); rec.continuous = true; rec.interimResults = true; rec.lang = "en-US";
  const base = $("#answer").value ? $("#answer").value + " " : "";
  rec.onresult = (e) => { $("#answer").value = base + [...e.results].map((r) => r[0].transcript).join(" "); };
  rec.onend = () => { rec = null; $("#btn-mic").textContent = "🎙 Speak"; };
  rec.start(); startTimer(); $("#btn-mic").textContent = "■ Stop";
}

// events -------------------------------------------------------------------
function switchTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + name));
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
$("#facts").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-fact]"); if (!b) return;
  try { await api("/api/fact", { id: b.dataset.fact, status: b.dataset.st }); await refresh(); } catch (err) { toast(err.message, true); }
});
$("#add-fact").addEventListener("submit", async (e) => {
  e.preventDefault(); const t = $("#new-fact").value.trim(); if (!t) return;
  await api("/api/fact", { new: true, text: t }); $("#new-fact").value = ""; refresh();
});
$("#btn-sample").addEventListener("click", (e) => busy(e.target, "Loading…", async () => {
  if (state.facts.length && !confirm("Replace your current record with the demo candidate?")) return;
  const r = await api("/api/sample", {});
  $("#company").value = "Orbit Commerce"; $("#role").value = "Senior Software Engineer, Payments Infrastructure"; $("#jd").value = r.jd;
  await refresh(); toast(`Loaded ${r.facts} facts and ${r.stories} stories (fictional candidate).`);
}));
$("#btn-reset").addEventListener("click", async () => { if (confirm("Delete all facts, stories, plans and attempts?")) { await api("/api/reset", {}); currentQ = null; refresh(); } });
$("#btn-import").addEventListener("click", (e) => busy(e.target, "Reading…", async () => {
  const file = $("#resume-pdf").files[0]; let pdf = "";
  if (file) pdf = await new Promise((ok) => { const r = new FileReader(); r.onload = () => ok(r.result.split(",")[1]); r.readAsDataURL(file); });
  const r = await api("/api/import", { text: $("#resume-text").value, pdf_base64: pdf, filename: file?.name });
  await refresh(); toast(`Added ${r.facts_added} draft facts (${r.source_verified} quote-verified) and ${r.stories_added} stories. Review and confirm them.`);
}));
$("#btn-plan").addEventListener("click", (e) => busy(e.target, "Muse is reading the JD…", async () => {
  await api("/api/plan", { company: $("#company").value, role: $("#role").value, jd: $("#jd").value, research: $("#research").checked });
  currentQ = null; await refresh(); toast("Plan ready.");
}));
$("#qlist").addEventListener("click", (e) => { const li = e.target.closest("li[data-q]"); if (li) selectQ(li.dataset.q); });
$("#answer").addEventListener("input", startTimer);
$("#btn-mic").addEventListener("click", toggleMic);
$("#btn-grade").addEventListener("click", (e) => busy(e.target, "Grading…", async () => {
  if (!currentQ) return toast("Pick a question first.", true);
  if (rec) rec.stop();
  const seconds = startedAt ? Math.round((Date.now() - startedAt) / 1000) : null;
  clearInterval(tick); tick = null;
  const g = await api("/api/grade", { plan_id: state.plan.id, question_id: currentQ.id, answer: $("#answer").value, seconds });
  renderGrade(g); state = await api("/api/state"); renderQuestions(); renderBrief();
  $("#status .pill").nextElementSibling.textContent = `$${state.budget.spent.toFixed(4)} / $${state.budget.cap.toFixed(0)} · ${state.budget.calls} calls`;
}));
$("#btn-copy").addEventListener("click", async () => { await navigator.clipboard.writeText($("#brief").dataset.md || ""); toast("Copied."); });
refresh().catch((e) => toast(e.message, true));
