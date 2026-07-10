# Compress ranges

You are given a list `nums` of integers sorted in strictly ascending order (no
duplicates). Implement `compress_ranges(nums)` that collapses runs of
consecutive integers into `"start-end"` strings and leaves isolated integers as
their own `"n"` string.

```
compress_ranges([1, 2, 3, 5, 7, 8])  ->  ["1-3", "5", "7-8"]
compress_ranges([4])                 ->  ["4"]
compress_ranges([])                  ->  []
```

Negative numbers are allowed (e.g. `[-3, -2, -1]` compresses to `"-3--1"`).
