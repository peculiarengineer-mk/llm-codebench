"""Problem-suite schema and loader (T2).

Single responsibility: turn the on-disk ``problems/`` tree into validated
:class:`~bench.types.Problem` value objects. Nothing here executes code or talks
to the network; it is pure filesystem -> data.

On-disk format
--------------
Each problem lives in its own directory::

    problems/<lang>/<slug>/
        problem.md        # the prompt shown to the model (required)
        solution.<ext>    # reference solution, NEVER shown to the model (required)
        tests.<ext>       # hidden tests (required)
        meta.yaml         # metadata (required)

``<lang>`` is one of ``python`` / ``csharp`` / ``typescript`` / ``bash`` and
``<ext>`` is that language's source extension (``py`` / ``cs`` / ``ts`` /
``sh``). ``meta.yaml`` keys::

    difficulty: easy | medium | hard      # required
    entrypoint: <symbol name>             # optional but recommended (see ABI)
    timeout: <float seconds>              # optional per-problem wall-clock override
    image_tag: <docker image>             # optional per-problem sandbox image

The ``entrypoint`` / filename / invocation contract each language obeys is
documented authoritatively in :mod:`bench.types`.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from bench.types import Language, Problem

# Source extension per language (used for solution.<ext> / tests.<ext> on disk).
LANG_EXT: dict[Language, str] = {
    Language.python: "py",
    Language.csharp: "cs",
    Language.typescript: "ts",
    Language.bash: "sh",
}

_VALID_DIFFICULTY = {"easy", "medium", "hard"}


class ProblemFormatError(ValueError):
    """Raised when a problem directory is malformed. Names the offending dir."""


def _estimate_tokens(text: str) -> int:
    """Cheap chars/4 token heuristic for dry-run costing (no tokenizer needed)."""
    return max(1, len(text) // 4)


def _load_one(problem_dir: Path, language: Language) -> Problem:
    """Parse a single ``problems/<lang>/<slug>/`` directory into a Problem."""
    slug = problem_dir.name
    ext = LANG_EXT[language]

    prompt_path = problem_dir / "problem.md"
    solution_path = problem_dir / f"solution.{ext}"
    tests_path = problem_dir / f"tests.{ext}"
    meta_path = problem_dir / "meta.yaml"

    for required in (prompt_path, solution_path, tests_path, meta_path):
        if not required.is_file():
            raise ProblemFormatError(
                f"{problem_dir}: missing required file '{required.name}'"
            )

    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    if not isinstance(meta, dict):
        raise ProblemFormatError(f"{meta_path}: expected a mapping, got {type(meta).__name__}")

    difficulty = meta.get("difficulty")
    if difficulty not in _VALID_DIFFICULTY:
        raise ProblemFormatError(
            f"{meta_path}: 'difficulty' must be one of {sorted(_VALID_DIFFICULTY)}, "
            f"got {difficulty!r}"
        )

    timeout_override = meta.get("timeout")
    if timeout_override is not None:
        try:
            timeout_override = float(timeout_override)
        except (TypeError, ValueError):
            raise ProblemFormatError(
                f"{meta_path}: 'timeout' must be a number, got {timeout_override!r}"
            )

    prompt = prompt_path.read_text(encoding="utf-8")

    return Problem(
        slug=slug,
        language=language,
        prompt=prompt,
        tests=tests_path.read_text(encoding="utf-8"),
        solution=solution_path.read_text(encoding="utf-8"),
        difficulty=difficulty,
        timeout_override=timeout_override,
        entrypoint=meta.get("entrypoint"),
        image_tag=meta.get("image_tag"),
        prompt_token_estimate=_estimate_tokens(prompt),
    )


def load_problems(
    root: str | Path = "problems",
    langs: list[Language] | list[str] | None = None,
    filter: str | None = None,
) -> list[Problem]:
    """Discover and load every problem under ``root``.

    Parameters
    ----------
    root:
        The ``problems/`` tree root.
    langs:
        Restrict to these languages (``Language`` members or their string
        values). ``None`` loads all four.
    filter:
        If given, keep only problems whose slug contains this substring.

    Returns problems sorted by ``(language, difficulty, slug)`` for stable runs.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise ProblemFormatError(f"problems root not found: {root_path}")

    wanted: set[Language] | None
    if langs is None:
        wanted = None
    else:
        wanted = {lang if isinstance(lang, Language) else Language(lang) for lang in langs}

    problems: list[Problem] = []
    for language in Language:
        if wanted is not None and language not in wanted:
            continue
        lang_dir = root_path / language.value
        if not lang_dir.is_dir():
            continue
        for problem_dir in sorted(p for p in lang_dir.iterdir() if p.is_dir()):
            if filter and filter not in problem_dir.name:
                continue
            problems.append(_load_one(problem_dir, language))

    _difficulty_rank = {"easy": 0, "medium": 1, "hard": 2}
    problems.sort(
        key=lambda p: (p.language.value, _difficulty_rank[p.difficulty], p.slug)
    )
    return problems


# Instruction wrappers for the two prompt styles. "strict" spells out the exact
# invocation ABI so weaker models still emit runnable code; "loose" trusts the
# model and adds minimal framing.
_STRICT_HEADER = {
    Language.python: (
        "Write a complete Python 3 solution. Define the function or class named "
        "`{entry}` at module top level. Return ONLY a single ```python fenced code "
        "block containing the full solution — no explanation. Do not include tests."
    ),
    Language.typescript: (
        "Write a complete TypeScript solution. Provide a NAMED export `{entry}` "
        "(e.g. `export function {entry}(...) {{ ... }}`). Return ONLY a single "
        "```typescript fenced code block with the full solution — no explanation, "
        "no tests."
    ),
    Language.csharp: (
        "Write a complete C# solution inside `namespace Grok;`. Expose a `public` "
        "type/method named `{entry}`. Return ONLY a single ```csharp fenced code "
        "block with the full solution — no explanation, no `Main`, no tests."
    ),
    Language.bash: (
        "Write a complete Bash solution. Define a shell function named `{entry}` "
        "that echoes its result to stdout (so callers can capture it with "
        "`$({entry} ...)`). Return ONLY a single ```bash fenced code block with the "
        "full solution — no explanation, no tests, no top-level invocation."
    ),
}


def render_prompt(problem: Problem, prompt_style: str = "strict") -> str:
    """Wrap a problem's raw prompt with per-style, per-language instructions.

    ``strict`` prepends an explicit instruction spelling out the invocation ABI
    (entry-point name, single fenced block, no tests) so the extractor in T4 can
    reliably recover runnable code. ``loose`` adds only light framing and trusts
    the model to format its own answer.
    """
    if prompt_style == "loose":
        return (
            f"{problem.prompt.rstrip()}\n\n"
            "Respond with your solution as a single fenced code block."
        )
    if prompt_style != "strict":
        raise ValueError(f"prompt_style must be 'strict' or 'loose', got {prompt_style!r}")

    entry = problem.entrypoint or "the required entry point"
    header = _STRICT_HEADER[problem.language].format(entry=entry)
    return f"{header}\n\n---\n\n{problem.prompt.rstrip()}\n"


__all__ = ["load_problems", "render_prompt", "LANG_EXT", "ProblemFormatError"]
