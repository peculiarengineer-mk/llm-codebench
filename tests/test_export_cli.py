"""Output-surface tests: export_raw CSV/JSON round-trip, render_cli sections."""

import csv
import json
from io import StringIO

import pytest
from rich.console import Console

from bench.report import export_raw, render_cli
from bench.types import Attempt, ExecResult, Language, ProblemResult, RunResult


def _att(passed=False, error=None):
    return Attempt(
        code=None if error else "code", latency_ms=0.0 if error else 100.0,
        ttft_ms=None if error else 50.0, prompt_tokens=0 if error else 5,
        completion_tokens=0 if error else 5, cost_usd=0.0 if error else 0.001,
        price_source="api", raw_response="" if error else "ok", error=error,
    )


def _filtered_att():
    """An empty content-filter block: HTTP 200, no code, no error."""
    return Attempt(
        code=None, latency_ms=1.0, ttft_ms=None, prompt_tokens=5,
        completion_tokens=1, cost_usd=0.0, price_source="api",
        raw_response="", error=None, finish_reason="content_filter",
    )


def _ex(passed):
    return ExecResult(passed=passed, stdout="", stderr="", exit_code=0 if passed else -1,
                      duration_ms=1.0, timed_out=False)


def _pr(model, slug, diff, attempts_spec):
    """attempts_spec: list of (passed, error) tuples."""
    atts = [_att(passed=p, error=e) for p, e in attempts_spec]
    exs = [_ex(p and e is None) for p, e in attempts_spec]
    scored = [(a, e) for a, e in zip(atts, exs) if a.error is None]
    n = len(scored)
    c = sum(1 for _, e in scored if e.passed)
    from bench.runner import pass_at_k
    return ProblemResult(
        model=model, problem_slug=slug, language=Language.python,
        pass_at_1=pass_at_k(n, c, 1) if n else 0.0,
        pass_at_k=pass_at_k(n, c, 3) if n else 0.0,
        attempts=atts, exec_results=exs, difficulty=diff,
    )


def _run(results, **kw):
    return RunResult(
        results=results, total_cost_usd=0.0, total_latency_ms=0.0,
        models=sorted({r.model for r in results}), problems_count=len(results),
        k=3, **kw,
    )


# The CSV column order, pinned: a mid-row column insert must fail here rather
# than silently shift every downstream field.
EXPECTED_HEADER = [
    "model", "problem_slug", "language", "difficulty", "pass_at_1",
    "pass_at_k", "attempts", "passed_attempts", "timeouts", "no_code",
    "filtered", "api_errors", "total_cost_usd", "avg_latency_ms", "retries",
]


def _mixed_run():
    """One clean solved problem + one problem with 2 api-errors and 1 filter block."""
    solved = _pr("m", "p1", "easy", [(True, None)])
    blocked = ProblemResult(
        model="m", problem_slug="p2", language=Language.python,
        pass_at_1=0.0, pass_at_k=0.0,
        attempts=[_att(error="HTTP 402"), _att(error="HTTP 402"), _filtered_att()],
        exec_results=[_ex(False)] * 3, difficulty="easy",
    )
    return _run([solved, blocked])


def test_export_raw_csv_header_and_rows_align(tmp_path):
    _, csv_path = export_raw(_mixed_run(), tmp_path)
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fields = reader.fieldnames

    assert fields == EXPECTED_HEADER
    assert len(fields) == 15
    # `filtered` sits mid-row, between `no_code` and `api_errors`.
    assert (fields.index("no_code") + 1 == fields.index("filtered")
            == fields.index("api_errors") - 1)

    # Field-by-field via DictReader: a column shift misaligns every value.
    assert rows[0] == {
        "model": "m", "problem_slug": "p1", "language": "python",
        "difficulty": "easy", "pass_at_1": "1.0000", "pass_at_k": "1.0000",
        "attempts": "1", "passed_attempts": "1", "timeouts": "0",
        "no_code": "0", "filtered": "0", "api_errors": "0",
        "total_cost_usd": "0.001000", "avg_latency_ms": "100.0", "retries": "0",
    }
    # 2 api-errors + 1 filter block: the block is NOT counted as no_code.
    assert rows[1] == {
        "model": "m", "problem_slug": "p2", "language": "python",
        "difficulty": "easy", "pass_at_1": "0.0000", "pass_at_k": "0.0000",
        "attempts": "3", "passed_attempts": "0", "timeouts": "0",
        "no_code": "0", "filtered": "1", "api_errors": "2",
        "total_cost_usd": "0.000000", "avg_latency_ms": "0.3", "retries": "0",
    }


def test_export_raw_json_matches_csv(tmp_path):
    json_path, csv_path = export_raw(_mixed_run(), tmp_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    jresults = data["results"]
    assert len(rows) == len(jresults) == 2
    for csv_row, jrow in zip(rows, jresults):
        assert csv_row["model"] == jrow["model"]
        assert csv_row["problem_slug"] == jrow["problem_slug"]
        assert csv_row["language"] == jrow["language"]
        assert csv_row["difficulty"] == jrow["difficulty"]
        # CSV rounds: pass rates to 4dp, cost to 6dp.
        assert float(csv_row["pass_at_1"]) == pytest.approx(jrow["pass_at_1"], abs=1e-4)
        assert float(csv_row["pass_at_k"]) == pytest.approx(jrow["pass_at_k"], abs=1e-4)
        assert int(csv_row["attempts"]) == len(jrow["attempts"])
        assert int(csv_row["passed_attempts"]) == sum(
            1 for e in jrow["exec_results"] if e["passed"])
        assert int(csv_row["api_errors"]) == sum(
            1 for a in jrow["attempts"] if a["error"] is not None)
        # `filtered` is a derived property, not serialized — recompute it.
        assert int(csv_row["filtered"]) == sum(
            1 for a in jrow["attempts"]
            if a["finish_reason"] == "content_filter" and a["code"] is None)
        assert float(csv_row["total_cost_usd"]) == pytest.approx(
            sum(a["cost_usd"] for a in jrow["attempts"]), abs=1e-6)


def _render(run):
    """Drive render_cli into an in-memory console — no TTY required."""
    buf = StringIO()
    render_cli(run, Console(file=buf, width=200))
    return buf.getvalue()


def test_render_cli_effort_sections_under_own_titles():
    results = [
        _pr("m (low)", "p1", "easy", [(True, None)]),
        _pr("m (high)", "p1", "easy", [(True, None)]),
    ]
    out = _render(_run(results))
    assert "Leaderboard — low effort" in out
    assert "Leaderboard — high effort" in out
    # Each board lists only its own variant: slice each section by its title.
    low_seg = out.split("Leaderboard — low effort", 1)[1]
    low_seg = low_seg[: low_seg.index("Leaderboard — high effort")]
    assert "m (low)" in low_seg and "m (high)" not in low_seg
    high_seg = out.split("Leaderboard — high effort", 1)[1]
    high_seg = high_seg[: high_seg.index("Failure modes")]
    assert "m (high)" in high_seg and "m (low)" not in high_seg


def test_render_cli_single_section_keeps_plain_title():
    out = _render(_run([_pr("m", "p1", "easy", [(True, None)])]))
    assert "Leaderboard" in out
    assert "Leaderboard —" not in out  # no effort qualifier on a single board


def test_render_cli_filtered_problems_warning():
    blocked = ProblemResult(
        model="fable", problem_slug="p2", language=Language.python,
        pass_at_1=0.0, pass_at_k=0.0,
        attempts=[_filtered_att()] * 3,
        exec_results=[_ex(False)] * 3, difficulty="easy",
    )
    out = _render(_run([blocked]))
    assert "filtered problems excluded from scoring" in out
    assert "fable (1)" in out
