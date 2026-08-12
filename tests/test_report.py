"""Report aggregation tests — untested-problem exclusion, headline, dedup."""

from bench.config import expand_targets
from bench.report import (
    _grouped_model_rows,
    _headline,
    _model_rows,
    _untested,
    render_html,
)
from bench.types import (
    Attempt,
    ExecResult,
    Language,
    ModelSpec,
    ProblemResult,
    RunResult,
    parse_effort,
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


def _filtered_att():
    """An empty content-filter block: HTTP 200, no code, no error."""
    return Attempt(
        code=None, latency_ms=1.0, ttft_ms=None, prompt_tokens=5,
        completion_tokens=1, cost_usd=0.0, price_source="api",
        raw_response="", error=None, finish_reason="content_filter",
    )


def test_filtered_problem_excluded_from_passk_and_tracked_separately():
    # fable-like: solves 1 real problem, gets content-filtered on another.
    ok = _pr("fable", "p1", "easy", [(True, None)])
    blocked = ProblemResult(
        model="fable", problem_slug="p2", language=Language.python,
        pass_at_1=0.0, pass_at_k=0.0,
        attempts=[_filtered_att(), _filtered_att(), _filtered_att()],
        exec_results=[_ex(False)] * 3, difficulty="easy",
    )
    row = _model_rows(_run([ok, blocked]))[0]
    assert row["scored"] == 1              # only p1 counts
    assert row["filtered_problems"] == 1   # p2 surfaced as filtered, not untested
    assert row["untested"] == 0
    assert row["pass_at_k"] == 1.0         # 1/1, not dragged to 50% by the block
    assert row["low_conf"] is True         # p1 sampled only once out of k=3
    assert row["fails"]["filtered"] == 3   # three filtered attempts tallied
    assert row["fails"]["no_code"] == 0    # not miscounted as no-code


def test_filtered_and_apierror_exclusions_are_distinct():
    filt = ProblemResult(
        model="m", problem_slug="pf", language=Language.python, pass_at_1=0.0,
        pass_at_k=0.0, attempts=[_filtered_att()], exec_results=[_ex(False)],
        difficulty="easy",
    )
    err = _pr("m", "pe", "easy", [(False, "402")])
    good = _pr("m", "pg", "easy", [(True, None)])
    row = _model_rows(_run([filt, err, good]))[0]
    assert row["scored"] == 1
    assert row["filtered_problems"] == 1   # pf
    assert row["untested"] == 1            # pe (api error) — kept separate


def test_html_fully_filtered_model_cell_says_filtered_not_untested(tmp_path):
    # A model excluded purely by filter blocks reads (filtered) in the
    # leaderboard cell — (untested) would blame an API failure that didn't happen.
    blocked = ProblemResult(
        model="fable", problem_slug="p1", language=Language.python,
        pass_at_1=0.0, pass_at_k=0.0,
        attempts=[_filtered_att(), _filtered_att(), _filtered_att()],
        exec_results=[_ex(False)] * 3, difficulty="easy",
    )
    run = _run([blocked])
    row = _model_rows(run)[0]
    assert row["scored"] == 0
    assert row["filtered_problems"] == 1 and row["untested"] == 0
    html = render_html(run, tmp_path / "r.html").read_text()
    # Pin the cell markup specifically: the page footer mentions both words.
    assert '<span class="ci">(filtered)</span>' in html
    assert '<span class="ci">(untested)</span>' not in html


def test_mixed_problem_exclusion_attributed_by_attempt_majority():
    # api-error and filtered attempts mixed on ONE problem: the exclusion is
    # attributed by the majority of its unsampled attempts, ties to filtered.
    def mixed(slug, atts):
        return ProblemResult(
            model="m", problem_slug=slug, language=Language.python,
            pass_at_1=0.0, pass_at_k=0.0, attempts=atts,
            exec_results=[_ex(False)] * len(atts), difficulty="easy",
        )

    err_att = _att(error="HTTP 402")
    maj_filt = mixed("pf", [_filtered_att(), _filtered_att(), err_att])
    maj_err = mixed("pe", [_filtered_att(), err_att, err_att])
    tie = mixed("pt", [_filtered_att(), err_att])
    row = _model_rows(_run([maj_filt, maj_err, tie]))[0]
    assert row["scored"] == 0
    assert row["filtered_problems"] == 2  # pf (2-of-3 blocks) + pt (tie)
    assert row["untested"] == 1           # pe — mostly api-errored


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


def test_parse_effort_roundtrips_target_label():
    assert parse_effort("anthropic/claude-opus-4.8 (high)") == "high"
    assert parse_effort("anthropic/claude-opus-4.8 (low)") == "low"
    # No suffix -> effort-less; a bare id with parens that isn't an effort stays None.
    assert parse_effort("openai/gpt-5.6-luna") is None
    assert parse_effort("some/model (turbo)") is None


def test_grouped_rows_split_into_effort_sections_in_order():
    results = [
        _pr("m (high)", "p1", "easy", [(True, None)]),
        _pr("m (low)", "p1", "easy", [(True, None)]),
        _pr("m (medium)", "p1", "easy", [(True, None)]),
        _pr("tierX", "p1", "easy", [(True, None)]),  # effort-less -> default
    ]
    sections = _grouped_model_rows(_run(results))
    assert [s["effort"] for s in sections] == ["low", "medium", "high", None]
    # Multi-section run qualifies each heading; effort-less is the "default" board.
    assert sections[0]["title"] == "Leaderboard — low effort"
    assert sections[-1]["title"] == "Leaderboard — default (no effort)"
    assert [r["model"] for r in sections[0]["rows"]] == ["m (low)"]
    assert [r["model"] for r in sections[-1]["rows"]] == ["tierX"]


def test_grouped_rows_single_section_keeps_plain_title():
    # A run with no effort variants stays one plain "Leaderboard".
    results = [_pr("m", "p1", "easy", [(True, None)])]
    sections = _grouped_model_rows(_run(results))
    assert len(sections) == 1
    assert sections[0]["title"] == "Leaderboard"
    assert sections[0]["effort"] is None


def test_grouped_rows_single_pinned_effort_keeps_plain_title():
    # --efforts high -> only the high section exists, so no qualifier needed.
    results = [_pr("m (high)", "p1", "easy", [(True, None)])]
    sections = _grouped_model_rows(_run(results))
    assert len(sections) == 1
    assert sections[0]["title"] == "Leaderboard"
    assert sections[0]["effort"] == "high"


def test_html_renders_per_effort_section_headings(tmp_path):
    results = [
        _pr("m (low)", "p1", "easy", [(True, None)]),
        _pr("m (high)", "p1", "easy", [(True, None)]),
    ]
    html = render_html(_run(results), tmp_path / "r.html").read_text()
    assert "Leaderboard — low effort" in html
    assert "Leaderboard — high effort" in html
    # Per-section membership: slice each heading to the end of its table, so a
    # template rendering the flat `rows` under every heading (duplicating each
    # model) fails here. The later failure-mode table lists both models, which
    # is why the slice stops at the section's own </table>.
    def section_table(heading):
        seg = html.split(heading, 1)[1]
        return seg[: seg.index("</table>")]

    low = section_table("Leaderboard — low effort")
    high = section_table("Leaderboard — high effort")
    assert "m (low)" in low and "m (high)" not in low
    assert "m (high)" in high and "m (low)" not in high


def test_expand_targets_dedups_labels():
    specs = [ModelSpec(id="m"), ModelSpec(id="m")]
    assert [t.label for t in expand_targets(specs)] == ["m"]


def test_empty_efforts_override_is_no_override():
    specs = [ModelSpec(id="m", efforts=["high"])]
    # empty override must NOT wipe out targets; per-spec efforts still apply
    assert [t.label for t in expand_targets(specs, efforts_override=[])] == ["m (high)"]


def test_sections_order_full_effort_ladder_and_skip_unused():
    """xhigh/max get their own boards, ordered cheapest→deepest→default.

    Before the enum widened, _EFFORT_SECTION_ORDER stopped at high, so an
    xhigh/max target parsed to an effort with no section and vanished from the
    ordered output. Also pins that unused levels are skipped rather than
    rendering empty boards.
    """
    results = [
        _pr("m (max)", "p1", "easy", [(True, None)]),
        _pr("m (low)", "p1", "easy", [(True, None)]),
        _pr("plain", "p1", "easy", [(True, None)]),
        _pr("m (xhigh)", "p1", "easy", [(True, None)]),
    ]
    sections = _grouped_model_rows(_run(results))
    # medium/high were never used -> no empty boards for them
    assert [s["effort"] for s in sections] == ["low", "xhigh", "max", None]
    assert [r["model"] for r in sections[1]["rows"]] == ["m (xhigh)"]
    assert sections[-1]["title"] == "Leaderboard — default (no effort)"


def test_html_renders_xhigh_and_max_section_headings(tmp_path):
    results = [
        _pr("m (xhigh)", "p1", "easy", [(True, None)]),
        _pr("m (max)", "p1", "easy", [(True, None)]),
    ]
    html = render_html(_run(results), tmp_path / "r.html").read_text()
    assert "Leaderboard — xhigh effort" in html
    assert "Leaderboard — max effort" in html
