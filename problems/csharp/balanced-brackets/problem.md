# Balanced brackets

Inside `namespace Grok;`, expose a `public static class Solver` with the method:

```csharp
public static bool IsBalanced(string s)
```

Return `true` if every bracket in `s` is correctly matched and nested, and
`false` otherwise. Three bracket pairs must be considered: `()`, `[]`, and
`{}`. Any other character is ignored. The empty string is balanced.

A string is balanced when each opening bracket has a matching closing bracket of
the same kind, closed in the correct order (a closing bracket must match the
most recently opened, still-unclosed bracket).

```
IsBalanced("([]{})")     ->  true
IsBalanced("([)]")       ->  false
IsBalanced("(a[b]{c})")  ->  true
IsBalanced("(")          ->  false
IsBalanced("")           ->  true
```
