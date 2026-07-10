# Integer arithmetic evaluator

Inside `namespace Grok;`, expose a `public static class Solver` with the method:

```csharp
public static long Evaluate(string expr)
```

Evaluate an arithmetic expression string and return its integer value. The
grammar supports:

- Non-negative integer literals (one or more digits).
- Binary operators `+`, `-`, `*`, `/` with the usual precedence (`*` and `/`
  bind tighter than `+` and `-`), all left-associative.
- A unary minus, e.g. `-3` or `2 * -4`.
- Parentheses `(` and `)` to override precedence.
- Arbitrary spaces between tokens, which are ignored.

Division is **integer division that truncates toward zero** (so `7 / 2 == 3`
and `-7 / 2 == -3`). You may assume the expression is well-formed and never
divides by zero.

```
Evaluate("2 + 3 * 4")       ->  14
Evaluate("(2 + 3) * 4")     ->  20
Evaluate("10 / 3")          ->  3
Evaluate("2 * -4")          ->  -8
Evaluate("100")             ->  100
```
