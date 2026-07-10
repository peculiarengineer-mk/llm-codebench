# Compare semantic versions

Provide a named export `compareSemver(a: string, b: string): number` comparing
two dotted version strings of the form `"MAJOR.MINOR.PATCH"` (all non-negative
integers).

Return `-1` if `a` sorts before `b`, `1` if after, and `0` if equal. Each
component is compared **numerically**, not lexically (so `1.10.0` is greater
than `1.9.0`).

```
compareSemver("1.0.0", "1.0.1")   ->  -1
compareSemver("2.0.0", "1.9.9")   ->   1
compareSemver("1.10.0", "1.9.0")  ->   1
compareSemver("1.2.3", "1.2.3")   ->   0
```
