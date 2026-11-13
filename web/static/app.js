"use strict";

const FEATURES = [
  ["aphe", "Arterial phase hyperenhancement"],
  ["washout", "Washout"],
  ["capsule", "Enhancing capsule"],
  ["growth", "Threshold growth"],
  ["af_malignant", "Ancillary signs of malignancy"],
  ["af_benign", "Ancillary signs of benignity"],
];
const STATE_LABEL = { present: "Present", absent: "Absent", uncertain: "Possible", not_documented: "Not mentioned" };
const CATS = ["LR-2", "LR-3", "LR-4", "LR-5"];
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const hue = (c) => (c && /LR-[2-5]/.test(c) ? `--c:var(--lr${c[3]});--tint:var(--lr${c[3]}s)` : "");
const orList = (xs) => (xs.length > 1 ? xs.slice(0, -1).join(", ") + " or " + xs[xs.length - 1] : xs[0] || "");
const pill = (c) => (c ? `<span class="pill" style="${hue(c)}">${esc(c)}</span>` : `<span class="pill">—</span>`);
const ICON = {
  warn: '<svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 2 21h20L12 3Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M12 10v5m0 3v.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
  ok: '<svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="m8 12 3 3 5-6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  info: '<svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 11v6m0-9v.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
};

const S = { examples: [], a: null, obs: 0, samples: 1, mod: "MRI", review: null, undo: null, addendum: null, prevEnv: null };
const CHECK_STATE = { consistent: ["safe", "ok"], contradicts: ["conflict", "warn"], inside_envelope: ["critical", "warn"], not_assessable: ["review", "info"] };
const FROM_PRIOR = "From prior study";
const GROWTH_OUTCOME = {
  threshold_growth: "Threshold growth",
  threshold_growth_uncertain: "Threshold growth depends on the measurement",
  subthreshold_growth: "Subthreshold growth",
  size_stability: "Size stable for 2 years or more",
  no_threshold_growth: "No threshold growth",
};
const today = () => new Date().toLocaleDateString("en-CA");

async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch (e) { /* ignore */ } throw new Error(m); }
  return r.json();
}
function toast(m) { const t = $("toast"); t.textContent = m; t.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 2400); }

/* ---------------- routing ---------------- */
function route() {
  const v = location.hash === "#batch" ? "batch" : "analyse";
  $("view-analyse").hidden = v !== "analyse"; $("view-batch").hidden = v !== "batch";
  document.querySelectorAll("nav a").forEach((a) => a.setAttribute("aria-current", a.dataset.view === v ? "page" : "false"));
}
addEventListener("hashchange", route);

/* ---------------- status ---------------- */
async function status() {
  try {
    const h = await api("/api/health");
    const [cls, txt] = h.llm_ready ? ["ok", "On-device AI ready"] : h.warming ? ["wait", "Preparing on-device AI"]
      : h.llm_installed ? ["wait", "On-device AI idle"] : ["off", "Basic reading mode"];
    $("status").innerHTML = `<span class="dot ${cls}"></span><span title="${esc(h.llm)}">${txt}</span>`;
    if (h.warming || (!h.llm_ready && h.llm_installed)) setTimeout(status, 3000);
  } catch (e) {
    $("status").innerHTML = `<span class="dot off"></span><span>Service unavailable</span>`;
    setTimeout(status, 4000);
  }
}

/* ---------------- files ---------------- */
async function fileToText(file) {
  if (/\.(txt|md|text)$/i.test(file.name)) return file.text();
  const buf = new Uint8Array(await file.arrayBuffer());
  let bin = ""; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  const out = await api("/api/extract-text", { filename: file.name, content_b64: btoa(bin) });
  return out.text;
}
function dropZone(el, onFiles) {
  ["dragenter", "dragover"].forEach((e) => el.addEventListener(e, (ev) => { ev.preventDefault(); el.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach((e) => el.addEventListener(e, (ev) => { ev.preventDefault(); if (e === "dragleave" && el.contains(ev.relatedTarget)) return; el.classList.remove("dragging"); }));
  el.addEventListener("drop", (ev) => { if (ev.dataTransfer.files.length) onFiles([...ev.dataTransfer.files]); });
}

/* ---------------- start screen ---------------- */
async function loadExamples() {
  const longitudinal = await api("/api/samples/longitudinal").catch(() => []);
  S.examples = (await api("/api/samples")).concat(longitudinal);
  $("examples").innerHTML = S.examples.map((x, i) => `<button type="button" data-i="${i}" title="${esc(x.note)}">${esc(x.title)}</button>`).join("");
}
$("examples").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  const x = S.examples[+b.dataset.i];
  $("report").value = x.report;
  if (x.prior) {
    $("priorReport").value = x.prior.report; $("priorDate").value = x.prior.prior_date;
    $("curDate").value = x.prior.current_date || today(); setModality(x.prior.modality); showPrior(true);
  } else showPrior(false);
  $("report").focus();
});

/* ---------------- prior study ---------------- */
function showPrior(open) {
  $("prior").hidden = !open; $("priorBtn").setAttribute("aria-expanded", open);
  $("priorBtn").textContent = open ? "Hide prior study" : "Add prior study";
}
function setModality(m) {
  S.mod = m; [...$("priorMod").children].forEach((x) => x.setAttribute("aria-pressed", x.dataset.m === m));
}
$("priorBtn").addEventListener("click", () => { const open = $("prior").hidden; showPrior(open); if (open) $("priorReport").focus(); });
$("priorMod").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setModality(b.dataset.m); });
$("curDate").value = today();
function priorInput() {
  if ($("prior").hidden || !$("priorReport").value.trim()) return null;
  if (!$("priorDate").value) throw new Error("Add the prior exam date");
  return { report: $("priorReport").value.trim(), prior_date: $("priorDate").value, current_date: $("curDate").value || today(), modality: S.mod };
}
$("optBtn").addEventListener("click", () => {
  const open = $("options").hidden; $("options").hidden = !open; $("optBtn").setAttribute("aria-expanded", open);
});
$("depth").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  S.samples = +b.dataset.n; [...$("depth").children].forEach((x) => x.setAttribute("aria-pressed", x === b));
});
$("tol").addEventListener("input", () => { $("tolVal").textContent = `±${$("tol").value} mm`; });
$("file").addEventListener("change", async (e) => { const f = e.target.files[0]; if (f) await loadFile(f); e.target.value = ""; });
dropZone($("composer"), (files) => loadFile(files[0]));
async function loadFile(f) {
  try { $("report").value = await fileToText(f); toast(`Loaded ${f.name}`); } catch (e) { toast(e.message); }
}
$("report").addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") analyse(); });
$("go").addEventListener("click", analyse);
$("back").addEventListener("click", () => { $("result").hidden = true; $("start").hidden = false; window.scrollTo({ top: 0 }); });

async function analyse() {
  const report = $("report").value.trim();
  if (report.length < 10) { toast("Paste a report first"); $("report").focus(); return; }
  let prior;
  try { prior = priorInput(); } catch (e) { toast(e.message); $("priorDate").focus(); return; }
  const btn = $("go"); btn.disabled = true;
  btn.innerHTML = `<span class="spin"></span>${S.samples > 1 ? "Reading 3×" : "Reading"}`;
  try {
    S.a = await api("/api/analyse", { report, extractor: "auto", samples: S.samples, size_tolerance_mm: +$("tol").value, high_risk: $("risk").checked, prior });
    S.a.observations.forEach((o) => { o.spread = o.confidence.size.spread_mm || 0; });
    S.obs = 0; S.undo = null; S.addendum = null; S.prevEnv = null;
    await refreshReview();
    $("start").hidden = true; $("result").hidden = false; window.scrollTo({ top: 0 });
    renderAll();
  } catch (e) { toast(e.message); }
  btn.disabled = false; btn.textContent = "Analyse";
}

/* ---------------- result ---------------- */
function renderAll() { renderSwitch(); renderReport(); renderFindings(); renderDecision(); }

function renderSwitch() {
  const obs = S.a.observations;
  $("obsSwitch").innerHTML = obs.length > 1
    ? `<div class="seg" role="group" aria-label="Observation">${obs.map((o, i) => `<button type="button" data-o="${i}" aria-pressed="${i === S.obs}">${esc(o.label)}</button>`).join("")}</div>` : "";
}
$("obsSwitch").addEventListener("click", (e) => { const b = e.target.closest("button[data-o]"); if (!b) return; S.obs = +b.dataset.o; renderAll(); });

function renderReport() {
  const text = S.a.report, low = text.toLowerCase(), spans = [];
  S.a.observations.forEach((o, oi) => {
    const start = Math.max(0, low.indexOf(o.text.toLowerCase().slice(0, 40)));
    const add = (ev, cls) => {
      if (!ev) return;
      let i = low.indexOf(ev.toLowerCase(), start); if (i < 0) i = low.indexOf(ev.toLowerCase()); if (i < 0) return;
      if (spans.some((s) => i < s.e && i + ev.length > s.s)) return;
      spans.push({ s: i, e: i + ev.length, cls: cls + (oi !== S.obs ? " dim" : "") });
    };
    FEATURES.forEach(([k]) => add(o.extraction[k].evidence, o.features[k]));
    add(o.extraction.size_evidence, "size");
  });
  spans.sort((x, y) => x.s - y.s);
  let html = "", p = 0;
  spans.forEach((s) => { html += esc(text.slice(p, s.s)) + `<mark class="${s.cls}">${esc(text.slice(s.s, s.e))}</mark>`; p = s.e; });
  $("reportView").innerHTML = html + esc(text.slice(p));
}

function renderFindings() {
  const o = S.a.observations[S.obs];
  const x = S.a.extractor;
  $("findingsNote").textContent = o.edited ? "Edited · updates instantly" : (x.used || "").startsWith("Lexicon") ? "Basic reading mode" : "Change any finding to update the result";
  const rows = FEATURES.map(([k, label]) => {
    const st = o.features[k], c = o.confidence[k] || {}, lg = o.longitudinal;
    let ev = o.extraction[k].evidence;
    if (lg && lg.reported_evidence && k in lg.reported_evidence) {
      ev = (k === "growth" && lg.applied) || (lg.ancillary_added || []).includes(k) ? FROM_PRIOR : lg.reported_evidence[k];
    }
    const unsure = c.source === "extractor" ? `<span class="fu">The AI read this differently across runs (${Math.round(c.agreement * 100)}% agreement), so it is treated as possible.</span>` : "";
    const evText = ev === FROM_PRIOR ? FROM_PRIOR : ev ? "“" + esc(ev) + "”" : "Not mentioned in the report";
    return `<li><span class="fn">${label}</span>
      <select data-k="${k}" class="${st}" aria-label="${label}">${Object.entries(STATE_LABEL).map(([v, t]) => `<option value="${v}" ${v === st ? "selected" : ""}>${t}</option>`).join("")}</select>
      <span class="fe" title="${esc(ev)}">${evText}</span>${unsure}</li>`;
  }).join("");
  const tol = (+$("tol").value + o.spread / 2);
  const sz = o.confidence.size || {};
  const fix = "corrected_from" in sz && !o.sizeEdited
    ? `<li class="size-fix"><span class="muted">Size taken from the report text (${sz.corrected_from == null ? "the AI found no size" : `the AI read ${esc(sz.corrected_from)} mm`})</span></li>` : "";
  $("findings").innerHTML = rows + `<li class="size-line"><span>Size</span><input id="sizeIn" type="number" min="0" step="0.5" value="${o.size_mm ?? ""}" aria-label="Size in millimetres"><span>mm · considered ±${tol.toFixed(1)} mm</span></li>` + fix;
}
$("findings").addEventListener("change", (e) => {
  const o = S.a.observations[S.obs];
  if (e.target.matches("select[data-k]")) o.features[e.target.dataset.k] = e.target.value;
  else if (e.target.id === "sizeIn") { const v = parseFloat(e.target.value); o.size_mm = isNaN(v) ? null : v; o.sizeEdited = true; }
  else return;
  o.edited = true; recompute();
});

async function recompute() {
  const base = +$("tol").value, obs = S.a.observations;
  const body = { high_risk: $("risk").checked, observations: obs.map((o) => ({ label: o.label, features: o.features, size_mm: o.size_mm, size_tolerance_mm: base + o.spread / 2, defer_reasons: o.defer_reasons, longitudinal: o.longitudinal || null })) };
  try {
    const r = await api("/api/recompute", body);
    r.observations.forEach((x, i) => {
      obs[i].result = x.result;
      if (x.longitudinal) obs[i].longitudinal = x.longitudinal;
      if (x.features) obs[i].features = x.features;          // the prior comparison may change growth
      if (obs[i].audit && x.result.status === "assigned") { obs[i].audit.computed = x.result.acr_category; obs[i].audit.contradiction = obs[i].audit.stated !== x.result.acr_category; }
    });
    Object.assign(S.a, { exam: r.exam, impression: r.impression, consistency: r.consistency });
    await refreshReview();
    renderAll();
  } catch (e) { toast(e.message); }
}

/* report check, completeness and impression diff for the current analysis */
async function refreshReview() {
  try { S.review = await api("/api/review", S.a); } catch (e) { S.review = null; }
}

function meter(c) {
  if (!c) return "";
  const pct = Math.round(c.score * 100);
  return `<div class="meter"><div class="meter-label"><span>Documentation</span><span>${c.documented}/${c.total}</span></div>
    <div class="meter-bar"><span style="width:${pct}%"></span></div>
    ${c.missing_labels.length ? `<div class="note">Missing: ${c.missing_labels.map(esc).join(", ")}</div>` : ""}</div>`;
}

function diffHtml(diff, side) {
  return diff.filter((d) => d.op === "equal" || d.op === (side === "stated" ? "delete" : "insert"))
    .map((d) => (d.op === "equal" ? esc(d.text) : `<mark class="${d.op === "delete" ? "del" : "ins"}">${esc(d.text)}</mark>`)).join(" ");
}

function reportCheckCard(rv) {
  const chk = rv && rv.check;
  if (!chk) return "";
  const [cls, icon] = CHECK_STATE[chk.status] || ["review", "info"];
  const diff = S.review && S.review.diff && S.review.diff.length
    ? `<details class="diff"><summary>Compare impressions word by word</summary><div class="diff-cols">
        <div><div class="kicker">Stated in the report</div><p>${diffHtml(S.review.diff, "stated")}</p></div>
        <div><div class="kicker">Generated from the findings</div><p>${diffHtml(S.review.diff, "generated")}</p></div></div></details>` : "";
  return `<div class="card flat check"><div class="kicker">Report check</div>
    <div class="check-row"><span class="cc">Stated${pill(chk.stated)}</span><span class="arrow">→</span><span class="cc">Rules${pill(chk.computed)}</span></div>
    ${stateBlock(cls, icon, esc(chk.label), chk.status === "inside_envelope" ? "The stated category is possible only if an uncertain finding is resolved." : chk.status === "contradicts" ? "No completion of the documented findings supports the stated category." : "")}
    ${diff}</div>`;
}

function addendumBlock() {
  if (!S.addendum || S.addendum.obs !== S.obs) return S.undo && S.undo.obs === S.obs ? `<div class="addendum"><button type="button" id="undo">Undo last answer</button></div>` : "";
  return `<div class="addendum"><div class="kicker">Suggested addendum</div><p id="addText">${esc(S.addendum.text)}</p>
    <div class="btns"><button type="button" id="copyAdd">Copy</button>${S.undo ? '<button type="button" id="undo">Undo</button>' : ""}</div></div>`;
}

function stateBlock(cls, icon, title, body) { return `<div class="state ${cls}">${ICON[icon]}<div><b>${title}</b>${body}</div></div>`; }

function priorCard(lg) {
  const sub = [lg.prior_modality, lg.prior_date].filter(Boolean).map(esc).join(" · ");
  let body;
  if (lg.matching === "none") {
    body = stateBlock("review", "info", "Not compared", esc(lg.explanation));
  } else if (lg.rule === "prior_modality_invalid") {
    body = stateBlock("review", "info", "Ultrasound priors cannot be used for LI-RADS growth", "Add a prior CT or MRI to assess growth.");
  } else if (lg.percent_change == null) {
    body = stateBlock("review", "info", "Growth not assessed", esc(lg.explanation));
  } else {
    const months = (lg.interval_days / 30.44).toFixed(1);
    const pct = `${lg.percent_change > 0 ? "+" : ""}${Math.round(lg.percent_change)}%`;
    body = `<div class="meaning">${lg.prior_mm} → ${lg.current_mm} mm</div>
      <div class="note">${pct} in ${lg.interval_days} days (${months} months) · matched by ${lg.matching === "segment" ? "segment" : "order"}</div>
      ${lg.measurement_dependent ? stateBlock("critical", "warn", "Depends on the measurement", `Within ±${lg.tolerance_mm} mm the change ranges from ${Math.round(lg.percent_range[0])}% to ${lg.percent_range[1] == null ? "more" : Math.round(lg.percent_range[1]) + "%"}.`) : ""}
      <div class="rec"><div class="kicker">${esc(GROWTH_OUTCOME[lg.rule] || "Rule outcome")}</div><p>${esc(lg.explanation)}</p></div>`;
  }
  const conflict = lg.prior_conflict ? stateBlock("conflict", "warn", "The prior study disagrees with the report", esc(lg.prior_conflict)) : "";
  return `<div class="card flat compare"><div class="kicker">Compared with prior${sub ? " · " + sub : ""}</div>${body}${conflict}</div>`;
}

function renderDecision() {
  const a = S.a, o = a.observations[S.obs], r = o.result;
  const rv = S.review && S.review.observations ? S.review.observations[S.obs] : null;
  let html = "";
  if (a.observations.length > 1) {
    html += `<div class="card flat exam"><span>${a.exam.observations} observations · highest</span><b>${pill(a.exam.highest_category)}</b></div>`;
  }
  if (r.status !== "assigned") {
    const title = r.status === "defer" ? "Needs radiologist review" : r.status === "not_applicable" ? "LI-RADS does not apply" : "Category cannot be assigned";
    html += `<div class="card"><div class="kicker">${esc(o.label)}</div><div class="cat" style="color:var(--faint)">—</div><div class="meaning">${title}</div>
      ${stateBlock("review", "info", "Why", r.reasons.map(esc).join("<br>"))}${meter(rv && rv.completeness)}</div>`;
  } else {
    const pc = r.acr_category, env = new Set(r.envelope);
    const others = r.envelope.filter((c) => c !== pc);
    let banner;
    if (r.decision_critical) {
      banner = stateBlock("critical", "warn", "Could change management", `The findings support ${r.envelope[0]} to ${r.envelope[r.envelope.length - 1]}. Answer the question below before signing.`);
    } else if (others.length) {
      banner = stateBlock("safe", "ok", "Safe to sign", "Other categories are possible, but the recommended management is the same.");
    } else {
      banner = stateBlock("safe", "ok", "Safe to sign", "The documented findings support a single category.");
    }
    const conflict = o.audit && o.audit.contradiction
      ? stateBlock("conflict", "warn", "The impression disagrees", `The report says ${esc(o.audit.stated)}, but its findings support ${esc(pc)}.`) : "";
    const prev = S.prevEnv && S.prevEnv.obs === S.obs ? S.prevEnv.cats : null;
    const track = CATS.map((c) => {
      const cls = c === pc ? "point" : env.has(c) ? "reach" : prev && prev.has(c) ? "leaving" : "";
      return `<div class="${cls}" style="${hue(c)}">${c.slice(3)}</div>`;
    }).join("");
    const notes = CATS.map((c) => `<span>${c === pc ? "ACR" : env.has(c) ? esc("if " + r.witnesses[c].if.join(", ").replace(">=", "≥")) : ""}</span>`).join("");
    let ask = "";
    if (r.decision_critical && r.decisive_questions.length) {
      ask = r.decisive_questions.map((q, qi) => q.feature === "size"
        ? `<div class="ask${qi ? " minor" : ""}"><div class="q">Re-measure the observation.</div><div class="qs">The size sits near a cut-off. Measured exactly, it is ${orList(q.if_exact)}.</div><div class="btns"><button type="button" data-exact="1">Measurement is exact</button></div></div>`
        : `<div class="ask${qi ? " minor" : ""}"><div class="q">${esc(q.question)}</div><div class="qs">Present gives ${orList(q.if_yes)}. Absent gives ${orList(q.if_no)}.</div><div class="btns"><button type="button" data-k="${q.feature}" data-v="present">Present</button><button type="button" data-k="${q.feature}" data-v="absent">Absent</button></div></div>`).join("");
    }
    ask += addendumBlock();
    const tie = r.tie_break_features.length && others.length
      ? `<div class="note">${r.tie_break_features.map((k) => FEATURES.find((f) => f[0] === k)[1].toLowerCase()).join(" and ")} not confirmed, counted as absent (ACR rule)</div>` : "";
    html += `<div class="card">
      <div class="kicker">${esc(o.label)} · LI-RADS</div>
      <div class="cat" style="color:var(--lr${pc[3]})">${pc}</div>
      <div class="meaning">${esc(r.meaning[0].toUpperCase() + r.meaning.slice(1))}</div>${tie}
      ${banner}${conflict}
      <div class="range"><div class="range-label"><span>Possible categories</span><span>${r.envelope.length === 1 ? "one" : r.envelope.length}</span></div>
        <div class="track">${track}</div><div class="track-notes">${notes}</div></div>
      ${ask}${meter(rv && rv.completeness)}
      <div class="rec"><div class="kicker">Recommendation</div><p>${esc(r.management.find((m) => m.category === pc).action)}</p></div>
      <details><summary>Why ${pc}</summary>
        <ol class="path">${r.trace.map((s) => `<li><span>${esc(s.step)}</span><span>${esc(s.value.replace("->", "→"))}</span></li>`).join("")}</ol>
        ${others.length ? `<ul class="others">${others.map((c) => `<li>${c}: ${esc(r.management.find((m) => m.category === c).action)}</li>`).join("")}</ul>` : ""}
      </details>
    </div>`;
  }
  html += reportCheckCard(rv);
  if (o.longitudinal) html += priorCard(o.longitudinal);
  html += `<div class="card flat impression"><div class="kicker"><span>Draft impression</span><span class="actions"><button type="button" id="copy">Copy</button><button type="button" id="download">Download</button><button type="button" id="fhir">Export FHIR</button></span></div>
    <pre>${esc(a.impression)}</pre>
    ${a.consistency.consistent ? `<div class="verified">${ICON.ok}Matches the rule-based category</div>` : ""}</div>`;
  $("decision").innerHTML = html;
  if (S.prevEnv) setTimeout(() => { S.prevEnv = null; }, 0);       // the narrowing animates once
}
$("decision").addEventListener("click", async (e) => {
  if (e.target.id === "copy") { try { await navigator.clipboard.writeText(S.a.impression); toast("Impression copied"); } catch (err) { toast("Copy is not available here"); } return; }
  if (e.target.id === "download") { downloadReport(); return; }
  if (e.target.id === "fhir") { exportFhir(); return; }
  if (e.target.id === "copyAdd") { try { await navigator.clipboard.writeText(S.addendum.text); toast("Addendum copied"); } catch (err) { toast("Copy is not available here"); } return; }
  if (e.target.id === "undo") { undoAnswer(); return; }
  const b = e.target.closest(".ask button"); if (!b) return;
  const o = S.a.observations[S.obs];
  S.undo = { obs: S.obs, features: { ...o.features }, size_mm: o.size_mm, tol: $("tol").value,
             spreads: S.a.observations.map((x) => x.spread), addendum: S.addendum };
  S.prevEnv = { obs: S.obs, cats: new Set(o.result.envelope || []) };
  let req;
  if (b.dataset.exact) {
    $("tol").value = 0; $("tolVal").textContent = "±0 mm"; S.a.observations.forEach((x) => (x.spread = 0));
    req = { feature: "size", size_mm: o.size_mm, label: o.label };
  } else {
    o.features[b.dataset.k] = b.dataset.v;
    req = { feature: b.dataset.k, state: b.dataset.v, label: o.label };
  }
  try { S.addendum = { obs: S.obs, text: (await api("/api/addendum", req)).sentence }; } catch (err) { S.addendum = null; }
  o.edited = true; recompute();
});
function undoAnswer() {
  const u = S.undo; if (!u) return;
  const o = S.a.observations[u.obs];
  o.features = u.features; o.size_mm = u.size_mm;
  $("tol").value = u.tol; $("tolVal").textContent = `±${u.tol} mm`;
  S.a.observations.forEach((x, i) => (x.spread = u.spreads[i]));
  S.addendum = u.addendum; S.undo = null; S.prevEnv = null;
  recompute(); toast("Last answer undone");
}
function saveFile(name, text, type) {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob), link = document.createElement("a");
  link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url);
}
async function exportFhir() {
  try {
    const bundle = await api("/api/export/fhir", S.a);
    saveFile("lirads-report.fhir.json", JSON.stringify(bundle, null, 2), "application/fhir+json");
    toast("FHIR bundle downloaded");
  } catch (e) { toast(e.message); }
}
function downloadReport() {
  const lines = [S.a.impression, "", "FINDINGS USED", ...S.a.observations.flatMap((o) => [
    `${o.label}: size ${o.size_mm ?? "not stated"} mm`, ...FEATURES.map(([k, l]) => `  ${l}: ${STATE_LABEL[o.features[k]]}`)]),
  "", `Rules: ${S.a.rules}`, `Generated: ${new Date().toLocaleString()}`];
  const blob = new Blob([lines.join("\n")], { type: "text/plain" });
  const url = URL.createObjectURL(blob), link = document.createElement("a");
  link.href = url; link.download = "lirads-impression.txt"; link.click(); URL.revokeObjectURL(url);
}

/* ---------------- batch ---------------- */
const batchFiles = [];
$("batchExamples").addEventListener("click", () => { $("batchText").value = S.examples.filter((x) => !x.prior).map((x) => x.report).join("\n---\n"); });
$("batchFiles").addEventListener("change", async (e) => { await addBatchFiles([...e.target.files]); e.target.value = ""; });
dropZone($("batchComposer"), addBatchFiles);
async function addBatchFiles(files) {
  const texts = [];
  for (const f of files) { try { texts.push(await fileToText(f)); } catch (err) { toast(`${f.name}: ${err.message}`); } }
  if (texts.length) { const cur = $("batchText").value.trim(); $("batchText").value = [cur, ...texts].filter(Boolean).join("\n---\n"); toast(`${texts.length} file(s) added`); }
}
$("batchGo").addEventListener("click", async () => {
  const reports = $("batchText").value.split(/\n\s*---\s*\n/).map((s) => s.trim()).filter((s) => s.length > 10);
  if (!reports.length) { toast("Add at least one report"); return; }
  const b = $("batchGo"); b.disabled = true; b.innerHTML = `<span class="spin"></span>Checking ${reports.length}`;
  try {
    const out = await api("/api/audit", { reports, extractor: "auto" });
    S.batch = reports; S.batchRows = out.rows;
    const s = out.summary;
    const flagFor = (r) => {
      const st = r.check && r.check.status;
      if (st === "contradicts") return '<span class="flag conflict">Contradicts the rules</span>';
      if (st === "inside_envelope") return '<span class="flag critical">Inside envelope, not ACR</span>';
      if (r.status !== "assigned") return '<span class="flag review">Needs review</span>';
      if (r.critical) return '<span class="flag critical">Could change management</span>';
      return '<span class="flag ok">Consistent</span>';
    };
    $("batchOut").innerHTML = `<div class="summary">
        <div><b>${s.observations}</b><span>observations</span></div>
        <div><b style="color:var(--lr5)">${s.reports_contradicting_rules}</b><span>contradict the rules</span></div>
        <div><b style="color:var(--warn)">${s.decision_critical}</b><span>could change management</span></div>
        <div><b>${s.needs_review}</b><span>need review</span></div>
        <div><b>${s.mean_completeness == null ? "—" : Math.round(s.mean_completeness * 100) + "%"}</b><span>documentation</span></div></div>
      <div class="batch-bar"><span>${s.reports_contradicting_rules} of ${s.reports} reports contradict the rules${s.most_missing ? ` · most often missing: ${esc(s.most_missing.toLowerCase())} (${s.most_missing_count})` : ""}</span>
        <button type="button" class="opt-btn" id="batchCsv">Export CSV</button></div>
      <div class="rows">${out.rows.map((r) => {
        const c = r.completeness;
        const doc = c ? `Documentation ${c.documented}/${c.total}${c.missing_labels.length ? " · missing " + c.missing_labels.map((x) => x.toLowerCase()).join(", ") : ""}` : "";
        return `<div class="rowi" data-r="${r.report - 1}" role="button" tabindex="0"><span class="n">${r.report}</span><span class="tx"><b>${esc(r.label)}</b><span>${esc(r.excerpt)}</span><span class="doc">${esc(doc)}</span></span>
          <span class="cc">Stated${pill(r.stated)}</span><span class="cc">Computed${pill(r.computed)}</span>${flagFor(r)}</div>`;
      }).join("")}</div>`;
  } catch (e) { toast(e.message); }
  b.disabled = false; b.textContent = "Check reports";
});
$("batchOut").addEventListener("click", async (e) => {
  if (e.target.id === "batchCsv") {
    try {
      const r = await fetch("/api/audit/csv", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rows: S.batchRows || [] }) });
      if (!r.ok) throw new Error(r.statusText);
      saveFile("lirads-batch.csv", await r.text(), "text/csv"); toast("CSV downloaded");
    } catch (err) { toast(err.message); }
    return;
  }
  const row = e.target.closest(".rowi"); if (!row) return;
  $("report").value = S.batch[+row.dataset.r]; location.hash = "#analyse"; analyse();
});
$("batchOut").addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.classList.contains("rowi")) e.target.click(); });

/* ---------------- boot ---------------- */
route(); status(); loadExamples();
