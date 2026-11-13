"use strict";
// Numbers are read from the committed result files through /api/headline; nothing is hard-coded.
(async function headline() {
  const pct = (p) => `${Math.round(p.value * 1000) / 10}%`;
  try {
    const r = await fetch("/api/headline");
    if (!r.ok) return;
    const h = (await r.json()).b1_contradiction;
    const rob = h.robustness, real = h.real_dev;
    if (!rob && !real) return;
    const parts = [];
    if (real) parts.push(`<b>${real.k} of ${real.n}</b> real published cases`);
    if (rob) parts.push(`<b>${pct(rob)}</b> of ${rob.n} generated test reports (95% CI ${pct({ value: rob.ci95[0] })}–${pct({ value: rob.ci95[1] })})`);
    document.getElementById("problemNumber").innerHTML =
      `Asked directly for features and a category, the same local model contradicted its own findings in ${parts.join(" and in ")}.`;
    document.getElementById("problemSource").textContent =
      "Contradiction = the model's category differs from the ACR table applied to the model's own features. "
      + "Generated reports have rule-generated gold (robustness test); real cases are development cases. See the evaluation documentation.";
  } catch (e) { /* keep the static sentence */ }
})();

(function reveal() {
  const els = document.querySelectorAll(".reveal");
  if (!("IntersectionObserver" in window) || matchMedia("(prefers-reduced-motion: reduce)").matches) {
    els.forEach((e) => e.classList.add("in"));
    return;
  }
  const io = new IntersectionObserver((entries) => entries.forEach((en) => {
    if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
  }), { threshold: 0.12 });
  els.forEach((e) => io.observe(e));
})();
