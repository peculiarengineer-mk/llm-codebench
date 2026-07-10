# Longest strictly increasing subsequence

Provide a named export `lisLength(nums: number[]): number`.

A subsequence is obtained by deleting zero or more elements without reordering
the rest. Return the length of the longest **strictly increasing** subsequence
of `nums` (each element strictly greater than the previous). For an empty input
return `0`.

Your solution must run in `O(n log n)` time (patience-sorting with binary
search); an `O(n^2)` approach may time out on the hidden tests.

```
lisLength([10, 9, 2, 5, 3, 7, 101, 18])  ->  4      // e.g. 2, 3, 7, 18
lisLength([0, 1, 0, 3, 2, 3])            ->  4      // 0, 1, 2, 3
lisLength([7, 7, 7, 7])                  ->  1
lisLength([])                            ->  0
```
