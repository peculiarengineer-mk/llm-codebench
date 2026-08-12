# Dev Plan: Stop infrastructure failures from scoring as model failures, and add Claude Opus 5 + Kimi K3 to the roster

## Overview
The code review found ten defects sharing one theme: a harness problem — a truncated reply, an expired API key, an OOM-killed container, a missing image — gets recorded as the *model* getting the answer wrong. Every scoring surface in this repo exists to separate "the model was wrong" from "the model never got a fair attempt," and each of these findings punches a hole in that separation. The two highest-value fixes are `extract.py` classifying prose as code (confirmed by execution: a fence-free reply with any indented line is shipped to the sandbox and scored as *wrong answer* rather than *no code*) and `openrouter.py` swallowing the HTTP status on the pricing fetch, so an expired key never triggers the fatal-abort path it was built for.

The work splits cleanly by file, one owner each, so almost everything runs in parallel.

T6 also closes a usability gap that matters for a tool this expensive to run: **there is currently no way to benchmark exactly one model cheaply.** `--models X` inherits `X`'s configured `efforts` and silently expands to three targets, and the only workaround — `--efforts high` — applies to every selected model and fabricates a `(high)` label on models that declare no efforts, which is the tier × effort conflation `config/models.yaml` already warns about. T6 adds `--list-targets` and `--target "<label>"` so a single (model, effort) pair can be selected by the same label the leaderboard uses.

**This is Phase 2. It assumes the existing `DEV_PLAN.md` phase has landed**, because that phase owns `types.py`, `report.py`, `cost.py`, `cli.py`, `config.py`, `models.yaml`, and the two test files, and this plan touches six of those. Running both phases concurrently will collide. `bench/cost.py` is not in this plan at all — the review found nothing in it that Phase 1 doesn't already fix.

**Flagged for your decision, deliberately not fixed here:** `VALID_EFFORTS` in `bench/types.py` is `("low", "medium", "high")`, but Claude Opus 5 supports `xhigh` and `max` — the two levels its own documentation recommends for coding and agentic work. Benchmarking Opus 5 at a `high` ceiling measures it below the setting it is designed to be used at. Widening the enum changes `parse_effort`, `target_label`, the report's `_EFFORT_SECTION_ORDER`, and the HTML section grouping — a larger change than this phase should absorb, and one that shifts every historical label. See **Out of scope**.

## Design principles
- **Single owner per file.** If your task needs a change in a file you don't own, stop and report it — do not edit across the boundary, even for a one-line fix.
- **Source tasks don't touch tests; test tasks don't touch source.** T1–T9 own `bench/`, `config/`, and docs; T10–T11 own `tests/`. A source task that breaks an existing test records the failure by name and stops.
- **Infra failure ≠ model failure.** Every fix here must preserve or sharpen that distinction. If a change would make an environment problem *look* like a wrong answer, it is the wrong change.
- **Never weaken sandbox isolation.** The `--network none`, `--read-only`, `--cap-drop ALL`, `--security-opt no-new-privileges`, and `:ro` mount flags in `bench/sandbox.py` are the boundary that makes running untrusted model output safe. Raising a memory limit is fine; removing an isolation flag is not.
- **No new runtime dependencies**, no reformatting of untouched code, no drive-by refactors. Match surrounding style and comment density.
- **Cost and pricing claims must be reproduced**, not recalled — quote a figure only if `--dry-run` or the live API produced it.
- Never commit, push, or open a PR. Leave changes in the working tree for review.

## Task T1: Stop classifying prose as code
### Tree org map
```
bench/
└── extract.py   [MODIFIED]
```
### List of changes
1. `_CODE_MARKERS[Language.python]` currently includes `"    "` (four spaces). Any prose containing one indented line matches, so `_looks_like_code` returns True for pure prose. Remove the bare-indent marker and replace the whole heuristic with one that requires *structural* evidence: a line that starts (after optional leading whitespace) with a language keyword — `def `/`class `/`import `/`from ` for Python, `function `/`const `/`export `/`class ` for TypeScript, `public `/`namespace `/`class `/`using ` for C#, `#!/`/a function-definition line for Bash. Match per line, anchored, not as a substring of the whole reply.
2. Require at least **two** distinct structural matches, or one match plus the reply being predominantly non-prose, before step 3 accepts a fence-free reply. A single stray `import` inside an explanatory paragraph is not a solution.
3. Docstring: state that step 3 is a deliberately conservative last resort — a reply that cannot be confidently identified as code must return `None` so the attempt is bucketed as `no_code`, not shipped to the sandbox to fail as a wrong answer. Name the failure mode being prevented.
4. Leave steps 1 and 2 (tagged fences, then any fence) untouched. This task changes only the fence-free path.
### Reason for changes
This is the only confirmed-by-execution finding, and it corrupts the headline failure-mode split: truncated replies (`finish_reason=length`) and models that explain before coding are the common cases, and both currently land in `failed` (wrong answer) instead of `no_code`. It is the same class of bug the entire Phase 1 plan exists to fix, and it was missed there. Tightening rather than deleting step 3 preserves the genuine case it was written for — a model that returns bare code with no fences.
### Done when
- `python3 -c "from bench.extract import extract_code; from bench.types import Language; print(extract_code('I will solve this. My approach:\n\n    First, sort the intervals.\n    Then merge them.\n\nUnfortunately I ran out of', Language.python))"` prints `None`.
- A fence-free reply that *is* real Python (starts with `def solve(...):` and an indented body) still returns the code, not `None`.
- Fenced extraction is unchanged: `pytest tests/test_extract.py -q` passes without editing that file.
- `git diff --name-only` lists `bench/extract.py` and nothing else.
### Depends on
none

## Task T2: Propagate HTTP status so a bad key aborts the run
### Tree org map
```
bench/
└── openrouter.py   [MODIFIED]
```
### List of changes
1. `_request_json` (`openrouter.py:295-309`) loses the status code twice: the retryable raise omits `status_code=`, and the final raise wraps `last_exc` without it. Capture the status from `httpx.HTTPStatusError` (and from the retryable branch) and pass `status_code=` on both raises, so a 401/402 on the `/models` fetch reaches the caller with its status intact.
2. `complete()` calls `_pricing_for` at line 178, **outside** the retry loop, so a pricing-fetch failure propagates directly out of `complete()`. Confirm the error that escapes now carries `status_code`; if wrapping is needed to preserve it, wrap without discarding the status. Do not move the pricing fetch inside the retry loop — a fatal status must not be retried.
3. `_is_retryable` (line 319) decides via `"retryable" in str(exc)`. Since the non-retryable branch embeds up to 500 bytes of response body (line 234), a 400 whose body happens to contain that word is retried. Replace the string test with `exc.status_code in _RETRYABLE_STATUS` (treating `status_code is None` as transient, matching the current transport-error behavior).
4. Delete the unused `raw_lines` accumulator (line 217 and its `append`) — collected, never read.
### Reason for changes
`runner.py:92` checks `exc.status_code in FATAL_STATUS` to decide whether to abort the whole run. With `status_code=None`, an expired or out-of-credit key never matches, so the harness grinds through every remaining (model × problem × k) attempt producing generic errors — exactly the scenario the fatal-abort path was built for. Items 1–2 are the fix; item 3 removes the adjacent fragility in the same file while it is open.
### Done when
- A simulated 401 from the `/models` endpoint produces an `OpenRouterError` whose `.status_code == 401` (verify with a stubbed transport, not a live call).
- `grep -n '"retryable" in' bench/openrouter.py` returns nothing.
- `grep -n raw_lines bench/openrouter.py` returns nothing.
- `pytest tests/test_openrouter.py -q` passes.
- `git diff --name-only` lists `bench/openrouter.py` and nothing else.
### Depends on
none

## Task T3: Give the C# sandbox memory headroom and preflight custom images
### Tree org map
```
bench/
└── sandbox.py   [MODIFIED]
```
### List of changes
1. `--memory 256m` is hardcoded for every language (`sandbox.py:176`), but the C# adapter requests a **512m tmpfs** (line 75) and copies the whole `/app` project into it before `dotnet run -c Release`. tmpfs pages count against the container's memory cgroup, so the tmpfs alone can exceed the cap before the SDK's own footprint. Move the memory limit onto `LangAdapter` as a per-language field and give C# enough headroom (start at `1g`, tmpfs unchanged); keep `256m` for python/typescript/bash.
2. Document the tmpfs/cgroup interaction in a comment on the new field — the constraint is `memory > tmpfs_size + runtime footprint`, and it is not obvious from either value alone.
3. `ensure_images` (line 137) builds only the four default images, never a problem's `Problem.image_tag`. A problem pointing at an unbuilt image fails inside `docker run` and is recorded as a *test failure*. Add a preflight: `run_in_sandbox` (or `ensure_images`, whichever keeps the async boundary clean) verifies an overridden `image_tag` exists via `_image_exists` and raises `SandboxError` if not — an environment error, not a model failure.
4. Do not change any isolation flag. `--network none`, `--read-only`, `--cap-drop ALL`, `--security-opt no-new-privileges`, and the `:ro` mount stay exactly as they are.
### Reason for changes
Both items are infra-failure-scored-as-model-failure. Item 1 is unconfirmed (it needs a Docker daemon to reproduce) but is the first thing to check if C# problems fail at an unusual rate; the fix is cheap and carries no isolation cost. Item 3 is latent — no current problem sets `image_tag` — but it converts a config typo into a silent leaderboard penalty, which is precisely the failure class this phase is closing.
### Done when
- `_docker_run_argv` emits `--memory 1g` for `Language.csharp` and `--memory 256m` for python/typescript/bash — assert on the argv list, no daemon required.
- Every isolation flag is still present and unchanged in the argv for all four languages.
- `run_in_sandbox` with a non-existent `image_tag` raises `SandboxError` naming the missing tag, with `_run`/`_image_exists` stubbed — no daemon required.
- `git diff --name-only` lists `bench/sandbox.py` and nothing else.
- `pytest -q` passes.
### Depends on
none

## Task T4: Account for cost on failed attempts and make the pass@k clamp explicit
### Tree org map
```
bench/
└── runner.py   [MODIFIED]
```
### List of changes
1. `guard.record(attempt.cost_usd)` runs only after a successful call (`runner.py:117`). An attempt that streams partially and then errors may have billed tokens that never count against the spend cap. In the `except OpenRouterError` branch, record whatever cost is known (0.0 when nothing is recoverable) and add a comment stating that partial-stream spend is not recoverable from the exception, so the cap can under-count by at most the in-flight attempts.
2. `pass_at_k` clamps `k` to `n` (line 61), so a problem with fewer usable samples than `k` reports pass@*n* in the pass@*k* column. Do not change the maths — the clamp is what avoids a zero denominator. Instead state the consequence explicitly in the docstring: the returned value is comparable across models **only** when `n == k`, and callers must surface the sample count alongside it. Reference `low_conf` in `report.py` as the existing flag.
3. Verify `bench/runner.py` needs no change for the narrowed `filtered` contract from Phase 1 — the `if code is None` branch and the `a.sampled` filter both stay correct. If that proves wrong, stop and report rather than editing.
### Reason for changes
Item 1 is a real gap in the spend guard: the cap exists to stop an accidental large spend, and attempts that fail mid-stream are exactly the ones a flaky provider produces in bulk. Item 2 is documentation rather than behavior because the honest fix — carrying the effective `k` through to the report — requires a `types.py` change owned by T8; recording the caveat where the clamp lives is the contained half, and T5 makes it machine-readable downstream.
### Done when
- The `except OpenRouterError` branch in `_run_one_attempt` calls `guard.record(...)`, and the comment states why partial-stream spend can be missed.
- `pass_at_k`'s docstring states the `n < k` comparability caveat and names `low_conf`.
- `bench/runner.py` is unmodified apart from those two edits — no logic change to `pass_at_k`'s arithmetic (`pytest tests/test_runner.py -q` still passes).
- `git diff --name-only` lists `bench/runner.py` and nothing else.
### Depends on
none

## Task T5: Make the sample-size caveat machine-readable in the exports
### Tree org map
```
bench/
└── report.py   [MODIFIED]
```
### List of changes
1. `export_raw`'s CSV carries `attempts` (total) but nothing that says how many were *usable samples*, so a downstream consumer cannot tell a clean pass@3 from a pass@1 wearing a pass@3 label. Add a `sampled` column counting `a.sampled` attempts per row, positioned adjacent to `attempts` so the pair reads together.
2. Update the header list, the data row, and the documented column count in the same edit. State the new count in a comment so the next mid-row insert has a number to check against.
3. Confirm the JSON export carries the same information (it serializes full `Attempt` objects, so `sampled` is derivable) and note that in the docstring — the CSV needs the explicit column precisely because it is flattened.
4. Do not change any leaderboard, HTML, or classification logic. This task adds one export column and nothing else.
### Reason for changes
T4 documents the pass@k caveat where the clamp lives; this makes it actionable for anyone analyzing `results.csv`, which is the surface where the caveat is currently invisible — the CLI and HTML at least print a `†`. Scoping this task to one column keeps it out of the way of Phase 1's much larger `report.py` changes.
### Done when
- `export_raw`'s CSV header and every data row have the same field count, with `sampled` adjacent to `attempts` — verify by round-tripping a synthetic `RunResult` through `csv.DictReader` and comparing header length to row length.
- A problem with 3 attempts of which 1 is `sampled` exports `attempts=3, sampled=1`.
- `pytest tests/test_report.py -q` passes.
- `git diff --name-only` lists `bench/report.py` and nothing else.
### Depends on
none

## Task T6: Single-target selection, argument validation, and import cleanup
### Tree org map
```
bench/
└── cli.py   [MODIFIED]
```
### List of changes
1. **`--list-targets`**: resolve the roster to targets, print one label per line, exit 0. No API key, no network, no problem loading required beyond what config needs. This is the discovery half — you cannot select a target by label without first seeing the labels.
2. **`--target LABEL[,LABEL...]`**: select benchmark targets by their exact leaderboard label (e.g. `"anthropic/claude-opus-5 (high)"`, or `"openai/gpt-5.6-luna"` for an effort-less model). Resolve the full target list as today, then filter it to the named labels. Build the filtered `RunConfig` with `run_config.model_copy(update={"targets": kept, "models": [t.label for t in kept]})` — keep the whole change inside `cli.py`; do not edit `config.py` (T8 owns it).
3. An unmatched `--target` label is an error, not a silent empty run: exit 2 with a message naming the bad label and listing the available ones (the same list `--list-targets` prints). This is the single most likely user mistake — a typo or a missing `(effort)` suffix.
4. **`--target` and `--efforts` are mutually exclusive** — reject the combination with exit 2. `--efforts` rewrites which targets exist; `--target` selects among the ones that do. Accepting both invites the user to filter a list they just fabricated.
5. `--help` text must state the distinction plainly, because it is the whole point of this task: **`--models X` runs every effort level `X` configures** (three targets for a swept model, so roughly 3× the cost of one), while **`--target "X (low)"` runs exactly one**. Say this on both flags.
6. `--k` is unvalidated: `--k 0` yields `range(0)`, zero attempts, every problem "untested", and exit 0 — a silently empty run that looks like a completed one. Reject `k < 1` with a clear message and exit 2 (matching the existing config-error path).
7. Reject `--max-spend <= 0` and `--concurrency < 1` the same way. A zero cap trips `can_proceed` on the first check and produces the same silent-empty-run shape.
8. Replace the two `__import__("os").environ.get(...)` calls (`cli.py:161-162`) with a module-level `import os`.
9. Keep every validation message in the same voice as the existing `Config error:` output, and route them through the same `console.print` + `return 2` path rather than raising.
### Reason for changes
There is currently no way to benchmark exactly one model cheaply. `--models X` inherits `X`'s configured `efforts` and expands to three targets; the only workaround, `--efforts high`, applies the override to *every* selected model and fabricates a `(high)` label on models that declare no efforts — the tier × effort conflation the yaml note already warns about. Selecting by label sidesteps both problems, because `target_label`/`parse_effort` already round-trip and the label is the identity used in the leaderboard, CSV, and HTML. Items 6–8 are the validation and cleanup findings from the review, grouped here because they are the same file and the same argument-handling surface.
### Done when
- `python3 -m bench.cli --list-targets` prints one label per line and exits 0 with no API key set.
- `python3 -m bench.cli --target "<a label from that list>" --dry-run` prices **exactly one** target; the dry-run table has one row.
- Selecting an effort-less model by bare id (e.g. `--target "openai/gpt-5.6-luna"`) yields one target whose label carries **no** `(effort)` suffix — the conflation `--efforts` causes does not reappear.
- `python3 -m bench.cli --target "does/not-exist"` exits 2, names the bad label, and lists the valid ones.
- `python3 -m bench.cli --target "X" --efforts high` exits 2 explaining the two flags are mutually exclusive.
- `python3 -m bench.cli --k 0 --dry-run`, `--max-spend 0 --dry-run`, and `--concurrency 0 --dry-run` each exit 2 naming the offending flag.
- A valid invocation is unaffected: `python3 -m bench.cli --dry-run` still runs (or fails only for a missing API key, not for validation).
- `--help` states the `--models` vs `--target` cost distinction.
- `grep -n '__import__' bench/cli.py` returns nothing.
- `git diff --name-only` lists `bench/cli.py` and nothing else — in particular **not** `bench/config.py`.
### Depends on
none

## Task T7: Require an entrypoint and stop shadowing `filter`
### Tree org map
```
bench/
└── problems.py   [MODIFIED]
```
### List of changes
1. `Problem.entrypoint` is optional, and `render_prompt` falls back to the string `"the required entry point"` when it is absent (`problems.py:203`). The per-language ABI requires a named symbol the hidden tests import, so a problem without one is guaranteed to fail every model. Validate in `_load_one`: raise `ProblemFormatError` naming the directory when `entrypoint` is missing or blank.
2. Remove the `"the required entry point"` fallback from `render_prompt` once the loader guarantees the field — or keep it as a defensive branch with a comment explaining it is now unreachable via `load_problems`. State which you chose and why.
3. Rename the `filter` parameter of `load_problems` (it shadows the builtin) to `slug_filter`, updating the docstring. Accept the old name as a keyword alias **only** if a caller outside this file passes it positionally — check `bench/cli.py:139` before deciding, and if the call is positional, no alias is needed.
### Reason for changes
All 19 current problems set `entrypoint`, so item 1 is latent — but it fails in the most expensive way possible: every model scores zero on that problem and the leaderboard reads it as a hard problem rather than a broken one. Catching it at load time turns a silent scoring corruption into a startup error. Item 3 is a contained style fix in the same file.
### Done when
- A tmp problem directory whose `meta.yaml` omits `entrypoint` raises `ProblemFormatError` naming the directory; one with a blank string does too.
- All 19 existing problems still load: `python3 -c "from bench.problems import load_problems; ps=load_problems('problems'); print(len(ps)); assert all(p.entrypoint for p in ps)"` prints 19 and does not assert.
- `grep -n 'def load_problems' -A6 bench/problems.py` shows no parameter named `filter`.
- `python3 -m bench.cli --dry-run --filter parse` still selects problems (the CLI call site works).
- `git diff --name-only` lists `bench/problems.py` and nothing else.
### Depends on
none

## Task T8: Delete the dead `RunTarget.price_override`
### Tree org map
```
bench/
├── types.py    [MODIFIED]
└── config.py   [MODIFIED]
```
### List of changes
1. `RunTarget.price_override` is populated at `config.py:162` and read nowhere — the client builds its own `price_overrides` dict at `cli.py:113` from `ModelSpec`. Remove the field from `RunTarget` in `types.py` and stop passing it in `expand_targets`.
2. Before removing, confirm the field is genuinely unread: `grep -rn 'price_override' bench/ tests/` and verify every remaining hit is `ModelSpec.price_override` or the client's dict. If any consumer reads `RunTarget.price_override`, **stop and report** — the correct fix would then be to wire it up, not delete it.
3. Update `RunTarget`'s docstring, which currently claims the field "mirrors `ModelSpec` and is keyed by `model`" — a promise nothing keeps.
### Reason for changes
A populated-but-unread field is worse than an absent one: it reads as the mechanism by which per-model pricing reaches the runner, so the next person to touch pricing will wire against it and find their override silently ignored. `types.py` and `config.py` move together because the field's definition and its only writer live in the two files.
### Done when
- `grep -rn 'RunTarget' bench/ | grep price_override` returns nothing.
- `grep -rn 'price_override' bench/` returns only `ModelSpec`-related hits and the client's `price_overrides` dict.
- `RunTarget`'s docstring no longer references `price_override`.
- `pytest -q` passes — a `price_override` set in `models.yaml` still reaches the client (verify via `--dry-run` against a roster entry that has one).
- `git diff --name-only` lists exactly `bench/types.py` and `bench/config.py`.
### Depends on
none

## Task T9: Add Claude Opus 5 and Kimi K3 to the roster
### Tree org map
```
README.md            [MODIFIED]
config/
└── models.yaml      [MODIFIED]
```
### List of changes
1. Add **Claude Opus 5** as `anthropic/claude-opus-5` (verified present on OpenRouter). Pricing is $5 / $25 per 1M tokens — the same tier as Opus 4.8 — so follow the existing comment convention: `# Anthropic — Claude Opus 5  ($5 / $25 per M)`. Give it `efforts: [low, medium, high]` to match the other reasoning-capable flagships, and `price_override: null` so live pricing wins.
2. Add **Kimi K3** as `moonshotai/kimi-k3` (verified present on OpenRouter). **Do not invent a price** — check what OpenRouter reports and record the figure in the comment only if the live catalog returns one; if the model comes back unpriced, add a `price_override` and say in the comment that the number is a pinned estimate, not fetched pricing.
3. **Verify before committing to an effort sweep for Kimi K3.** It is reasoning-capable (it emits thinking blocks), but whether OpenRouter honors `reasoning.effort` for it is unverified. Run a single low-cost call at two different effort levels and compare completion-token counts; if the levels are indistinguishable, add the entry **without** `efforts` (a single effort-less target) and add a yaml comment recording that the sweep was tested and not honored — the same shape as the existing `gpt-5.6` tier note.
4. Note in the yaml that `anthropic/claude-opus-5-fast` also exists but is deliberately not rostered: fast mode is a different price tier ($10 / $25) and a serving-speed axis, not a capability axis — the same reasoning that keeps the 5.6 tiers off the effort sweep.
5. `README.md`: update the roster description and the target-count arithmetic. Adding Opus 5 with a three-level sweep adds 3 targets; Kimi K3 adds 1 or 3 depending on item 3. Re-run `--dry-run` and quote the number it actually prints for both the new target count and the new estimated cost — do not extrapolate from the old figure.
6. Confirm the new estimate against `DEFAULT_MAX_SPEND_USD` (150.0). If the roster now estimates above the cap, say so plainly in the README and flag it in your final message — **do not raise the cap**; that is the user's call.
7. Document T6's `--list-targets` and `--target` in the README, including a copy-pasteable **single-model smoke run** recipe combining them with the existing scoping flags, e.g. `--target "anthropic/claude-opus-5 (low)" --filter <slug> --k 1 --dry-run` to price it, then the same without `--dry-run`. State the cost distinction explicitly: `--models X` runs every effort level `X` configures; `--target` runs exactly one.
8. Correct the `--efforts` description while you are here if Phase 1 left anything stale: a non-empty `--efforts` applies to **every** selected model, which is why `--target` exists for single-target runs.
### Reason for changes
This is the feature request that motivated the phase. Item 7 is what makes T6 discoverable — a flag documented only in `--help` is a flag most users never find, and "benchmark just this one model" is the most common thing someone wants from a tool this expensive to run. Note that until T1 lands, both new models are subject to the prose-as-code misclassification, which will understate them if they explain before coding — so prefer landing T1 first even though nothing forces the ordering.
### Done when
- `python3 -c "from bench.config import load_model_specs; ids=[s.id for s in load_model_specs()]; print(ids)"` includes `anthropic/claude-opus-5` and `moonshotai/kimi-k3`.
- `python3 -m bench.cli --dry-run` runs clean and prints a target count and cost estimate; both figures appear verbatim in the README.
- Neither new entry shows as `unpriced` in the dry-run table, **or** the unpriced one carries a `price_override` with a comment saying the figure is pinned.
- The Kimi K3 effort decision is recorded as a yaml comment stating what was tested and what was observed.
- `grep -n 'claude-opus-5-fast' config/models.yaml` shows the deliberate-exclusion note.
- The README's smoke-run recipe is copy-pasteable and verified: run the `--dry-run` form exactly as written and confirm it prices one target.
- `grep -n 'list-targets\|--target' README.md` returns the new documentation.
- `git diff --name-only` lists exactly `README.md` and `config/models.yaml`.
### Depends on
T6

## Task T10: Regression guards for the two high-severity fixes
### Tree org map
```
tests/
├── test_extract.py     [MODIFIED]
└── test_openrouter.py  [MODIFIED]
```
### List of changes
1. `test_extract.py` — the T1 defect as a direct test: a fence-free prose reply containing an indented paragraph must return `None`. **This test fails on `main`**, which is the point; say so in a comment.
2. `test_extract.py` — the case T1 must not break: a fence-free reply that is genuinely bare Python (a `def` with an indented body, no prose) still extracts. Add the TypeScript, C#, and Bash equivalents so the tightened marker set is pinned per language.
3. `test_extract.py` — a truncated reply (prose + an unterminated ```` ``` ```` fence) returns `None` rather than the prose. This is the `finish_reason=length` shape that motivated the fix.
4. `test_openrouter.py` — a stubbed 401 from `/models` surfaces as `OpenRouterError` with `.status_code == 401`, and that status is in `FATAL_STATUS`. This is the T2 regression guard and it also fails on `main`.
5. `test_openrouter.py` — `_is_retryable` returns False for a 400 whose body text contains the word "retryable", proving the predicate no longer matches on message text.
6. `test_openrouter.py` — 429/500/502/503/504 remain retryable and 401/402/403 do not, as a parametrized table.
### Reason for changes
Items 1 and 4 are the only two findings in the review confirmed to change reported numbers; both are currently unguarded, and both fixes are the kind that a later refactor could quietly undo. Splitting from T11 by file lets the two test tasks run in parallel.
### Done when
- `pytest tests/test_extract.py tests/test_openrouter.py -q` passes.
- Items 1 and 4 are documented in comments as failing against the pre-fix behavior; state in your final message that you confirmed this by reasoning from the assertion.
- No network call is made by any test in either file — `grep -n 'httpx.AsyncClient\|api.openrouter' tests/test_openrouter.py` shows only stubs.
- `git diff --name-only` lists exactly `tests/test_extract.py` and `tests/test_openrouter.py`.
- No `bench/` source file is modified. If a test cannot pass without a source change, stop and report it.
### Depends on
T1, T2

## Task T11: First coverage for the sandbox and CLI surfaces
### Tree org map
```
tests/
├── test_sandbox.py   [NEW]
└── test_cli.py       [NEW]
```
### List of changes
1. `test_sandbox.py` — assert the full isolation flag set in `_docker_run_argv` by exact flag/value pair for all four languages: `--network none`, `--read-only`, `--cap-drop ALL`, `--security-opt no-new-privileges`, `--pids-limit 512`, and the `:ro` bind mount. These are the security posture of the whole harness and no test asserts them today.
2. `test_sandbox.py` — the T3 memory change: `--memory 1g` for C#, `--memory 256m` for the other three, and the invariant that each language's memory limit exceeds its `tmpfs_size`.
3. `test_sandbox.py` — a non-existent `image_tag` raises `SandboxError` (T3 item 3), with `_run`/`_image_exists` stubbed.
4. `test_sandbox.py` — `run_in_sandbox` timeout path returns `timed_out=True` rather than propagating `asyncio.TimeoutError`, with `_run` stubbed.
5. `test_cli.py` — the T6 validations: `--k 0`, `--max-spend 0`, and `--concurrency 0` each exit 2; a valid argument set does not. Drive `_build_parser` and `_amain` directly rather than shelling out.
6. `test_cli.py` — T6 target selection, the core of the single-model feature: `--target "<swept model> (low)"` resolves to exactly one target; a bare effort-less id resolves to one target whose label has **no** `(effort)` suffix; an unmatched label exits 2; `--target` with `--efforts` exits 2. Assert on the resolved `RunConfig.targets`, not on printed output.
7. `test_cli.py` — `--list-targets` prints every roster label and exits 0 without an API key. Point it at a tiny fixture `models.yaml` under `tmp_path` rather than the real roster, so the test doesn't break every time the roster changes.
8. Every test in both files must pass with the Docker daemon **stopped** and with no network. Stub `_run` and the HTTP client at the boundary.
### Reason for changes
`sandbox.py` and `cli.py` have no dedicated test file, and `_docker_run_argv` is the single most security-sensitive function in the repo — a silently dropped `--network none` would break no existing test. New files so they cannot collide with T10.
### Done when
- `pytest tests/test_sandbox.py tests/test_cli.py -q` passes **with Docker stopped** — that is the check that matters; run it with the daemon down.
- Each flag in item 1 has its own assertion, per language.
- `grep -n 'docker' tests/test_sandbox.py` shows no invocation that shells out; `_run` is stubbed in every test that would.
- `git diff --name-only` shows only the two new files; no existing file is modified.
### Depends on
T3, T6

---
## File ownership map
- `bench/extract.py` → T1
- `bench/openrouter.py` → T2
- `bench/sandbox.py` → T3
- `bench/runner.py` → T4
- `bench/report.py` → T5
- `bench/cli.py` → T6
- `bench/problems.py` → T7
- `bench/types.py` → T8
- `bench/config.py` → T8
- `README.md` → T9
- `config/models.yaml` → T9
- `tests/test_extract.py` → T10
- `tests/test_openrouter.py` → T10
- `tests/test_sandbox.py` → T11 [NEW]
- `tests/test_cli.py` → T11 [NEW]
- `bench/cost.py` → unowned, intentionally untouched (Phase 1 owns it; the review found nothing further)
- `tests/test_cost.py`, `tests/test_runner.py`, `tests/test_report.py`, `tests/test_variants.py` → unowned, intentionally untouched
- `problems/` → unowned, never edited (see Out of scope)

Verified: no file is touched by more than one task.

## Out of scope
- **Widening `VALID_EFFORTS` to include `xhigh` and `max`.** Claude Opus 5 supports both and is documented as performing best at `xhigh` for coding, so this phase benchmarks it below its intended setting. The change touches `parse_effort`, `target_label`, `_EFFORT_SECTION_ORDER`, and the HTML section grouping, and it re-labels every historical result — a phase of its own. Flagged in the Overview for your decision.
- **Raising `DEFAULT_MAX_SPEND_USD`.** T9 may push the roster estimate past the $150 cap; the task reports that, it does not fix it.
- **Any edit to `problems/`.** The problems are the measurement; changing one to make a test pass invalidates every historical result.
- **Weakening or removing any sandbox isolation flag.** T3 raises a memory limit and adds a preflight check — nothing else in `sandbox.py`'s security posture may move.
- **Carrying the effective `k` through to `ProblemResult`.** The honest fix for the pass@k clamp needs a `types.py` field and report plumbing; T4 documents the caveat and T5 exports the sample count instead. Deferred deliberately.
- **`bench/cost.py`**, adding `anthropic/claude-opus-5-fast` to the roster, new runtime dependencies, CI config, `pyproject.toml`, and reformatting of code no task owns.
- Committing, pushing, or opening a PR.

## Acceptance for the phase
- [ ] Full suite green: `pytest -q`, with strictly more tests than the pre-phase baseline (63 at the time of writing; Phase 1 adds more).
- [ ] Suite passes with the Docker daemon **stopped** — proves no new test took a daemon dependency.
- [ ] `git diff --name-only` is a subset of the File ownership map; `bench/cost.py` and `problems/` do **not** appear.
- [ ] A fence-free prose reply is bucketed as `no_code`, not `failed` — the confirmed defect this phase exists to fix.
- [ ] A 401 on the pricing fetch reaches `runner.py` with `status_code=401` and triggers the run-wide abort.
- [ ] `_docker_run_argv` still emits every isolation flag for all four languages, asserted per flag.
- [ ] `--k 0`, `--max-spend 0`, and `--concurrency 0` each exit non-zero instead of producing a silent empty run.
- [ ] **A single model can be benchmarked in one target**: `--list-targets` enumerates the roster, and `--target "<label>" --dry-run` prices exactly one row — including for an effort-less model, whose label gains no `(effort)` suffix.
- [ ] An unmatched `--target` label exits non-zero listing the valid labels, rather than running nothing and exiting 0.
- [ ] The README carries a copy-pasteable single-model smoke-run recipe, verified by running its `--dry-run` form.
- [ ] `python3 -m bench.cli --dry-run` runs clean and lists both `anthropic/claude-opus-5` and `moonshotai/kimi-k3` as targets.
- [ ] Every cost or target-count figure in `README.md` was reproduced from that dry-run, not carried over.
- [ ] `grep -rn 'price_override' bench/` shows no `RunTarget` hits.

## Suggested execution order
- Fully parallel, no dependencies: **T1, T2, T3, T4, T5, T6, T7, T8**
- Then: **T9** (needs T6 — it documents T6's new flags), **T10** (needs T1, T2), **T11** (needs T3, T6). All three are parallel with each other.

Critical path is T6 → T9/T11 and T1/T2 → T10; everything else can start immediately. T6 is now on the critical path for two downstream tasks, so start it early.

With the dev-handoff cap of 2 workers at a time, a reasonable wave order is **(T1, T6) → (T2, T3) → (T9, T10) → (T11, T4) → (T5, T7) → (T8)** — this starts both dependency chains in wave 1 and lets the independent fixes fill in behind them.

## Ready to hand off?
