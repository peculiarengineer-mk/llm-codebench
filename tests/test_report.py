"""Report aggregation tests — untested-problem exclusion, headline, dedup."""

from bench.config import expand_targets
from bench.report import _headline, _model_rows, _untested, render_html
from bench.types import (
    Attempt,
    ExecResult,
    Language,
    ModelSpec,
    ProblemResult,
    RunResult,
)


def _att(passed=False, error=None):
    return Attempt(
        code=None if error else "code", latency_ms=0.0 if error else 100.0,
        ttft_ms=None if error else 50.0, prompt_tokens=0 if error else 5,
        completion_tokens=0 if error else 5, cost_usd=0.0 if error else 0.001,
        price_source="api", raw_response="" if error else "ok", error=error,
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


def test_untested_helper():
    assert _untested(_pr("m", "p", "easy", [(False, "402"), (False, "402")]))
    assert not _untested(_pr("m", "p", "easy", [(True, None), (False, "402")]))


def test_fully_errored_problem_excluded_from_denominator():
    # model A: 1 solved problem + 1 fully-errored problem.
    results = [
        _pr("A", "p1", "easy", [(True, None), (False, "402"), (False, "402")]),
        _pr("A", "p2", "easy", [(False, "402"), (False, "402"), (False, "402")]),
    ]
    row = _model_rows(_run(results))[0]
    assert row["scored"] == 1          # p2 never sampled -> excluded
    assert row["untested"] == 1
    assert row["solved"] == 1
    assert row["pass_at_k"] == 1.0     # scored over p1 only, not dragged to 50%
    assert row["low_conf"] is True     # p1 had only 1 of k=3 valid samples


def test_fully_untested_model_not_crowned():
    results = [
        _pr("good", "p1", "easy", [(True, None)]),
        _pr("dead", "p1", "easy", [(False, "402")]),
    ]
    rows = _model_rows(_run(results))
    assert rows[0]["model"] == "good"          # dead ($0, 0%) must not sort first
    dead = next(r for r in rows if r["model"] == "dead")
    assert dead["scored"] == 0
    assert _headline(_run(results), rows).startswith("good leads")


def test_headline_on_aborted_run():
    results = [_pr("m", "p1", "easy", [(False, "402")])]
    run = _run(results, aborted_reason="Run aborted — HTTP 402")
    assert "did not complete" in _headline(run, _model_rows(run))


def test_headline_when_nothing_solved():
    results = [_pr("m", "p1", "easy", [(False, None)])]  # sampled, wrong answer
    run = _run(results)
    assert _headline(run, _model_rows(run)) == "No model solved any problem in this run."


def test_html_shows_abort_banner(tmp_path):
    results = [_pr("m", "p1", "easy", [(False, "402")])]
    run = _run(results, aborted_reason="Run aborted — HTTP 402 out of credits")
    html = render_html(run, tmp_path / "r.html").read_text()
    assert "did not complete" in html.lower() or "402" in html
    assert "untested" in html.lower()


def test_expand_targets_dedups_labels():
    specs = [ModelSpec(id="m"), ModelSpec(id="m")]
    assert [t.label for t in expand_targets(specs)] == ["m"]


def test_empty_efforts_override_is_no_override():
    specs = [ModelSpec(id="m", efforts=["high"])]
    # empty override must NOT wipe out targets; per-spec efforts still apply
    assert [t.label for t in expand_targets(specs, efforts_override=[])] == ["m (high)"]
