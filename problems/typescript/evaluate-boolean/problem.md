# Evaluate a boolean expression

Provide a named export `evaluateBoolean(expr: string): boolean` that evaluates a
boolean expression string and returns its value.

The grammar uses the literals `true` and `false`, the operators `not`, `and`,
`or`, and parentheses `(` `)`. Tokens are separated by spaces. Precedence, from
highest to lowest, is: `not`, then `and`, then `or`. Parentheses override
precedence. `and`/`or` are left-associative.

```
evaluateBoolean("true and false")             ->  false
evaluateBoolean("not true")                   ->  false
evaluateBoolean("true and not false")         ->  true
evaluateBoolean("false or true and false")    ->  false
evaluateBoolean("(false or true) and true")   ->  true
```
