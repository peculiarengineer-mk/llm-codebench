# Block sums

Inside `namespace Grok;`, expose a `public static class Solver` with the method:

```csharp
public static int[] BlockSums(int[] xs, int k)
```

Split `xs` into consecutive, non-overlapping blocks of `k` elements and return
the sum of each block. If the final block has fewer than `k` elements, sum
whatever remains. You may assume `k >= 1`.

```
BlockSums([1, 2, 3, 4, 5, 6], 2)  ->  [3, 7, 11]
BlockSums([1, 2, 3, 4, 5], 2)     ->  [3, 7, 5]
BlockSums([1, 2, 3], 5)           ->  [6]
```
