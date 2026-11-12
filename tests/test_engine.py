"""Rule engine: table correctness, formal properties of the envelope, guards."""
import copy
from itertools import product

import pytest

from radsenvelope.engine.envelope import (ABSENT, NOT_DOCUMENTED, PRESENT, STATES, UNCERTAIN, Observation,
                                          analyse, completions, envelope)
from radsenvelope.engine.ruleset import FEATURES, RuleSet, RuleSetError, get_ruleset, rank

RS = get_ruleset()


def reference(aphe, size, w, c, g, mal, ben):
    """Independent transcription of the LI-RADS v2018 CT/MRI diagnostic table."""
    n = w + c + g
    if aphe:
        if size < 10:
            cat = "LR-3" if n == 0 else "LR-4"
        elif size < 20:
            cat = "LR-3" if n == 0 else ("LR-4" if (n == 1 and c) else "LR-5")
        else:
            cat = "LR-4" if n == 0 else "LR-5"
    else:
        cat = ("LR-4" if n >= 2 else "LR-3") if size < 20 else ("LR-3" if n == 0 else "LR-4")
    if mal and ben:
        return cat
    r = int(cat[-1])
    if mal and r < 4:
        r += 1
    elif ben and r > 2:
        r -= 1
    return f"LR-{r}"


SIZES = [3, 9.99, 10, 15, 19.99, 20, 45]


@pytest.mark.parametrize("bits", list(product([0, 1], repeat=6)))
def test_table_matches_reference(bits):
    f = dict(zip(FEATURES, map(bool, bits)))
    for s in SIZES:
        assert RS.categorize(f, s) == reference(bits[0], s, *bits[1:]), (f, s)


def test_core_table_is_monotone():
    """Adding a major feature or growing the observation never lowers the core category."""
    for bits in product([0, 1], repeat=4):
        f = dict(zip(FEATURES, map(bool, bits + (0, 0))))
        for s1, s2 in zip(SIZES, SIZES[1:]):
            assert rank(RS.categorize(f, s1)) <= rank(RS.categorize(f, s2))
        for k in ("aphe", "washout", "capsule", "growth"):
            if not f[k]:
                g = dict(f, **{k: True})
                for s in SIZES:
                    assert rank(RS.categorize(f, s)) <= rank(RS.categorize(g, s))


def test_trace_ends_in_category():
    for bits in product([0, 1], repeat=6):
        f = dict(zip(FEATURES, map(bool, bits)))
        for s in SIZES:
            assert RS.trace(f, s)[-1]["value"] == RS.categorize(f, s)


def test_incomplete_ruleset_is_rejected():
    raw = copy.deepcopy(RS.raw)
    del raw["core_table"]["no_aphe"]["10-19"]
    with pytest.raises(RuleSetError):
        RuleSet(raw).validate()
    raw = copy.deepcopy(RS.raw)
    del raw["management"]["LR-4"]
    with pytest.raises(RuleSetError):
        RuleSet(raw).validate()


def obs(size, tol=2.0, **states):
    base = {k: ABSENT for k in ("aphe", "washout", "capsule", "growth")}
    base.update(af_malignant=NOT_DOCUMENTED, af_benign=NOT_DOCUMENTED)
    base.update(states)
    return Observation(base, size, tol)


ALL_STATE_COMBOS = list(product(STATES, repeat=4))


def _brute_force(o: Observation) -> set:
    """Independent envelope: every completion of every unresolved feature, sizes on a fine grid."""
    unresolved = [k for k in FEATURES if o.features[k] in (UNCERTAIN, NOT_DOCUMENTED) and not
                  (k.startswith("af_") and o.features[k] == NOT_DOCUMENTED)]
    grid = [round(o.size_mm - o.size_tolerance_mm + i * 0.05, 2)
            for i in range(int(o.size_tolerance_mm * 40) + 1)] or [o.size_mm]
    cats = set()
    for combo in product([False, True], repeat=len(unresolved)):
        f = {k: o.features[k] == PRESENT for k in FEATURES}
        f.update(zip(unresolved, combo))
        for s in grid:
            if s > 0:
                cats.add(RS.categorize(f, s))
    return cats


@pytest.mark.parametrize("size,tol", [(8, 2.0), (18, 2.0), (19, 1.0), (24, 1.0), (30, 0.0)])
def test_envelope_sound_and_complete(size, tol):
    """The enumerated envelope equals an independent brute-force envelope for every state combination."""
    for combo in ALL_STATE_COMBOS:
        o = obs(size, tol, **dict(zip(("aphe", "washout", "capsule", "growth"), combo)))
        assert envelope(o) == _brute_force(o), combo


def test_point_category_and_witnesses():
    for combo in ALL_STATE_COMBOS:
        r = analyse(obs(17, **dict(zip(("aphe", "washout", "capsule", "growth"), combo))))
        assert r["acr_category"] in r["envelope"]
        assert set(r["witnesses"]) == set(r["envelope"])
        assert r["witnesses"][r["acr_category"]]["assumptions"] == 0


def test_decisive_answer_never_widens_envelope():
    for combo in ALL_STATE_COMBOS:
        o = obs(18, **dict(zip(("aphe", "washout", "capsule", "growth"), combo)))
        r = analyse(o)
        for q in r["decisive_questions"]:
            if q["feature"] == "size":
                continue
            assert set(q["if_yes"]) <= set(r["envelope"]) and set(q["if_no"]) <= set(r["envelope"])


def test_named_cases():
    r = analyse(obs(25, aphe=PRESENT, washout=PRESENT, capsule=PRESENT))
    assert (r["acr_category"], r["envelope"], r["decision_critical"]) == ("LR-5", ["LR-5"], False)
    r = analyse(obs(18, aphe=PRESENT, washout=UNCERTAIN, growth=NOT_DOCUMENTED))
    assert (r["acr_category"], r["envelope"], r["decision_critical"]) == ("LR-3", ["LR-3", "LR-4", "LR-5"], True)
    assert r["witnesses"]["LR-5"]["if"] == ["washout present"]
    r = analyse(obs(19, aphe=PRESENT))
    assert r["envelope"] == ["LR-3", "LR-4"] and r["near_size_cutoff"]
    assert any(q["feature"] == "size" for q in r["decisive_questions"])
    r = analyse(obs(24, tol=1.0, aphe=PRESENT, washout=PRESENT, capsule=UNCERTAIN))
    assert r["acr_category"] == "LR-5" and not r["decision_critical"]


def test_completion_count_is_bounded():
    o = obs(19, aphe=UNCERTAIN, washout=UNCERTAIN, capsule=UNCERTAIN, growth=UNCERTAIN,
            af_malignant=UNCERTAIN, af_benign=UNCERTAIN)
    assert len(list(completions(o))) <= 2 ** 6 * 5


def test_guards():
    assert analyse(Observation({}, None))["status"] == "not_assignable"
    assert analyse(Observation({}, 20, high_risk=False))["status"] == "not_applicable"
    assert analyse(Observation({}, 20, defer_reasons=["x"]))["status"] == "defer"
