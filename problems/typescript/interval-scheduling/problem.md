# Maximum non-overlapping intervals

Provide a named export
`maxNonOverlapping(intervals: number[][]): number`.

Each interval is `[start, end]` with `start < end` and represents the
half-open span `[start, end)`. Two intervals **overlap** if their spans share
any interior point; intervals that merely touch at an endpoint (one ends exactly
where the next begins) do **not** overlap and may both be selected.

Return the size of the largest set of intervals you can select such that no two
selected intervals overlap. The input is not sorted and may be empty.

```
maxNonOverlapping([[1, 3], [2, 4], [3, 5]])   ->  2
maxNonOverlapping([[1, 2], [2, 3], [3, 4]])   ->  3
maxNonOverlapping([[1, 10], [2, 3], [3, 4]])  ->  2
maxNonOverlapping([])                         ->  0
```
