# Parse a single CSV line

Implement `parse_csv_line(line)` that splits one line of CSV text into its list
of field strings.

Rules:

- Fields are separated by commas.
- A field may be wrapped in double quotes. A quoted field can contain commas
  (they do not split the field) and can contain a literal double quote, written
  as two consecutive double quotes (`""`).
- The surrounding quotes of a quoted field are not part of the field value.
- Unquoted fields are taken literally; any surrounding whitespace is preserved.
- An empty input string yields a single empty field: `[""]`.

You may assume the line is well-formed: a quoted field, if present, starts right
after a comma (or at the beginning) and its closing quote is immediately
followed by a comma or the end of the line.

```
parse_csv_line("a,b,c")               ->  ["a", "b", "c"]
parse_csv_line('"a,b",c')             ->  ["a,b", "c"]
parse_csv_line('"she said ""hi""",ok') ->  ['she said "hi"', "ok"]
parse_csv_line("a,,c")                ->  ["a", "", "c"]
```
