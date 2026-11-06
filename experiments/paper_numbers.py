"""
Export every number quoted in the paper as a LaTeX macro.

    python -m experiments.paper_numbers      (run after experiments.analyze)

Writes paper/numbers.tex. In the paper a value is written as \\R{key}, e.g.
\\R{dafny.specloop_full.correct}. A key that does not exist prints a bold
??key in the PDF instead of silently disappearing, so a stale or missing
number is visible. Tables and figures are copied into paper/generated/.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

S = json.loads((ROOT / "results" / "summary.json").read_text(encoding="utf-8"))
LANG = {"dafny": "dafny", "python_icontract": "python"}
OUT: dict[str, str] = {}


def put(key: str, val, fmt: str = "{:.1f}"):
    if val is None or (isinstance(val, float) and val != val):
        return
    OUT[key] = fmt.format(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else str(val)


def pct(x):
    return None if x is None else 100 * x


def p_fmt(p):
    if p is None:
        return None
    return "< 0.001" if p < 0.001 else f"= {p:.3f}"


# --- main table -------------------------------------------------------------
for r in S.get("main", []):
    k = f"{LANG[r['language']]}.{r['config']}"
    put(f"{k}.correct", r["correct_mean"])
    put(f"{k}.correctsd", r["correct_sd"])
    put(f"{k}.verified", r["verified_mean"])
    put(f"{k}.tests", r["tests_mean"])
    put(f"{k}.intact", r["spec_intact"])
    put(f"{k}.attempts", r["attempts"], "{:.2f}")
    put(f"{k}.calls", r["llm_calls"], "{:.2f}")
    put(f"{k}.tokens", r["tokens"], "{:,.0f}")
    put(f"{k}.costrun", 1000 * r["cost_per_run"], "{:.2f}")          # in 1/1000 USD
    if r["cost_per_solved"] is not None:
        put(f"{k}.costsolved", 1000 * r["cost_per_solved"], "{:.2f}")
    put(f"{k}.wall", r["wall_s"], "{:.1f}")
    put(f"{k}.falsesuccess", r["false_success"])
    put(f"{k}.runs", r["runs"], "{:d}")

# --- gap tests ----------------------------------------------------------------
for gap, tests in S.get("gaps", {}).items():
    for name, t in tests.items():
        if not t.get("n_tasks"):
            continue
        parts = name.split("/")
        key = gap + "." + ".".join(LANG.get(x, x) for x in parts[1:])
        put(f"{key}.a", pct(t["a"]))
        put(f"{key}.b", pct(t["b"]))
        put(f"{key}.diff", pct(t["diff"]), "{:+.1f}")
        put(f"{key}.lo", pct(t["ci95"][0]), "{:+.1f}")
        put(f"{key}.hi", pct(t["ci95"][1]), "{:+.1f}")
        put(f"{key}.p", p_fmt(t["p_wilcoxon"]), "{}")
        put(f"{key}.pm", p_fmt(t["p_mcnemar"]), "{}")
        put(f"{key}.aonly", t["mcnemar_a_only"], "{:d}")
        put(f"{key}.bonly", t["mcnemar_b_only"], "{:d}")
        put(f"{key}.n", t["n_tasks"], "{:d}")

for name, v in S.get("proof_gap_ambiguity", {}).items():
    lang = LANG[name.split("/")[1]]
    put(f"ambig.{lang}.fails", v["failed_verifications"], "{:d}")
    put(f"ambig.{lang}.prooffails", v["with_all_tests_passing"], "{:d}")
    put(f"ambig.{lang}.share", 100 * v["share"])

# --- ablation -----------------------------------------------------------------
for r in S.get("ablation", []):
    k = f"abl.{LANG[r['language']]}.{r['variant'].replace(' ', '')}"
    put(f"{k}.correct", r["correct_mean"])
    put(f"{k}.sd", r["correct_sd"])
    if r.get("delta") is not None:
        put(f"{k}.delta", r["delta"], "{:+.1f}")
    if r.get("ci_lo") is not None:
        put(f"{k}.lo", r["ci_lo"], "{:+.1f}")
        put(f"{k}.hi", r["ci_hi"], "{:+.1f}")
    if r.get("p_wilcoxon") is not None:
        put(f"{k}.p", p_fmt(r["p_wilcoxon"]), "{}")
    if r.get("false_success") is not None:
        put(f"{k}.falsesuccess", r["false_success"])
    if r.get("spec_intact") is not None:
        put(f"{k}.intact", r["spec_intact"])

# --- reliability ----------------------------------------------------------------
for c, v in S.get("reliability", {}).items():
    for f in ("runs", "runs_with_guard_block", "false_success", "final_spec_violations",
              "strategy_switches", "runs_with_switch", "solved_after_switch"):
        put(f"rel.{c}.{f.replace('_', '')}", v[f], "{:d}")
    put(f"rel.{c}.toolshare", 100 * v["tool_seconds_share"])

# --- E2 -----------------------------------------------------------------------
for r in S.get("e2", []):
    k = f"etwo.{LANG[r['language']]}"
    put(f"{k}.pass", r["pass_at_1_tests"])
    put(f"{k}.nocompile", r["cannot_compile"])
    put(f"{k}.verified", r["verified_at_1"])
    put(f"{k}.correct", r["correct_at_1"])
    put(f"{k}.samples", r["samples"], "{:d}")
    put("etwo.verina.pass", r["verina_lean_pass_reported"])
    put("etwo.verina.nocompile", r["verina_lean_cannot_compile_reported"])

# --- failures -------------------------------------------------------------------
for r in S.get("failures", []):
    lang = LANG[r["model_language"].split("/")[1]]
    cat = "".join(ch for ch in r["category"].title() if ch.isalnum())
    put(f"fail.{lang}.{cat}", r["count"], "{:d}")
    put(f"fail.{lang}.{cat}.share", r["share"])
for lang in ("dafny", "python"):
    tot = sum(r["count"] for r in S.get("failures", []) if LANG[r["model_language"].split("/")[1]] == lang)
    put(f"fail.{lang}.total", tot, "{:d}")

# --- guard stress, equivalence, benchmark ---------------------------------------------
for k, v in S.get("guard_stress", {}).items():
    lang, what = k.split("/")
    base = f"guard.{LANG[lang]}.{what.replace('_', '')}"
    put(f"{base}.n", v["n"], "{:d}")
    put(f"{base}.rejects", v["guard_rejects"], "{:d}")
    put(f"{base}.veraccepts", v["verifier_accepts"], "{:d}")
    if "n_verified_check" in v:
        put(f"{base}.checked", v["n_verified_check"], "{:d}")
    if "verifier_accepts_and_guard_misses" in v:
        put(f"{base}.missed", v["verifier_accepts_and_guard_misses"], "{:d}")
eq = S.get("equivalence")
if eq:
    put("eq.inputs", eq["total_inputs"], "{:,d}")
    put("eq.agree", eq["total_agree"], "{:,d}")
    put("eq.tasks", eq["tasks"], "{:d}")
put("total.cost", S.get("total_cost_usd"), "{:.2f}")
put("total.runs", S.get("n_runs"), "{:,d}")

for k, ys in S.get("curves", {}).items():
    lang, cfg = k.split("/")
    for i, y in enumerate(ys, 1):
        put(f"curve.{LANG[lang]}.{cfg}.k{i}", y)
for k, n in S.get("solved_by_repair", {}).items():
    lang, cfg = k.split("/")
    put(f"repaired.{LANG[lang]}.{cfg}", n, "{:d}")
put("reused.ablation", S.get("n_reused_ablation_units"), "{:d}")

extra = ROOT / "results" / "extra_numbers.json"
if extra.exists():
    for k, v in json.loads(extra.read_text(encoding="utf-8")).items():
        OUT[k] = str(v)

lines = ["% generated by experiments/paper_numbers.py from results/summary.json -- do not edit",
         r"\makeatletter",
         r"\newcommand{\R}[1]{\ifcsname R@#1\endcsname\csname R@#1\endcsname\else\textbf{??\detokenize{#1}}\fi}"]
for k in sorted(OUT):
    v = OUT[k].replace("%", r"\%").replace("<", r"\textless{}")
    lines.append(rf"\expandafter\def\csname R@{k}\endcsname{{{v}}}")
lines.append(r"\makeatother")
(ROOT / "paper" / "numbers.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

gen = ROOT / "paper" / "generated"
gen.mkdir(exist_ok=True)
for f in (ROOT / "results" / "figures").glob("*.pdf"):
    shutil.copy(f, gen / f.name)
for f in (ROOT / "results" / "tables").glob("*.tex"):
    shutil.copy(f, gen / f.name)
print(f"{len(OUT)} numbers written to paper/numbers.tex")
