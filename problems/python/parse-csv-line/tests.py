from solution import parse_csv_line


def test_plain():
    assert parse_csv_line("a,b,c") == ["a", "b", "c"]


def test_quoted_comma():
    assert parse_csv_line('"a,b",c') == ["a,b", "c"]


def test_escaped_quotes():
    assert parse_csv_line('"she said ""hi""",ok') == ['she said "hi"', "ok"]


def test_empty_fields():
    assert parse_csv_line("a,,c") == ["a", "", "c"]


def test_empty_line():
    assert parse_csv_line("") == [""]


def test_trailing_comma():
    assert parse_csv_line("a,b,") == ["a", "b", ""]


def test_whitespace_preserved():
    assert parse_csv_line("  a , b ") == ["  a ", " b "]


def test_only_quoted():
    assert parse_csv_line('""') == [""]


def test_quoted_then_empty():
    assert parse_csv_line('"x",') == ["x", ""]
