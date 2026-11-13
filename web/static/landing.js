"use strict";
// Landing page v2. Result numbers come from /api/headline (committed result files); the example's results come
// from /static/landing_demo.json, computed by the rule engine (data_tools/landing_demo.py). Nothing is hard-coded.
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const $ = (id) => document.getElementById(id);
const pct = (v) => `${Math.round(v * 1000) / 10}%`;

function countUp(el, target, fmt) {
  if (reduce || !("IntersectionObserver" in window)) { el.textContent = fmt(target); return; }
  const io = new IntersectionObserver((entries) => {
    if (!entries.some((e) => e.isIntersecting)) return;
    io.disconnect();
    const t0 = performance.now(), dur = 900;
    const tick = (t) => {
      const p = Math.min(1, (t - t0) / dur), eased = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(target * eased);
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, { threshold: 0.4 });
  el.textContent = fmt(0);
  io.observe(el);
}

(async function headline() {
  try {
    const r = await fetch("/api/headline");
    if (!r.ok) return;
    const h = await r.json();
    const rob = h.b1_contradiction.robustness, real = h.b1_contradiction.real_dev;
    if (rob) {
      countUp($("statB1"), rob.value, pct);
      $("problemNumber").textContent = `of ${rob.n} generated reports contradicted the model's own findings (95% CI ${pct(rob.ci95[0])}–${pct(rob.ci95[1])})`;
    }
    if (real) $("statB1Real").textContent = `and ${real.k} of ${real.n} real published cases`;
    const ours = h.rule_contradiction && (h.rule_contradiction.robustness || h.rule_contradiction.real_dev);
    if (ours) {
      countUp($("statOurs"), ours.k, (v) => String(Math.round(v)));
      $("statOursSub").textContent = `of ${ours.n} generated reports. By construction: the rule table computes the category.`;
    }
    $("problemSource").textContent =
      "Contradiction = the model's category differs from the ACR table applied to the model's own features. "
      + "Generated reports have rule-generated gold (robustness test); real cases are development cases. See the evaluation documentation.";
  } catch (e) { /* keep the static text */ }
})();

(async function demo() {
  let d;
  try { d = await (await fetch("/static/landing_demo.json")).json(); } catch (e) { return; }
  const report = $("demoReport"), track = [...$("demoTrack").children], cat = $("demoCat");
  // evidence highlights from the engine's extraction; the hedged feature gets the warning colour
  let html = d.report.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  for (const [feat, ev] of Object.entries(d.evidence)) {
    const cls = d.features[feat] === "uncertain" ? "hedge" : "";
    html = html.replace(ev, `<mark class="${cls}">${ev}</mark>`);
  }
  report.innerHTML = html;
  $("demoQ").textContent = d.question.text;
  $("demoLabel").textContent = d.label;
  $("demoRules").textContent = d.rules;
  const mg = [...$("bigMgmt").children];                       // management text straight from the rule file
  (d.categories || []).forEach((c, i) => { if (mg[i]) mg[i].textContent = c.management; });

  const show = (res, answered) => {
    cat.textContent = res.acr_category; cat.dataset.cat = res.acr_category;
    $("demoMeaning").textContent = res.meaning;
    const st = $("demoState");
    st.className = `state ${res.decision_critical ? "warn" : "good"}`;
    st.textContent = res.decision_critical ? "Could change management" : "Safe to sign";
    track.forEach((t) => {
      const inEnv = res.envelope.includes(t.dataset.c);
      t.classList.toggle("point", inEnv && res.envelope.length === 1);
      t.classList.toggle("reach", inEnv && res.envelope.length > 1);
    });
    $("demoReset").hidden = !answered;
  };
  const buttons = [...document.querySelectorAll("#demoAsk [data-answer]")];
  buttons.forEach((b) => b.addEventListener("click", () => {
    buttons.forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    show(d.answers[b.dataset.answer], true);
  }));
  $("demoReset").addEventListener("click", () => {
    buttons.forEach((x) => x.setAttribute("aria-pressed", "false"));
    show(d.documented, false);
  });

  // the envelope opens from the computed point to the full range
  if (reduce) { show(d.documented, false); return; }
  show({ ...d.documented, envelope: [d.documented.acr_category], decision_critical: d.documented.decision_critical }, false);
  setTimeout(() => show(d.documented, false), 700);
})();

(function story() {
  const steps = [...document.querySelectorAll(".story .step")];
  if (reduce || !("IntersectionObserver" in window) || !steps.length) return;   // final states are the default
  document.querySelector(".story").classList.add("play");
  const io = new IntersectionObserver((entries) => entries.forEach((en) => {
    if (!en.isIntersecting) return;
    const i = steps.indexOf(en.target);
    setTimeout(() => {
      en.target.classList.add("in");
      if (i === 2) setTimeout(() => en.target.classList.add("narrow"), 900);
    }, i * 250);
    io.unobserve(en.target);
  }), { threshold: 0.5 });
  steps.forEach((s) => io.observe(s));
})();
