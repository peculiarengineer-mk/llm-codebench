"""Unit tests for bench.extract (T4)."""

from bench.extract import extract_code
from bench.types import Language


def test_tagged_python_block():
    resp = "Here you go:\n```python\ndef f():\n    return 1\n```\nDone."
    code = extract_code(resp, Language.python)
    assert code is not None
    assert "def f():" in code
    assert code.endswith("\n")
    assert "Here you go" not in code


def test_no_code_block_returns_none():
    assert extract_code("I cannot help with that.", Language.python) is None


def test_wrong_language_tag_falls_back_to_largest_block():
    resp = "```\ndef solve():\n    return 42\n```"
    code = extract_code(resp, Language.python)
    assert code is not None and "def solve()" in code


def test_multiple_blocks_picks_largest_tagged():
    resp = (
        "```python\nx = 1\n```\n"
        "and the real one:\n"
        "```python\ndef big():\n    total = 0\n    for i in range(10):\n"
        "        total += i\n    return total\n```"
    )
    code = extract_code(resp, Language.python)
    assert "def big()" in code
    assert code.strip() != "x = 1"


def test_typescript_aliases():
    resp = "```ts\nexport function twoSum() { return []; }\n```"
    code = extract_code(resp, Language.typescript)
    assert code is not None and "twoSum" in code


def test_csharp_tag():
    resp = "```csharp\nnamespace Grok;\npublic static class Solver {}\n```"
    code = extract_code(resp, Language.csharp)
    assert code is not None and "Solver" in code


def test_bash_tag():
    resp = "```bash\nword_count() {\n  echo 3\n}\n```"
    code = extract_code(resp, Language.bash)
    assert code is not None and "word_count" in code


def test_bash_sh_alias():
    resp = "Here:\n```sh\ngreet() { echo hi; }\n```\ndone"
    code = extract_code(resp, Language.bash)
    assert code is not None and "greet" in code
    assert "Here" not in code


def test_bash_fence_free_code():
    resp = "sum_col() {\n  local total=0\n  echo \"$total\"\n}"
    code = extract_code(resp, Language.bash)
    assert code is not None and "sum_col" in code


def test_fence_free_code_used_when_it_looks_like_code():
    resp = "def add(a, b):\n    return a + b"
    code = extract_code(resp, Language.python)
    assert code is not None and "def add" in code


def test_prose_only_returns_none():
    assert extract_code("The answer is forty two.", Language.python) is None


def test_empty_response():
    assert extract_code("", Language.python) is None
    assert extract_code("   \n  ", Language.python) is None
