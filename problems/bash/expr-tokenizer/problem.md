# Arithmetic expression tokenizer

Define a shell function `tokenize` that takes a single string containing a simple
arithmetic expression and echoes its tokens, **one per line**.

The valid tokens are:

- integer literals: one or more consecutive digits (`0`-`9`), kept together as a
  single multi-digit token;
- the operators `+`, `-`, `*`, `/`;
- the parentheses `(` and `)`.

Whitespace separates tokens but is not itself a token. On encountering any other
character, print nothing to stdout for the offending run and return a **non-zero**
exit status (an error message on stderr is allowed).

```
tokenize "12+3 * (4-5)"
```
produces
```
12
+
3
*
(
4
-
5
)
```

An empty string produces no output and succeeds.
