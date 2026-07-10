"""Turn a model's chat reply into runnable source code (T4).

The brittle text -> code step, isolated behind one pure function so it is easy
to unit-test. Never raises on unusable input: if no code can be recovered,
:func:`extract_code` returns ``None`` and the caller marks the attempt failed.

Strategy (in priority order):
  1. Fenced blocks tagged with the target language (```python / ```ts / ```cs
     and common aliases).
  2. Any untagged fenced block (```), largest first.
  3. If the whole reply looks like bare code (no fences at all), use it verbatim.
"""

from __future__ import annotations

import re

from bench.types import Language

# Language tag -> aliases that may appear after the opening triple backtick.
_LANG_ALIASES: dict[Language, tuple[str, ...]] = {
    Language.python: ("python", "python3", "py"),
    Language.typescript: ("typescript", "ts", "tsx", "javascript", "js"),
    Language.csharp: ("csharp", "cs", "c#", "dotnet"),
    Language.bash: ("bash", "sh", "shell", "shellscript"),
}

# Matches a fenced block, capturing the info-string (language tag) and body.
# Handles ``` and optional leading tilde-style not supported (backticks only).
_FENCE_RE = re.compile(
    r"```[ \t]*([^\n`]*)\r?\n(.*?)```",
    re.DOTALL,
)


def _iter_blocks(text: str) -> list[tuple[str, str]]:
    """Return ``(tag, body)`` pairs for every fenced block, in document order."""
    blocks: list[tuple[str, str]] = []
    for match in _FENCE_RE.finditer(text):
        tag = match.group(1).strip().lower()
        body = match.group(2)
        blocks.append((tag, body))
    return blocks


def extract_code(response: str, language: Language) -> str | None:
    """Extract the best code block for ``language`` from a model ``response``.

    Returns cleaned source (trailing whitespace stripped, trailing newline
    ensured) ready to hand to the sandbox, or ``None`` if nothing usable is
    found.
    """
    if not response or not response.strip():
        return None

    blocks = _iter_blocks(response)
    aliases = _LANG_ALIASES[language]

    # 1. Prefer fenced blocks explicitly tagged with the target language.
    #    The info-string may be just the tag ("python") or "python title=...".
    tagged = [
        body
        for tag, body in blocks
        if tag and (tag in aliases or tag.split()[0] in aliases)
    ]
    if tagged:
        # If several, the largest is most likely the full solution.
        return _clean(max(tagged, key=lambda b: len(b.strip())))

    # 2. Any fenced block, largest first (untagged or wrong-tag).
    if blocks:
        return _clean(max((body for _, body in blocks), key=lambda b: len(b.strip())))

    # 3. No fences at all: if the reply looks like code, use it whole.
    if _looks_like_code(response, language):
        return _clean(response)

    return None


def _clean(code: str) -> str | None:
    """Normalize an extracted block; return ``None`` if it is effectively empty."""
    cleaned = code.strip("\n").rstrip()
    if not cleaned.strip():
        return None
    return cleaned + "\n"


# Heuristic markers that a fence-free reply is source code rather than prose.
_CODE_MARKERS: dict[Language, tuple[str, ...]] = {
    Language.python: ("def ", "class ", "import ", "return ", "    "),
    Language.typescript: ("function ", "const ", "export ", "let ", "=>", "class "),
    Language.csharp: ("public ", "namespace ", "static ", "class ", "using ", "void "),
    Language.bash: ("#!/", "echo ", "function ", "() {", "local "),
}


def _looks_like_code(text: str, language: Language) -> bool:
    markers = _CODE_MARKERS[language]
    return any(marker in text for marker in markers)


__all__ = ["extract_code"]
