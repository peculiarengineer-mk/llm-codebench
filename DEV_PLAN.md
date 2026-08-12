# Dev Plan: Make filtered-attempt scoring self-consistent, put a visible gate on the raised spend cap, and correct the cost/sweep claims the docs now overstate

## Overview
The review surfaced one real scoring bug and a cluster of trust problems around it. The scoring bug is a disagreement between two authorities: `Attempt.sampled` says a `content_filter` attempt is never a sample, while `_classify` checks `ex.passed` first and will happily call it a pass — so a filtered-but-code-bearing attempt that actually solves a problem is both reported as a pass and excluded from pass@k. The fix is to narrow "filtered" to what the docstring already claims it means (a blocked reply with **no usable output**), which makes both authorities agree without either of them special-casing the other.

That narrowing is a contract change in `bench/types.py`, so it lands first and alone (T1); every report-layer consumer follows in `bench/report.py` (T2). The remaining work is independent of the scoring fix and of each other: the spend guard's silent cap-trip (T3), a run-start cost estimate so the 30× cap raise isn't invisible (T4), and the doc/config claims that don't reproduce (T5). Tests land last, split by file so they parallelize (T6, T7).

Note: `bench/runner.py` is deliberately **not** in this plan. Its `if code is None` branch and its `a.sampled` filter both stay correct under the new contract — T1 changes what `sampled` returns, not where it's consulted. If T1 proves that wrong, stop and re-plan rather than editing `runner.py` from inside another task.

## Design principles
- **Single owner per file.** Every file belongs to exactly one task. If your task needs a change in a file you don't own, stop and report it — do not edit across the boundary, even for a one-line fix.
- **Source tasks don't touch tests; test tasks don't touch source.** T1–T5 own `bench/` and docs; T6–T7 own `tests/`. A source task that breaks an existing test records the failure by name and stops.
- **Narrow, don't reorder.** Where a contract is wrong, tighten its definition rather than resequencing the checks that read it — the invariant `filtered ⊆ (code is None)` must hold after every task.
- **No new dependencies**, no reformatting of untouched code, no drive-by refactors. Match surrounding style and comment density.
- Never commit, push, or open a PR. Leave changes in the working tree for review.

## Task T1: Narrow the `filtered` contract to "blocked with no usable output"
### Tree org map
```
bench/
└── types.py   [MODIFIED]
```
### List of changes
1. Redefine `Attempt.filtered` to `self.finish_reason == "content_filter" and self.code is None`. Update its docstring to state the code-is-None condition explicitly, and to note that `code` is populated post-hoc by the runner, so this property is only meaningful after extraction.
2. Leave `Attempt.sampled` as `self.error is None and not self.filtered` — under the new `filtered`, this now correctly admits a partial-content attempt that still yielded runnable code. Extend its docstring with that case: a provider that streams a complete code fence and *then* trips the filter produced a genuine sample, and is scored normally.
3. Fix the `parse_effort` docstring: it claims a model id ending in parentheses "is not mistaken for an effort variant", which holds only for non-effort parens. State the real guarantee — only the three `VALID_EFFORTS` suffixes match — and note that `target_label("m (high)", None)` and `target_label("m", "high")` collide (theoretical; OpenRouter ids contain no spaces).
### Reason for changes
`filtered` and `sampled` are the contract every other layer reads. Fixing them here — and nowhere else — means T2's report changes are pure consumer updates against a settled definition, and `runner.py` needs no edit at all. Narrowing rather than reordering keeps the invariant `filtered ⊆ code is None`, which is what the `_classify` docstring and the `filtered` failure bucket already promise readers.
### Done when
- `python3 -c "from bench.types import Attempt"` then, constructed with `error=None`: `finish_reason='content_filter', code='x'` gives `filtered is False` and `sampled is True`; `finish_reason='content_filter', code=None` gives `filtered is True` and `sampled is False`.
- `git diff --name-only` lists `bench/types.py` and nothing else.
- `pytest -q` runs. Existing tests that encode the *old* contract may now fail — do **not** edit them (they belong to T6). Record any such failure by name in your final message and stop; that is a successful outcome for this task, not a blocker.
### Depends on
none

## Task T2: Realign the report layer with the narrowed contract
### Tree org map
```
bench/
└── report.py   [MODIFIED]
```
### List of changes
1. `_classify`: replace the raw `attempt.finish_reason == "content_filter"` test with `attempt.filtered`. Keep the `ex.passed` check first — under T1 a filtered attempt can no longer carry passing code, so the ordering is now sound rather than accidentally sound. Add a line to the docstring explaining that a partial-content filter block with usable code is classified on its execution result, not as `filtered`.
2. `export_raw`: switch the `filtered` tally and the `no_code` exclusion to `a.filtered` so the CSV agrees with `_classify`. Verify the header and data rows stay at 15 fields each and in the same order — the `filtered` column sits between `no_code` and `api_errors`.
3. `_filtered_problem`: an unsampled problem with a *mix* of api-errors and filter blocks currently reports as wholly filtered, so the banner blames the provider for what may be mostly a billing failure. Attribute by majority of unsampled attempts, ties going to `filtered`, and say so in the docstring.
4. HTML template (`report.py:702`): the `{% if r.scored == 0 %}` branch hardcodes `(untested)`. Choose the label from the row — `(filtered)` when `r.filtered_problems` and not `r.untested`, `(untested)` when the reverse, `(excluded)` when both. This is the one cell that still conflates the two states the diff exists to separate.
5. Sweep the CLI and HTML footnotes for the same conflation now that attribution is majority-based: the "all attempts API-errored" wording on the untested note is only accurate for problems that remain in the `untested` bucket.
### Reason for changes
Every one of these is a consumer of the T1 contract; grouping them keeps `report.py` single-owner and lets the whole report layer move in one reviewable step. Items 3–5 are the labelling half of the same defect as items 1–2 — the code now distinguishes filtered from untested, but three surfaces still print the wrong one.
### Done when
- `grep -n 'finish_reason == "content_filter"' bench/report.py` returns nothing — every such test now reads `attempt.filtered`.
- `export_raw`'s CSV header and every data row have exactly 15 fields, with `filtered` positioned between `no_code` and `api_errors`.
- The HTML `scored == 0` branch can emit all three of `(filtered)`, `(untested)`, `(excluded)`; `grep -c '(untested)' bench/report.py` shows it is no longer the only hardcoded label.
- `git diff --name-only` lists `bench/report.py` and nothing else.
- `pytest -q` passes.
### Depends on
T1

## Task T3: Make a spend-cap halt visible and correctly attributed
### Tree org map
```
bench/
└── cost.py   [MODIFIED]
```
### List of changes
1. `SpendGuard.can_proceed` and `SpendGuard.record`: when `self._spent >= self._cap`, set `abort_reason` (not just `stopped`) to a message naming the cap and the amount spent, e.g. `f"Run halted — spend cap ${self._cap:.2f} reached (${self._spent:.2f} spent)."`. Reuse the existing idempotent first-reason-wins guard from `abort()` rather than assigning directly, so a prior fatal error keeps its message.
2. Resolve `SpendCapExceeded` (`cost.py:99`): it is defined, exported in `__all__`, and never raised. Either raise it from the cap path or delete it and its export. Prefer deletion — the guard is a cooperative flag, not an exception-driven halt, and a dead exception in `__all__` invites a caller to `except` on something that never fires.
### Reason for changes
`runner.py:244` surfaces only `guard.abort_reason`, so a cap-truncated run today renders with no abort banner and its unrun problems land in the `untested` bucket, where the report tells the user "all attempts API-errored" — false. This is what makes the raised cap dangerous rather than merely expensive: the failure mode is silent. Fixing it in the guard fixes every consumer at once, and it's the precondition for T5's README text ("the default cap is sized to clear a full run") being honest.
### Done when
- A `SpendGuard` driven past its cap has a non-empty `abort_reason` naming both the cap and the spent amount.
- A guard given a prior fatal reason via `abort()` keeps that first reason after a subsequent cap trip (first-reason-wins is preserved).
- `grep -rn SpendCapExceeded bench/` returns nothing (deletion path) or exactly one `raise` plus its definition (raise path). No dangling `__all__` entry either way.
- `git diff --name-only` lists `bench/cost.py` and nothing else.
- `pytest -q` passes, including `tests/test_cost.py`.
### Depends on
none

## Task T4: Show the cost estimate before a real run, and fix the `--efforts` help
### Tree org map
```
bench/
└── cli.py   [MODIFIED]
```
### List of changes
1. In `_amain`, hoist the pricing fetch + `dry_run_estimate` call out of the `if run_config.dry_run:` branch so both paths compute an estimate. On the real-run path, print a one-line summary before `ensure_images` — targets, calls, estimated cost, and the active cap — rather than the full per-model table.
2. When the estimate exceeds `run_config.max_spend_usd`, print the same red warning the dry-run path uses (`cli.py:101-103`); the run proceeds, since T3 now makes the truncation visible when it happens.
3. Keep the estimate best-effort: a pricing-fetch failure must warn and continue to the benchmark, never abort it. Reuse the existing `try/except` shape from the dry-run branch.
4. Fix the `--efforts` help text (`cli.py:31-35`): "(the default: low, medium and high)" is false for the three effort-less gpt-5.6 tiers. State that the default is whatever each model configures in `config/models.yaml`, and keep the existing final sentence about the override applying to every selected model.
### Reason for changes
The cap raise from $5 to $150 removed the only friction on an accidental ~$110 spend, because `_print_estimate` is reachable only under `--dry-run` — a user who forgets the flag gets "Running benchmark…" and no number at all. Printing the estimate restores the signal without adding an interactive prompt to a tool that's run in scripts. `dry_run_estimate` already lives in `bench/runner.py` and `_print_estimate` in this file, so no other file moves.
### Done when
- `python3 -m bench.cli --help` shows `--efforts` help that no longer claims "the default: low, medium and high".
- The pricing fetch and `dry_run_estimate` call are outside the `if run_config.dry_run:` branch — verify by inspection that both paths reach them.
- A simulated pricing-fetch failure warns and continues rather than raising: the estimate is best-effort and must never abort a real run.
- `git diff --name-only` lists `bench/cli.py` and nothing else.
- `pytest -q` passes.
### Depends on
none

## Task T5: Correct the cost, sweep, and CSV claims the docs overstate
### Tree org map
```
README.md              [MODIFIED]
bench/
└── config.py          [MODIFIED]
config/
└── models.yaml        [MODIFIED]
```
### List of changes
1. `README.md` + the `DEFAULT_MAX_SPEND_USD` comment in `config.py`: replace "≈$135 at current prices". Re-run `--dry-run` against the current roster and quote the number it actually prints (~$108 with the prices documented in `models.yaml`), and say it's a `REASONING_TOKENS` heuristic, not a measurement. Keep the cap at 150.0 — the gap is headroom over a rough estimate, which is the right direction — but justify it by the reproduced figure.
2. `README.md`: "triples the target count" describes targets (8 → 18, 2.25×) but readers will calibrate spend from it, and cost goes ~10× ($10.56 → ~$108) because high-effort reasoning tokens dominate. State both multipliers separately.
3. `README.md`: drop or qualify "every reasoning-capable model in `config/models.yaml` is swept" — `gpt-5.6-sol` is reasoning-capable and deliberately unswept. Point at the yaml note that explains why.
4. `README.md`: "Select a subset with `--efforts`" is wrong — a non-empty `--efforts` applies to *every* selected model (`config.py:146-151`), so the doc's own `--efforts high` example silently converts luna/terra/sol into `(high)` targets, which is exactly the tier × effort conflation the yaml note avoids. Describe the override semantics and flag that consequence.
5. `README.md:50`: add the new `filtered` column to the documented CSV column list.
6. `config/models.yaml`: add a price comment for `claude-fable-5` — it is the only roster entry without one, which is why the $135 figure couldn't be reproduced.
### Reason for changes
Four separate claims in this diff's own doc hunks don't survive contact with the code, and the one number a user would rely on to size a $150 cap is the one that can't be reproduced. `config.py` is here rather than with the source tasks because its only change is the comment carrying the same unreproducible figure — grouping it with the README keeps the number in one owner's hands.
### Done when
- `grep -rn '135' README.md bench/config.py` returns no cost claim — the figure is replaced by one reproduced from `--dry-run` against the current roster.
- The replacement figure is stated as a `REASONING_TOKENS` heuristic, not a measurement, and `DEFAULT_MAX_SPEND_USD` is still `150.0`.
- `grep -n 'claude-fable-5' -A3 config/models.yaml` shows a price comment, so no roster entry lacks one.
- README's documented CSV column list includes `filtered`.
- `git diff --name-only` lists exactly `README.md`, `bench/config.py`, `config/models.yaml`.
### Depends on
none

## Task T6: Regression tests for the narrowed filtered contract
### Tree org map
```
tests/
├── test_variants.py   [MODIFIED]
└── test_report.py     [MODIFIED]
```
### List of changes
1. `test_variants.py` — the defect from finding #1, as a direct test: an attempt with `finish_reason="content_filter"` **and** extracted code that passes must classify as `"pass"`, be `sampled`, and not be `filtered`. This test fails on `main`.
2. `test_variants.py` — end-to-end through `run_benchmark`: a filtered attempt with no code is excluded from `pass_at_k`, and the runner writes the `finish_reason=content_filter` stderr. Currently only the client-level capture and `_classify` are tested; the wiring between them is unguarded.
3. `test_report.py` — a fully-filtered model (`scored == 0` via filtering, not api-errors) renders `(filtered)`, not `(untested)`, in the HTML leaderboard cell.
4. `test_report.py` — mixed api-error + filtered attempts *on the same problem* attribute by majority. The existing `test_filtered_and_apierror_exclusions_are_distinct` only mixes them across different problems.
5. `test_report.py` — assert `row["low_conf"]` is True in `test_filtered_problem_excluded_from_passk_and_tracked_separately`, which already constructs that state (1 sample < k=3) and never checks it.
6. `test_report.py` — strengthen `test_html_renders_per_effort_section_headings`: it asserts only that heading strings exist, so it would pass if the template reverted `section.rows` to the flat `rows` and duplicated every model under every heading. Assert per-section row membership in the rendered HTML.
### Reason for changes
Item 1 is the regression guard for the only finding that produced a wrong leaderboard number; items 3–4 guard T2's labelling changes; item 6 closes a test that currently can't fail for the reason it exists. Splitting from T7 by file lets both test tasks run in parallel.
### Done when
- `pytest tests/test_variants.py tests/test_report.py -q` passes, with at least one new test per numbered item.
- The item-1 test is a genuine regression guard: it must fail against the pre-T1 contract. Confirm by reasoning from the assertion (a `content_filter` attempt with passing code classifying as `"pass"`), and say so explicitly in your final message.
- `git diff --name-only` lists exactly `tests/test_variants.py` and `tests/test_report.py`.
- No `bench/` source file is modified. If a test cannot pass without a source change, stop and report it.
### Depends on
T1, T2

## Task T7: First coverage for the untested output paths
### Tree org map
```
tests/
└── test_export_cli.py   [NEW]
```
### List of changes
1. `export_raw`: round-trip the CSV with `csv.DictReader` and assert header/data alignment field by field — 15 columns, `filtered` between `no_code` and `api_errors`. Include a problem with 2 api-errors + 1 filter block and assert `no_code=0, filtered=1, api_errors=2`. This is the guard against the mid-row column insert silently shifting every downstream field.
2. `export_raw`: assert the JSON export stays consistent with the CSV for the same run.
3. `render_cli`: smoke-test the sectioned output with a `rich` `Console(file=StringIO(), width=200)` — both effort boards print under their own titles, the plain "Leaderboard" title appears for a single-section run, and the filtered-problems warning fires when a row has `filtered_problems`.
### Reason for changes
`export_raw` and `render_cli` have zero test coverage today, and this diff rewrote both — the sectioned CLI refactor and a mid-row CSV column insert. Both are correct as verified by hand, but a break in either ships unnoticed. New file so it can't collide with T6.
### Done when
- `pytest tests/test_export_cli.py -q` passes.
- The CSV test uses `csv.DictReader` and asserts all 15 fields by name, including `filtered` between `no_code` and `api_errors`, and covers the 2-api-error + 1-filter case with `no_code=0, filtered=1, api_errors=2`.
- The `render_cli` test drives a `rich` `Console(file=StringIO(), width=200)` and asserts on captured output — it must not require a TTY.
- `git diff --name-only` shows only the new `tests/test_export_cli.py`; no existing file is modified.
### Depends on
T2

---
## File ownership map
- `bench/types.py` → T1
- `bench/report.py` → T2
- `bench/cost.py` → T3
- `bench/cli.py` → T4
- `README.md` → T5
- `bench/config.py` → T5
- `config/models.yaml` → T5
- `tests/test_variants.py` → T6
- `tests/test_report.py` → T6
- `tests/test_export_cli.py` → T7 [NEW]
- `bench/runner.py` → unowned, intentionally untouched (see Overview)

Verified: no file is touched by more than one task.

## Out of scope
- **`bench/runner.py`** — deliberately untouched (see Overview). Its `if code is None` branch and `a.sampled` filter stay correct under the narrowed contract. A task that believes otherwise stops and reports.
- `bench/openrouter.py`, `bench/extract.py`, `bench/sandbox.py`, `bench/problems.py` — not part of this phase.
- Changing `DEFAULT_MAX_SPEND_USD` away from `150.0`. T5 justifies the number; it does not move it.
- Making `SpendGuard` exception-driven. T3 keeps it a cooperative flag; `SpendCapExceeded` is resolved, not promoted.
- Adding an interactive confirmation prompt to the CLI — the tool runs in scripts (T4 prints, it does not ask).
- New dependencies, CI config, `pyproject.toml`, and reformatting of code no task owns.
- Committing, pushing, or opening a PR.

## Acceptance for the phase
- [ ] Full suite green: `pytest -q` (baseline before this phase: 63 passed — expect strictly more).
- [ ] `git diff --name-only` is a subset of the File ownership map, and `bench/runner.py` does **not** appear.
- [ ] A `content_filter` attempt carrying passing code scores as a pass, is `sampled`, and is counted in pass@k — the defect this phase exists to fix.
- [ ] The invariant `filtered ⊆ (code is None)` holds; `grep -rn 'finish_reason == "content_filter"' bench/report.py` is empty.
- [ ] CSV export has 15 columns in both header and data rows, `filtered` between `no_code` and `api_errors`.
- [ ] A cap-truncated run renders an abort banner naming the cap; its unrun problems are not attributed to API errors.
- [ ] A real (non-dry-run) invocation prints a cost estimate and the active cap before work starts.
- [ ] No unreproducible cost figure remains: `grep -rn '135' README.md bench/config.py` returns no cost claim.

## Suggested execution order
- Sequential: T1 → T2 → (T6, T7 in parallel)
- Fully parallel with the above and with each other: T3, T4, T5

Critical path is T1 → T2 → T6/T7. T3, T4 and T5 share no files with it and can start immediately.

## Ready to hand off?
