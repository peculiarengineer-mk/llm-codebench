# Minimum intervals to cover a span

You are given a list of closed `intervals`, each `[a, b]` meaning the interval
covers every point from `a` to `b`, plus a target span `[start, end]`.

Implement `min_intervals_to_cover(intervals, start, end)` returning the
**minimum number of intervals** needed so that every point in `[start, end]` is
covered by at least one chosen interval. Return `-1` if the span cannot be fully
covered. If `start >= end` the span is empty and the answer is `0`.

Intervals may overlap and are not sorted.

```
min_intervals_to_cover([[0, 3], [1, 4], [3, 5]], 0, 5)  ->  2
min_intervals_to_cover([[0, 1], [2, 3]], 0, 3)          ->  -1
```
