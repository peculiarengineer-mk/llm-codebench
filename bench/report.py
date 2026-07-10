"""Reporting: RunResult -> human/file output (T7).

Pure presentation. Builds only against :class:`~bench.types.RunResult`, so it is
fully decoupled from how results were computed. Three surfaces:

  * :func:`render_cli`  — a rich leaderboard printed to the terminal.
  * :func:`render_html` — a self-contained HTML report (Jinja2, inline CSS).
  * :func:`export_raw`  — ``results.json`` + ``results.csv`` for downstream use.

Beyond the headline leaderboard the report surfaces, from data already captured
per attempt, several things a blog audience cares about: a **methodology
header** (so a run is reproducible), a **pass@k-by-difficulty** breakdown (where
models actually separate), a **failure-mode** split (wrong answer vs timeout vs
no-code-emitted), sample-size honesty (``solved/total`` + a 95% Wilson interval),
a **cost/quality scatter**, and a **per-problem drill-down** with a representative
failing stderr.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from html import escape
from pathlib import Path

from jinja2 import Template
from markupsafe import Markup

from bench.types import Attempt, ExecResult, ProblemResult, RunResult

# --------------------------------------------------------------------------- #
# Failure classification + statistics
# --------------------------------------------------------------------------- #

# Human labels for the four mutually-exclusive per-attempt outcomes.
FAILURE_LABELS = {
    "pass": "pass",
    "failed": "wrong answer",
    "timeout": "timeout",
    "no_code": "no code",
}
FAILURE_ORDER = ["pass", "failed", "timeout", "no_code"]

_Z95 = 1.959963984540054  # z for a 95% two-sided normal interval


def _classify(attempt: Attempt, ex: ExecResult) -> str:
    """Bucket one attempt into pass / failed / timeout / no_code.

    ``failed`` means the code ran but the hidden tests did not pass (wrong
    answer or a runtime error) — the two are not reliably distinguishable across
    languages from an exit code alone, so they share a bucket. ``no_code`` is the
    extractor finding no usable code block in the model's reply.
    """
    if ex.passed:
        return "pass"
    if attempt.code is None:
        return "no_code"
    if ex.timed_out:
        return "timeout"
    return "failed"


def _wilson(c: int, n: int, z: float = _Z95) -> tuple[float, float]:
    """95% Wilson score interval for ``c`` successes in ``n`` trials.

    Preferred over the normal approximation at small ``n`` (few problems) — it
    never runs off the [0, 1] ends and degrades gracefully. Returns (0, 0) for
    an empty sample.
    """
    if n <= 0:
        return (0.0, 0.0)
    p = c / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


def _model_rows(run: RunResult) -> list[dict]:
    """Aggregate per-model leaderboard rows (correctness / speed / cost)."""
    by_model: dict[str, list[ProblemResult]] = defaultdict(list)
    for pr in run.results:
        by_model[pr.model].append(pr)

    rows: list[dict] = []
    for model, results in by_model.items():
        n = len(results) or 1
        pass1 = sum(r.pass_at_1 for r in results) / n
        passk = sum(r.pass_at_k for r in results) / n

        latencies = [a.latency_ms for r in results for a in r.attempts]
        ttfts = [a.ttft_ms for r in results for a in r.attempts if a.ttft_ms is not None]
        completion_tokens = sum(a.completion_tokens for r in results for a in r.attempts)
        prompt_tokens = sum(a.prompt_tokens for r in results for a in r.attempts)
        total_latency_s = sum(latencies) / 1000.0 if latencies else 0.0
        tokens_per_sec = (completion_tokens / total_latency_s) if total_latency_s else 0.0
        cost = sum(a.cost_usd for r in results for a in r.attempts)
        retries = sum(a.retries for r in results for a in r.attempts)

        # $/correct-solution: total cost divided by number of problems solved
        # (pass@k counts a problem as solved if any of its k attempts passed).
        solved = sum(1 for r in results if r.pass_at_k > 0)
        total = len(results)
        cost_per_correct = (cost / solved) if solved else float("inf")
        ci_low, ci_high = _wilson(solved, total)

        # Per-attempt failure-mode tally + whether pricing came from a config
        # override (so the row can be asterisked as not-live-priced).
        fails = dict.fromkeys(FAILURE_ORDER, 0)
        config_priced = False
        for r in results:
            for a, ex in zip(r.attempts, r.exec_results):
                fails[_classify(a, ex)] += 1
                if a.price_source == "config":
                    config_priced = True
        attempts_total = sum(fails.values()) or 1

        rows.append(
            {
                "model": model,
                "problems": total,
                "pass_at_1": pass1,
                "pass_at_k": passk,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "solved": solved,
                "avg_latency_ms": (sum(latencies) / len(latencies)) if latencies else 0.0,
                "avg_ttft_ms": (sum(ttfts) / len(ttfts)) if ttfts else None,
                "tokens_per_sec": tokens_per_sec,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": cost,
                "cost_per_correct": cost_per_correct,
                "retries": retries,
                "fails": fails,
                "attempts_total": attempts_total,
                "config_priced": config_priced,
            }
        )
    # Rank by pass@k desc, then cost asc.
    rows.sort(key=lambda r: (-r["pass_at_k"], r["cost_usd"]))
    return rows


def _language_rows(run: RunResult) -> list[dict]:
    """Per (model, language) pass@k breakdown."""
    agg: dict[tuple[str, str], list[float]] = defaultdict(list)
    for pr in run.results:
        agg[(pr.model, pr.language.value)].append(pr.pass_at_k)
    rows = [
        {
            "model": model,
            "language": lang,
            "pass_at_k": sum(vals) / len(vals),
            "problems": len(vals),
        }
        for (model, lang), vals in agg.items()
    ]
    rows.sort(key=lambda r: (r["model"], r["language"]))
    return rows


_DIFF_ORDER = {"easy": 0, "medium": 1, "hard": 2}


def _difficulty_rows(run: RunResult) -> tuple[list[str], list[dict]]:
    """Per-model pass@k split by problem difficulty.

    Returns ``(difficulties_present, rows)`` where each row is
    ``{"model", "<difficulty>": {"pass_at_k", "solved", "problems"} , ...}``.
    Difficulty may be ``None`` on results produced before it was tracked; those
    are grouped under ``"?"`` only if present, otherwise skipped.
    """
    agg: dict[tuple[str, str], list[float]] = defaultdict(list)
    present: set[str] = set()
    for pr in run.results:
        diff = pr.difficulty or "?"
        present.add(diff)
        agg[(pr.model, diff)].append(pr.pass_at_k)

    difficulties = sorted(present, key=lambda d: _DIFF_ORDER.get(d, 99))
    models = sorted({pr.model for pr in run.results})
    rows: list[dict] = []
    for model in models:
        row: dict = {"model": model}
        for diff in difficulties:
            vals = agg.get((model, diff))
            if vals:
                row[diff] = {
                    "pass_at_k": sum(vals) / len(vals),
                    "solved": sum(1 for v in vals if v > 0),
                    "problems": len(vals),
                }
            else:
                row[diff] = None
        rows.append(row)
    return difficulties, rows


def _problem_rows(run: RunResult) -> list[dict]:
    """Per-problem drill-down: which models solved it + a sample failing stderr."""
    by_problem: dict[str, list[ProblemResult]] = defaultdict(list)
    for pr in run.results:
        by_problem[pr.problem_slug].append(pr)

    rows: list[dict] = []
    for slug, results in by_problem.items():
        first = results[0]
        models = []
        sample_stderr = ""
        for pr in sorted(results, key=lambda r: r.model):
            passed = pr.pass_at_k > 0
            models.append({"model": pr.model, "passed": passed})
            if not passed and not sample_stderr:
                for ex in pr.exec_results:
                    if not ex.passed and ex.stderr.strip():
                        sample_stderr = ex.stderr.strip()[-600:]
                        break
        rows.append(
            {
                "slug": slug,
                "language": first.language.value,
                "difficulty": first.difficulty or "?",
                "solved_by": sum(1 for m in models if m["passed"]),
                "total_models": len(models),
                "models": models,
                "sample_stderr": sample_stderr,
            }
        )
    rows.sort(key=lambda r: (_DIFF_ORDER.get(r["difficulty"], 99), r["language"], r["slug"]))
    return rows


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #


def _fmt_cost_per_correct(value: float) -> str:
    return "n/a" if value == float("inf") else f"${value:.4f}"


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _headline(rows: list[dict]) -> str:
    """A one-sentence auto TL;DR for the top of the report."""
    if not rows:
        return "No results."
    best = rows[0]
    priced = [r for r in rows if r["cost_per_correct"] != float("inf")]
    parts = [
        f"{best['model']} leads at {_fmt_pct(best['pass_at_k'])} pass@k "
        f"({best['solved']}/{best['problems']} solved)"
    ]
    if priced:
        cheapest = min(priced, key=lambda r: r["cost_per_correct"])
        if cheapest["model"] != best["model"]:
            parts.append(
                f"{cheapest['model']} is cheapest per correct solution at "
                f"{_fmt_cost_per_correct(cheapest['cost_per_correct'])}"
            )
    return "; ".join(parts) + "."


def _scatter_svg(rows: list[dict], width: int = 720, height: int = 340) -> str:
    """Inline SVG scatter of cost-per-correct (x) vs pass@k (y).

    Self-contained (no external refs) so it survives being pasted into a blog.
    Only models with a finite $/correct (i.e. that solved something) are plotted.
    """
    pts = [r for r in rows if r["cost_per_correct"] != float("inf")]
    if not pts:
        return ""

    ml, mr, mt, mb = 64, 16, 16, 44  # margins
    pw, ph = width - ml - mr, height - mt - mb
    x_max = max(r["cost_per_correct"] for r in pts) or 1.0
    x_max *= 1.15  # headroom

    def px(cost: float) -> float:
        return ml + (cost / x_max) * pw

    def py(frac: float) -> float:
        return mt + (1 - frac) * ph

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" '
        f'role="img" aria-label="Cost per correct solution versus pass@k" '
        f'style="max-width:{width}px;font:12px system-ui,sans-serif">'
    ]
    # y gridlines / labels at 0,25,50,75,100%
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = py(frac)
        parts.append(
            f'<line x1="{ml}" y1="{y:.1f}" x2="{width - mr}" y2="{y:.1f}" '
            f'stroke="#8883" />'
        )
        parts.append(
            f'<text x="{ml - 8}" y="{y + 4:.1f}" text-anchor="end" '
            f'fill="#8a8a8a">{frac * 100:.0f}%</text>'
        )
    # x axis ticks
    for i in range(5):
        cost = x_max * i / 4
        x = px(cost)
        parts.append(
            f'<text x="{x:.1f}" y="{height - mb + 20}" text-anchor="middle" '
            f'fill="#8a8a8a">${cost:.3f}</text>'
        )
    # axis titles
    parts.append(
        f'<text x="{ml + pw / 2:.1f}" y="{height - 4}" text-anchor="middle" '
        f'fill="#8a8a8a">cost per correct solution (USD, lower is better)</text>'
    )
    # points
    for r in pts:
        x, y = px(r["cost_per_correct"]), py(r["pass_at_k"])
        label = escape(r["model"].split("/")[-1])
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#2a8" '
            f'fill-opacity="0.85" stroke="#0b0b0b22" />'
        )
        parts.append(
            f'<text x="{x + 8:.1f}" y="{y + 4:.1f}" fill="currentColor">{label}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# CLI surface
# --------------------------------------------------------------------------- #


def _methodology_line(run: RunResult) -> str:
    bits = [f"k={run.k}"]
    if run.temperature is not None:
        bits.append(f"temp={run.temperature:g}")
    if run.timeout is not None:
        bits.append(f"timeout={run.timeout:g}s")
    if run.prompt_style:
        bits.append(f"prompt={run.prompt_style}")
    if run.generated_at:
        bits.append(run.generated_at)
    return "  ".join(bits)


def render_cli(run: RunResult, console=None) -> None:
    """Print a rich leaderboard + breakdowns to the terminal."""
    from rich.console import Console
    from rich.table import Table

    console = console or Console()
    rows = _model_rows(run)

    console.print(f"[dim]{_methodology_line(run)}[/dim]")
    console.print(f"[bold]TL;DR[/bold] {_headline(rows)}\n")

    title = (
        f"llm-codebench — {run.problems_count} problems × {len(run.models)} models "
        f"(k={run.k})"
    )
    table = Table(title=title, title_style="bold")
    table.add_column("Model", style="cyan", no_wrap=True)
    table.add_column("pass@1", justify="right")
    table.add_column(f"pass@{run.k}", justify="right", style="bold")
    table.add_column("solved", justify="right")
    table.add_column("95% CI", justify="right")
    table.add_column("tok/s", justify="right")
    table.add_column("avg TTFT", justify="right")
    table.add_column("cost", justify="right")
    table.add_column("$/correct", justify="right")
    table.add_column("retries", justify="right")

    for row in rows:
        ttft = f"{row['avg_ttft_ms']:.0f}ms" if row["avg_ttft_ms"] is not None else "—"
        star = "*" if row["config_priced"] else ""
        table.add_row(
            row["model"],
            _fmt_pct(row["pass_at_1"]),
            _fmt_pct(row["pass_at_k"]),
            f"{row['solved']}/{row['problems']}",
            f"{_fmt_pct(row['ci_low'])}–{_fmt_pct(row['ci_high'])}",
            f"{row['tokens_per_sec']:.0f}",
            ttft,
            f"${row['cost_usd']:.4f}{star}",
            _fmt_cost_per_correct(row["cost_per_correct"]),
            str(row["retries"]),
        )
    console.print(table)
    if any(r["config_priced"] for r in rows):
        console.print("[dim]* cost priced from a config override, not live API "
                      "pricing.[/dim]")

    # -- failure modes --------------------------------------------------------
    ft = Table(title="Failure modes (share of attempts)", title_style="bold")
    ft.add_column("Model", style="cyan")
    for key in FAILURE_ORDER:
        ft.add_column(FAILURE_LABELS[key], justify="right")
    for row in rows:
        tot = row["attempts_total"]
        ft.add_row(
            row["model"],
            *[f"{row['fails'][k]} ({row['fails'][k] / tot * 100:.0f}%)"
              for k in FAILURE_ORDER],
        )
    console.print(ft)

    # -- difficulty breakdown -------------------------------------------------
    difficulties, drows = _difficulty_rows(run)
    if difficulties:
        dt = Table(title="pass@k by difficulty", title_style="bold")
        dt.add_column("Model", style="cyan")
        for diff in difficulties:
            dt.add_column(diff, justify="right")
        for row in drows:
            cells = []
            for diff in difficulties:
                cell = row[diff]
                cells.append(
                    f"{_fmt_pct(cell['pass_at_k'])} ({cell['solved']}/{cell['problems']})"
                    if cell else "—"
                )
            dt.add_row(row["model"], *cells)
        console.print(dt)

    # -- per-language ---------------------------------------------------------
    lang_rows = _language_rows(run)
    if lang_rows:
        lt = Table(title="Per-language pass@k", title_style="bold")
        lt.add_column("Model", style="cyan")
        lt.add_column("Language")
        lt.add_column("pass@k", justify="right")
        lt.add_column("problems", justify="right")
        for row in lang_rows:
            lt.add_row(
                row["model"],
                row["language"],
                _fmt_pct(row["pass_at_k"]),
                str(row["problems"]),
            )
        console.print(lt)

    console.print(
        f"\nTotal cost: [bold]${run.total_cost_usd:.4f}[/bold]   "
        f"Total wall time: {run.total_latency_ms / 1000:.1f}s   "
        f"Total retries: [bold]{run.total_retries}[/bold]"
    )


# --------------------------------------------------------------------------- #
# HTML surface
# --------------------------------------------------------------------------- #

_HTML_TEMPLATE = Template(
    """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>llm-codebench report</title>
<style>
  :root { color-scheme: light dark; --line:#8884; --muted:#8a8a8a;
          --good:#2a8; --bad:#d9534f; --warn:#e0a800; }
  body { font: 15px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 980px;
         padding: 0 1rem; }
  h1 { font-size: 1.5rem; margin-bottom:.25rem; }
  h2 { font-size: 1.15rem; margin-top: 2.25rem; }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  th, td { padding: .5rem .75rem; text-align: right; border-bottom: 1px solid var(--line); }
  th:first-child, td:first-child { text-align: left; }
  thead th { border-bottom: 2px solid #8888; cursor: pointer; user-select: none; }
  thead th::after { content: " \\2195"; color: var(--muted); font-size:.8em; }
  tbody tr:hover { background: #8881; }
  .bar { position: relative; white-space: nowrap; }
  .bar > span { display: inline-block; height: .55rem; border-radius: 3px;
                background: linear-gradient(90deg,#4c9,#2a8); vertical-align: middle;
                margin-right:.4rem; }
  .ci { color: var(--muted); font-size: .82em; }
  .meta { color: var(--muted); font-size: .9rem; }
  .tldr { background:#2a81; border-left:3px solid var(--good); padding:.6rem .9rem;
          border-radius:4px; margin:1rem 0; }
  .scatter { overflow-x:auto; }
  details { border:1px solid var(--line); border-radius:6px; padding:.4rem .8rem;
            margin:.5rem 0; }
  details > summary { cursor:pointer; font-weight:600; }
  .pill { display:inline-block; padding:.05rem .5rem; border-radius:999px;
          font-size:.8em; margin:.1rem; }
  .pass { background:#2a83; } .fail { background:#d9534f33; }
  .diff { font-size:.8em; color:var(--muted); text-transform:uppercase; letter-spacing:.03em; }
  pre { background:#8881; padding:.6rem .8rem; border-radius:4px; overflow-x:auto;
        font-size:.82rem; white-space:pre-wrap; word-break:break-word; }
  code { background: #8881; padding: .1rem .3rem; border-radius: 3px; }
  footer { color:var(--muted); font-size:.82rem; margin-top:2.5rem; }
</style>
</head>
<body>
  <h1>llm-codebench report</h1>
  <p class="meta">{{ run.problems_count }} problems &times; {{ run.models|length }}
     models &middot; {{ methodology }}</p>
  <div class="tldr"><strong>TL;DR</strong> — {{ headline }}</div>
  <p class="meta">total cost
     <strong>${{ '%.4f'|format(run.total_cost_usd) }}</strong> &middot;
     wall time {{ '%.1f'|format(run.total_latency_ms / 1000) }}s &middot;
     total retries <strong>{{ run.total_retries }}</strong></p>

  <h2>Leaderboard</h2>
  <table id="leaderboard">
    <thead><tr>
      <th>Model</th><th>pass@1</th><th>pass@{{ run.k }}</th><th>solved</th>
      <th>tok/s</th><th>avg TTFT</th><th>cost</th><th>$/correct</th><th>retries</th>
    </tr></thead>
    <tbody>
    {% for r in rows %}
      <tr>
        <td>{{ r.model }}</td>
        <td class="bar" data-sort="{{ r.pass_at_1 }}">
          <span style="width: {{ (r.pass_at_1 * 70)|round(1) }}px"></span>
          {{ '%.0f'|format(r.pass_at_1 * 100) }}%
        </td>
        <td class="bar" data-sort="{{ r.pass_at_k }}">
          <span style="width: {{ (r.pass_at_k * 70)|round(1) }}px"></span>
          <strong>{{ '%.0f'|format(r.pass_at_k * 100) }}%</strong>
          <span class="ci">({{ '%.0f'|format(r.ci_low * 100) }}&ndash;{{ '%.0f'|format(r.ci_high * 100) }})</span>
        </td>
        <td data-sort="{{ r.solved }}">{{ r.solved }}/{{ r.problems }}</td>
        <td data-sort="{{ r.tokens_per_sec }}">{{ '%.0f'|format(r.tokens_per_sec) }}</td>
        <td data-sort="{{ r.avg_ttft_ms or -1 }}">{% if r.avg_ttft_ms is not none %}{{ '%.0f'|format(r.avg_ttft_ms) }}ms{% else %}&mdash;{% endif %}</td>
        <td data-sort="{{ r.cost_usd }}">${{ '%.4f'|format(r.cost_usd) }}{% if r.config_priced %}*{% endif %}</td>
        <td data-sort="{{ r.cost_per_correct if r.cost_per_correct != inf else 1e12 }}">{{ cost_per_correct(r.cost_per_correct) }}</td>
        <td data-sort="{{ r.retries }}">{{ r.retries }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% if any_config_priced %}<p class="meta">* cost priced from a config override,
     not live API pricing.</p>{% endif %}

  {% if scatter %}
  <h2>Cost vs. quality</h2>
  <div class="scatter">{{ scatter }}</div>
  {% endif %}

  <h2>Failure modes</h2>
  <table>
    <thead><tr><th>Model</th>{% for k in failure_order %}<th>{{ failure_labels[k] }}</th>{% endfor %}</tr></thead>
    <tbody>
    {% for r in rows %}
      <tr><td>{{ r.model }}</td>
        {% for k in failure_order %}<td>{{ r.fails[k] }}
          <span class="ci">({{ '%.0f'|format(r.fails[k] / r.attempts_total * 100) }}%)</span></td>{% endfor %}
      </tr>
    {% endfor %}
    </tbody>
  </table>

  {% if difficulties %}
  <h2>pass@k by difficulty</h2>
  <table>
    <thead><tr><th>Model</th>{% for d in difficulties %}<th>{{ d }}</th>{% endfor %}</tr></thead>
    <tbody>
    {% for r in diff_rows %}
      <tr><td>{{ r.model }}</td>
        {% for d in difficulties %}<td>
          {% if r[d] %}{{ '%.0f'|format(r[d].pass_at_k * 100) }}%
            <span class="ci">({{ r[d].solved }}/{{ r[d].problems }})</span>
          {% else %}&mdash;{% endif %}</td>{% endfor %}
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% endif %}

  <h2>Per-language pass@k</h2>
  <table>
    <thead><tr><th>Model</th><th>Language</th><th>pass@k</th><th>problems</th></tr></thead>
    <tbody>
    {% for r in lang_rows %}
      <tr>
        <td>{{ r.model }}</td><td style="text-align:left">{{ r.language }}</td>
        <td>{{ '%.0f'|format(r.pass_at_k * 100) }}%</td>
        <td>{{ r.problems }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>

  <h2>Per-problem detail</h2>
  {% for p in problem_rows %}
  <details>
    <summary>{{ p.slug }}
      <span class="diff">{{ p.language }} &middot; {{ p.difficulty }}</span>
      &mdash; solved by {{ p.solved_by }}/{{ p.total_models }}</summary>
    <p>{% for m in p.models %}<span class="pill {{ 'pass' if m.passed else 'fail' }}">
        {{ m.model }} {{ '\\u2713' if m.passed else '\\u2717' }}</span>{% endfor %}</p>
    {% if p.sample_stderr %}<pre>{{ p.sample_stderr }}</pre>{% endif %}
  </details>
  {% endfor %}

  <footer>Generated by llm-codebench{% if run.generated_at %} at {{ run.generated_at }}{% endif %}.
     pass@k uses the unbiased Chen et&nbsp;al. (2021) estimator; intervals are 95% Wilson
     score on solved/total.</footer>

<script>
// Lightweight click-to-sort for every data table. No external deps.
document.querySelectorAll('table').forEach(function (t) {
  var tbody = t.tBodies[0]; if (!tbody) return;
  t.querySelectorAll('thead th').forEach(function (th, col) {
    var dir = 1;
    th.addEventListener('click', function () {
      dir = -dir;
      var rows = Array.prototype.slice.call(tbody.rows);
      rows.sort(function (a, b) {
        var ca = a.cells[col], cb = b.cells[col];
        var va = ca.dataset.sort !== undefined ? parseFloat(ca.dataset.sort) : ca.innerText;
        var vb = cb.dataset.sort !== undefined ? parseFloat(cb.dataset.sort) : cb.innerText;
        if (typeof va === 'number' && typeof vb === 'number' && !isNaN(va) && !isNaN(vb))
          return (va - vb) * dir;
        return String(va).localeCompare(String(vb)) * dir;
      });
      rows.forEach(function (r) { tbody.appendChild(r); });
    });
  });
});
</script>
</body>
</html>
"""
)


def render_html(run: RunResult, out_path: str | Path) -> Path:
    """Write a self-contained HTML report to ``out_path`` and return the path."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = _model_rows(run)
    difficulties, diff_rows = _difficulty_rows(run)
    html = _HTML_TEMPLATE.render(
        run=run,
        rows=rows,
        lang_rows=_language_rows(run),
        difficulties=difficulties,
        diff_rows=diff_rows,
        problem_rows=_problem_rows(run),
        cost_per_correct=_fmt_cost_per_correct,
        methodology=_methodology_line(run),
        headline=_headline(rows),
        scatter=Markup(_scatter_svg(rows)),
        failure_order=FAILURE_ORDER,
        failure_labels=FAILURE_LABELS,
        any_config_priced=any(r["config_priced"] for r in rows),
        inf=float("inf"),
    )
    out.write_text(html, encoding="utf-8")
    return out


def export_raw(run: RunResult, out_dir: str | Path) -> tuple[Path, Path]:
    """Write ``results.json`` and ``results.csv``; return both paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "results.json"
    json_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")

    csv_path = out / "results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["model", "problem_slug", "language", "difficulty", "pass_at_1",
             "pass_at_k", "attempts", "passed_attempts", "timeouts", "no_code",
             "total_cost_usd", "avg_latency_ms", "retries"]
        )
        for pr in run.results:
            passed = sum(1 for e in pr.exec_results if e.passed)
            timeouts = sum(1 for e in pr.exec_results if e.timed_out)
            no_code = sum(1 for a in pr.attempts if a.code is None)
            cost = sum(a.cost_usd for a in pr.attempts)
            latencies = [a.latency_ms for a in pr.attempts]
            retries = sum(a.retries for a in pr.attempts)
            writer.writerow(
                [
                    pr.model,
                    pr.problem_slug,
                    pr.language.value,
                    pr.difficulty or "",
                    f"{pr.pass_at_1:.4f}",
                    f"{pr.pass_at_k:.4f}",
                    len(pr.attempts),
                    passed,
                    timeouts,
                    no_code,
                    f"{cost:.6f}",
                    f"{(sum(latencies) / len(latencies)) if latencies else 0.0:.1f}",
                    retries,
                ]
            )
    return json_path, csv_path


__all__ = ["render_cli", "render_html", "export_raw"]
