"""
Build every table, figure and number used in the paper from results/raw/.

    python -m experiments.analyze

Outputs
  results/summary.json            all numbers quoted in the paper / README
  results/tables/*.csv, *.tex     tables
  results/figures/*.pdf, *.png    figures
  results/cases/*.md              representative trajectories (failure analysis)
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.stats import correctness_at_k, mean_std, paired  # noqa: E402
from src.tracing.trajectory import read_trajectories  # noqa: E402

RAW = ROOT / "results" / "raw"
TAB = ROOT / "results" / "tables"
FIG = ROOT / "results" / "figures"
CASES = ROOT / "results" / "cases"

MODES = ["single_shot", "testing_only", "verifier_only", "specloop_full"]
MODE_LABEL = {"single_shot": "Single-shot", "testing_only": "Testing-only (E1)",
              "verifier_only": "Verifier-only", "specloop_full": "SpecLoop (E3)"}
ABLATIONS = ["no_normalizer", "no_router", "no_guard", "no_stagnation", "no_dev_fixes"]
LANGS = ["dafny", "python_icontract"]
LANG_LABEL = {"dafny": "Dafny", "python_icontract": "Python/iContract"}
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]      # validated categorical slots 1-4
HATCH = ["", "/", "\\", "x"]
INK, INK2 = "#0b0b0b", "#52514e"


def model_short(m: str) -> str:
    return re.sub(r"-\d{4}-\d{2}-\d{2}$", "", m)


def load_rows(exclude=("E2_base_paper", "dev")) -> list[dict]:
    rows = []
    for exp in sorted(RAW.glob("*")):
        if exp.name in exclude or not exp.is_dir():
            continue
        for f in exp.glob("*.jsonl"):
            for line in open(f, encoding="utf-8"):
                if line.strip():
                    r = json.loads(line)
                    r["model"] = model_short(r["model"])
                    rows.append(r)
    return rows


def fill_reused_ablation_units(rows: list[dict]) -> list[dict]:
    """E5 only runs units where the full system needed feedback (see experiments/run.py
    --reuse-first-attempt). For the other units every combined-mode ablation stops at the
    same cached first candidate with the same verdict, so the full system's row is reused."""
    full = [r for r in rows if r["config"] == "specloop_full" and r["attempts"] == 1
            and r["stop_reason"] == "mode_success"]
    abl_langs = {r["language"] for r in rows if r["config"] in ABLATIONS}
    have = {(r["config"], r["task_id"], r["seed"]) for r in rows if r["config"] in ABLATIONS}
    extra = []
    for cfg in ABLATIONS:
        if not any(r["config"] == cfg for r in rows):
            continue
        for r in full:
            if r["language"] in abl_langs and (cfg, r["task_id"], r["seed"]) not in have:
                extra.append({**r, "config": cfg, "experiment": "E5_ablation", "reused_from_E3": True})
    return rows + extra


def sel(rows, **kw):
    return [r for r in rows if all(r.get(k) == v for k, v in kw.items())]


def write_csv(name: str, rows: list[dict]):
    TAB.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))   # union of columns, first-seen order
    with open(TAB / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def pct(x):
    return None if x is None or x != x else round(100 * x, 1)


# ---------------------------------------------------------------------------
# main results (E1, E3, E4 arms)
# ---------------------------------------------------------------------------

def main_table(rows, models):
    out = []
    for m in models:
        for lang in LANGS:
            for c in MODES:
                rs = sel(rows, model=m, language=lang, config=c)
                if not rs:
                    continue
                cm, cs, n = mean_std(rs, "correct")
                vm, vs, _ = mean_std(rs, "verified")
                tm, ts, _ = mean_std(rs, "tests_ok")
                im, _, _ = mean_std(rs, "spec_intact")
                solved = sum(r["correct"] for r in rs)
                out.append({
                    "model": m, "language": lang, "config": c, "runs": len(rs), "seeds": n,
                    "correct_mean": pct(cm), "correct_sd": pct(cs),
                    "verified_mean": pct(vm), "verified_sd": pct(vs),
                    "tests_mean": pct(tm), "tests_sd": pct(ts),
                    "spec_intact": pct(im),
                    "attempts": round(float(np.mean([r["attempts"] for r in rs])), 2),
                    "llm_calls": round(float(np.mean([r["llm_calls"] for r in rs])), 2),
                    "tokens": round(float(np.mean([r["prompt_tokens"] + r["completion_tokens"] for r in rs]))),
                    "cost_per_run": round(float(np.mean([r["cost_usd"] for r in rs])), 5),
                    "cost_per_solved": round(sum(r["cost_usd"] for r in rs) / solved, 4) if solved else None,
                    "wall_s": round(float(np.mean([r["wall_seconds"] for r in rs])), 1),
                    "false_success": pct(np.mean([bool(r.get("false_success")) for r in rs])),
                })
    return out


def tex_main(table, models):
    lines = [r"\begin{tabular}{llrrrr}", r"\toprule",
             r"Model & Configuration & \multicolumn{2}{c}{Dafny} & \multicolumn{2}{c}{Python} \\",
             r" & & Correct & Verified & Correct & Verified \\", r"\midrule"]
    for m in models:
        for c in MODES:
            cells = []
            for lang in LANGS:
                r = next((x for x in table if x["model"] == m and x["language"] == lang and x["config"] == c), None)
                if r is None:
                    cells += ["--", "--"]
                else:
                    cells += [f"{r['correct_mean']:.1f}$\\pm${r['correct_sd']:.1f}", f"{r['verified_mean']:.1f}"]
            lines.append(f"{m} & {MODE_LABEL[c]} & " + " & ".join(cells) + r" \\")
        lines.append(r"\midrule")
    lines[-1] = r"\bottomrule"
    lines.append(r"\end{tabular}")
    (TAB / "main_results.tex").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# gap-wise analyses (E4)
# ---------------------------------------------------------------------------

def by_pair(rs):
    """Re-key rows by pair id so Dafny and Python runs of the same task match."""
    return [{**r, "task_id": r["pair_id"]} for r in rs]


def gap_analyses(rows, models):
    g = {"gap1": {}, "gap2": {}, "gap3": {}}
    for m in models:
        # Gap 1: same configuration, Dafny vs Python, paired by task
        for c in MODES:
            d = sel(rows, model=m, language="dafny", config=c)
            p = sel(rows, model=m, language="python_icontract", config=c)
            if d and p:
                g["gap1"][f"{m}/{c}/correct"] = paired(by_pair(d), by_pair(p), "correct")
                g["gap1"][f"{m}/{c}/verified"] = paired(by_pair(d), by_pair(p), "verified")
                g["gap1"][f"{m}/{c}/tests_ok"] = paired(by_pair(d), by_pair(p), "tests_ok")
        d = sel(rows, model=m, language="dafny", config="single_shot")
        p = sel(rows, model=m, language="python_icontract", config="single_shot")
        if d and p:
            g["gap1"][f"{m}/first_attempt_tests_ok"] = paired(by_pair(d), by_pair(p), "first_attempt_tests_ok")
        for lang in LANGS:
            full = sel(rows, model=m, language=lang, config="specloop_full")
            ver = sel(rows, model=m, language=lang, config="verifier_only")
            tst = sel(rows, model=m, language=lang, config="testing_only")
            if full and ver:
                g["gap2"][f"{m}/{lang}/full_vs_verifier"] = paired(full, ver)
            if full and tst:
                g["gap2"][f"{m}/{lang}/full_vs_testing"] = paired(full, tst)
            if ver and tst:
                g["gap3"][f"{m}/{lang}/verifier_vs_testing"] = paired(ver, tst)
            if full and tst:
                g["gap3"][f"{m}/{lang}/full_vs_testing"] = paired(full, tst)
    return g


def proof_gap_ambiguity(rows):
    """How often is a failed verification on code that already passes all tests?

    Uses verifier-only runs (the agent never saw tests) and the per-attempt
    oracle: these are exactly the verifier errors that are ambiguous to the
    agent but that tests would have explained as missing proof, not a bug.
    """
    out = {}
    for lang in LANGS:
        for m in sorted({r["model"] for r in rows}):
            rs = sel(rows, model=m, language=lang, config="verifier_only")
            fails = proof_only = 0
            for r in rs:
                for v, t in zip(r.get("per_attempt_verified", []), r.get("per_attempt_tests_ok", [])):
                    if not v:
                        fails += 1
                        proof_only += bool(t)
            if fails:
                out[f"{m}/{lang}"] = {"failed_verifications": fails, "with_all_tests_passing": proof_only,
                                      "share": round(proof_only / fails, 3)}
    return out


# ---------------------------------------------------------------------------
# E5 ablation, E6 efficiency
# ---------------------------------------------------------------------------

def ablation(rows, model):
    out = []
    for lang in LANGS:
        full = sel(rows, model=model, language=lang, config="specloop_full")
        if not full:
            continue
        fm, fs, _ = mean_std(full)
        out.append({"language": lang, "variant": "full system", "correct_mean": pct(fm), "correct_sd": pct(fs),
                    "delta": 0.0, "ci_lo": None, "ci_hi": None, "p_wilcoxon": None})
        variants = [(a, a) for a in ABLATIONS] + [("no_test_channel", "verifier_only"),
                                                    ("no_verifier_channel", "testing_only")]
        for name, cfg in variants:
            rs = sel(rows, model=model, language=lang, config=cfg)
            if not rs:
                continue
            m_, s_, _ = mean_std(rs)
            pr = paired(rs, full)
            out.append({"language": lang, "variant": name, "correct_mean": pct(m_), "correct_sd": pct(s_),
                        "delta": pct(pr["diff"]), "ci_lo": pct(pr["ci95"][0]), "ci_hi": pct(pr["ci95"][1]),
                        "p_wilcoxon": round(pr["p_wilcoxon"], 4),
                        "false_success": pct(np.mean([bool(r.get("false_success")) for r in rs])),
                        "spec_intact": pct(np.mean([r["spec_intact"] for r in rs])),
                        "cost_per_run": round(float(np.mean([r["cost_usd"] for r in rs])), 5)})
    return out


def reliability(rows):
    out = {}
    for c in MODES + ABLATIONS:
        rs = sel(rows, config=c)
        if not rs:
            continue
        out[c] = {
            "runs": len(rs),
            "runs_with_guard_block": sum(r["guard_blocks"] > 0 for r in rs),
            "false_success": sum(bool(r.get("false_success")) for r in rs),
            "final_spec_violations": sum(not r["spec_intact"] for r in rs),
            "strategy_switches": sum(r["strategy_switches"] for r in rs),
            "runs_with_switch": sum(r["strategy_switches"] > 0 for r in rs),
            "solved_after_switch": sum(r["strategy_switches"] > 0 and r["correct"] for r in rs),
            "tool_seconds_share": round(sum(r["tool_seconds"] for r in rs) /
                                        max(sum(r["tool_seconds"] + r["llm_seconds"] for r in rs), 1e-9), 3),
        }
    return out


# ---------------------------------------------------------------------------
# E2 base paper
# ---------------------------------------------------------------------------

def e2_table():
    cfg = json.loads((ROOT / "experiments" / "configs" / "E2_base_paper.json").read_text())
    rows = []
    for f in (RAW / "E2_base_paper").glob("*.jsonl") if (RAW / "E2_base_paper").exists() else []:
        rows += [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
    out = []
    for m in sorted({model_short(r["model"]) for r in rows}):
        for lang in LANGS:
            rs = [r for r in rows if model_short(r["model"]) == m and r["language"] == lang]
            if not rs:
                continue
            # pass@1 = mean over tasks of (passing samples / samples)
            by = defaultdict(list)
            for r in rs:
                by[r["task_id"]].append(r)
            def p1(key):
                return float(np.mean([np.mean([bool(x[key]) for x in v]) for v in by.values()]))
            rep = cfg["reported"].get(m, {})
            out.append({"model": m, "language": lang, "tasks": len(by), "samples": len(rs),
                        "pass_at_1_tests": pct(p1("tests_ok")), "cannot_compile": pct(1 - p1("compiles")),
                        "verified_at_1": pct(p1("verified")), "correct_at_1": pct(p1("correct")),
                        "verina_lean_pass_reported": rep.get("pass"),
                        "verina_lean_cannot_compile_reported": rep.get("cannot_compile")})
    return out


# ---------------------------------------------------------------------------
# failure analysis
# ---------------------------------------------------------------------------

def categorize(run: dict) -> str:
    """Assign a failure category from the last attempt in a trajectory."""
    ev = run["events"]
    oracle = [e for e in ev if e["type"] == "oracle"][-1]
    code = [e for e in ev if e["type"] == "llm"][-1].get("code", "")
    verifies = [e for e in ev if e["type"] == "tool" and e["tool"] == "verify"]
    kinds = set(verifies[-1]["kinds"]) if verifies else set()
    if not oracle["spec_intact"]:
        return "spec tampering / forbidden construct"
    if not oracle.get("compiles", True) or kinds & {"syntax", "resolution"}:
        return "does not compile"
    if oracle["verify_status"] == "timeout" or "timeout" in kinds:
        return "verifier timeout"
    if not oracle["tests_ok"]:
        return "wrong behaviour (fails tests)"
    if run["language"] == "python_icontract":
        return "counterexample on untested input"
    if "termination" in kinds:
        return "termination not proved"
    has_loop = "while" in code
    has_inv = re.search(r"^\s*invariant\b", code, re.M) is not None
    if has_loop and not has_inv:
        if re.search(r"//.*invariant", code, re.I):
            return "proof gap: invariants only in comments"
        return "proof gap: no loop invariants"
    return "proof gap: invariants too weak"


def failure_analysis(models):
    path_dir = ROOT / "logs" / "trajectories" / "E3_proposed"
    cats, examples = defaultdict(Counter), defaultdict(list)
    successes = []
    if not path_dir.exists():
        return {}, []
    for f in sorted(path_dir.glob("*.jsonl.gz")):
        for run in read_trajectories(f):
            final = [e for e in run["events"] if e["type"] == "oracle"][-1]
            key = f"{model_short(run['model'])}/{run['language']}"
            if final["correct"]:
                classes = [e["failure_class"] for e in run["events"] if e["type"] == "feedback"]
                if len(classes) >= 1:
                    successes.append((run, classes))
                continue
            c = categorize(run)
            cats[key][c] += 1
            examples[c].append(run)
    table = []
    for key, cnt in sorted(cats.items()):
        tot = sum(cnt.values())
        for c, n in cnt.most_common():
            table.append({"model_language": key, "category": c, "count": n, "share": round(100 * n / tot, 1)})
    # representative cases: two repaired successes (one per language), two failures
    CASES.mkdir(parents=True, exist_ok=True)
    picks = []
    for lang in LANGS:
        s = [x for x in successes if x[0]["language"] == lang and "PROOF_GAP" in x[1]] or \
            [x for x in successes if x[0]["language"] == lang]
        if s:
            picks.append(("success", s[0][0]))
    for c in ["proof gap: invariants too weak", "wrong behaviour (fails tests)",
              "proof gap: invariants only in comments", "spec tampering / forbidden construct"]:
        if examples.get(c):
            picks.append(("failure", examples[c][0]))
        if sum(1 for p in picks if p[0] == "failure") >= 2:
            break
    for i, (kind, run) in enumerate(picks, 1):
        (CASES / f"case{i}_{kind}.md").write_text(render_case(run), encoding="utf-8")
    return {"table": table}, picks


def render_case(run: dict) -> str:
    lines = [f"# {run['run_id']}", "", f"task {run['task_id']} | {run['language']} | {run['model']} | seed {run['seed']}", ""]
    for e in run["events"]:
        if e["type"] == "state":
            lines.append(f"- [{e['t']:.1f}s] state {e['frm']} -> {e['to']}")
        elif e["type"] == "llm":
            lines.append(f"- [{e['t']:.1f}s] LLM {e['purpose']} (attempt {e['attempt']}, "
                         f"{e['prompt_tokens']}+{e['completion_tokens']} tok): {e.get('analysis', '')[:220]}")
        elif e["type"] == "tool":
            detail = {k: e[k] for k in ("status", "ok", "kinds", "passed", "total", "violations") if k in e}
            lines.append(f"- [{e['t']:.1f}s] tool {e['tool']} -> {detail}")
        elif e["type"] == "feedback":
            lines.append(f"- [{e['t']:.1f}s] router: {e['failure_class']}")
        elif e["type"] == "decision":
            lines.append(f"- [{e['t']:.1f}s] decision: {e['what']} ({e['reason']})")
        elif e["type"] == "oracle":
            lines.append(f"- oracle(attempt {e['attempt']}): intact={e['spec_intact']} verified={e['verified']} "
                         f"tests={e['tests_passed']}/{e['tests_total']} correct={e['correct']}")
    codes = [e for e in run["events"] if e["type"] == "llm"]
    lines += ["", "## final program", "```", codes[-1]["code"], "```"]
    fbs = [e for e in run["events"] if e["type"] == "feedback"]
    if fbs:
        lines += ["", "## first feedback message", "```", fbs[0]["text"], "```"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------

def _style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(INK2)
    ax.spines["bottom"].set_color(INK2)
    ax.tick_params(colors=INK2, labelsize=7)
    ax.yaxis.grid(True, color="#e6e5e1", linewidth=0.6)
    ax.set_axisbelow(True)


def fig_modes(table, models):
    FIG.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, len(models), figsize=(3.5 * len(models), 2.6), sharey=True)
    axes = np.atleast_1d(axes)
    w = 0.19
    for ax, m in zip(axes, models):
        _style(ax)
        for i, c in enumerate(MODES):
            ys, es = [], []
            for lang in LANGS:
                r = next((x for x in table if x["model"] == m and x["language"] == lang and x["config"] == c), None)
                ys.append(r["correct_mean"] if r else 0)
                es.append(r["correct_sd"] if r else 0)
            xs = np.arange(len(LANGS)) + (i - 1.5) * (w + 0.02)
            bars = ax.bar(xs, ys, w, yerr=es, color=COLORS[i], hatch=HATCH[i], edgecolor="white",
                          linewidth=0.5, error_kw=dict(lw=0.7, capsize=1.5, ecolor=INK2), label=MODE_LABEL[c])
            for b, y, e in zip(bars, ys, es):
                ax.text(b.get_x() + b.get_width() / 2, y + (e or 0) + 1.5, f"{y:.0f}", ha="center",
                        va="bottom", fontsize=5.5, color=INK)
        ax.set_xticks(range(len(LANGS)), [LANG_LABEL[l] for l in LANGS], fontsize=7, color=INK)
        ax.set_title(m, fontsize=8, color=INK)
        ax.set_ylim(0, 105)
    axes[0].set_ylabel("Correct (%)", fontsize=7, color=INK)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=6, frameon=False, loc="lower center", ncol=4,
               bbox_to_anchor=(0.5, 0.0), handlelength=1.6, columnspacing=1.0)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(FIG / "fig_modes.pdf")
    fig.savefig(FIG / "fig_modes.png", dpi=200)
    plt.close(fig)


def fig_curves(rows, models):
    fig, axes = plt.subplots(len(models), 2, figsize=(6.8, 2.4 * len(models)), sharey=True, squeeze=False)
    for row_i, m in enumerate(models):
        for col_i, lang in enumerate(LANGS):
            ax = axes[row_i][col_i]
            _style(ax)
            ends = []
            for i, c in enumerate(MODES[1:], start=1):
                rs = sel(rows, model=m, language=lang, config=c)
                if not rs:
                    continue
                ys = [100 * correctness_at_k(rs, k) for k in range(1, 6)]
                ax.plot(range(1, 6), ys, color=COLORS[i], lw=2, marker="o", ms=3.5, label=MODE_LABEL[c])
                ends.append(ys[-1])
            # label line ends only when they are far enough apart to stay readable
            if ends and min(abs(a - b) for a in ends for b in ends if a is not b) >= 3 if len(ends) > 1 else True:
                for e in ends:
                    ax.annotate(f"{e:.0f}", (5, e), xytext=(4, 0), textcoords="offset points",
                                fontsize=6, color=INK, va="center")
            ax.set_title(f"{m}, {LANG_LABEL[lang]}", fontsize=7.5, color=INK)
            ax.set_xticks(range(1, 6))
            ax.set_xlim(0.8, 5.6)
            if col_i == 0:
                ax.set_ylabel("Correct by attempt k (%)", fontsize=7, color=INK)
            if row_i == len(models) - 1:
                ax.set_xlabel("attempt budget k", fontsize=7, color=INK)
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=6.5, frameon=False, loc="lower center", ncol=3,
               bbox_to_anchor=(0.5, 0.0))
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(FIG / "fig_curves.pdf")
    fig.savefig(FIG / "fig_curves.png", dpi=200)
    plt.close(fig)


def fig_failures(fa_table):
    if not fa_table:
        return
    keys = sorted({r["model_language"] for r in fa_table})
    cats = sorted({r["category"] for r in fa_table},
                  key=lambda c: -sum(r["count"] for r in fa_table if r["category"] == c))
    fig, ax = plt.subplots(figsize=(6.8, 0.32 * len(cats) + 1.0))
    _style(ax)
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color="#e6e5e1", linewidth=0.6)
    h = 0.8 / max(len(keys), 1)
    for i, k in enumerate(keys):
        vals = [next((r["count"] for r in fa_table if r["model_language"] == k and r["category"] == c), 0)
                for c in cats]
        ys = np.arange(len(cats)) + (i - (len(keys) - 1) / 2) * h
        ax.barh(ys, vals, h * 0.9, color=COLORS[i % 4], hatch=HATCH[i % 4], edgecolor="white", linewidth=0.5,
                label=k.replace("python_icontract", "Python").replace("dafny", "Dafny"))
        for y, v in zip(ys, vals):
            if v:
                ax.text(v + 0.3, y, str(v), va="center", fontsize=5.5, color=INK)
    ax.set_yticks(range(len(cats)), cats, fontsize=6.5, color=INK)
    ax.invert_yaxis()
    ax.set_xlabel("failed runs (SpecLoop, 3 seeds)", fontsize=7, color=INK)
    ax.legend(fontsize=6, frameon=False, loc="lower right")
    fig.tight_layout()
    fig.savefig(FIG / "fig_failures.pdf")
    fig.savefig(FIG / "fig_failures.png", dpi=200)
    plt.close(fig)


# ---------------------------------------------------------------------------

def main():
    rows = fill_reused_ablation_units(load_rows())
    summary_reused = sum(1 for r in rows if r.get("reused_from_E3"))
    models = [m for m in ["gpt-4.1", "gpt-4o-mini"] if any(r["model"] == m for r in rows)]
    models += sorted({r["model"] for r in rows} - set(models))
    summary: dict = {"n_runs": len(rows) - summary_reused, "n_reused_ablation_units": summary_reused,
                     "models": models}
    table = main_table(rows, models)
    write_csv("main_results", table)
    if table:
        tex_main(table, models)
        fig_modes(table, models)
        fig_curves(rows, models)
    summary["main"] = table
    summary["curves"] = {f"{lang}/{c}": [round(100 * correctness_at_k(sel(rows, language=lang, config=c), k), 1)
                                          for k in range(1, 6)]
                         for lang in LANGS for c in MODES[1:] if sel(rows, language=lang, config=c)}
    summary["solved_by_repair"] = {f"{lang}/{c}": sum(1 for r in sel(rows, language=lang, config=c)
                                                     if r["correct"] and (r.get("solved_at_attempt") or 1) > 1)
                                   for lang in LANGS for c in MODES[1:]}
    summary["gaps"] = gap_analyses(rows, models)
    summary["proof_gap_ambiguity"] = proof_gap_ambiguity(rows)
    abl = ablation(rows, models[0]) if models else []
    write_csv("ablation", abl)
    summary["ablation"] = abl
    summary["reliability"] = reliability(rows)
    e2 = e2_table()
    write_csv("e2_base_paper", e2)
    summary["e2"] = e2
    fa, picks = failure_analysis(models)
    if fa:
        write_csv("failure_categories", fa["table"])
        fig_failures(fa["table"])
        summary["failures"] = fa["table"]
        summary["cases"] = [{"kind": k, "run_id": r["run_id"]} for k, r in picks]
    gs = ROOT / "results" / "guard_stress_summary.json"
    if gs.exists():
        summary["guard_stress"] = json.loads(gs.read_text())
    eq = ROOT / "data" / "equivalence_report.json"
    if eq.exists():
        e = json.loads(eq.read_text())
        summary["equivalence"] = {"total_inputs": e["total_inputs"], "total_agree": e["total_agree"],
                                  "tasks": len(e["tasks"])}
    summary["total_cost_usd"] = round(sum(r["cost_usd"] for r in rows) +
                                      sum(r.get("cost_usd", 0) for r in []), 2)
    (ROOT / "results" / "summary.json").write_text(json.dumps(summary, indent=1, default=float), encoding="utf-8")
    print(f"{len(rows)} runs analysed; tables in {TAB.relative_to(ROOT)}, figures in {FIG.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
