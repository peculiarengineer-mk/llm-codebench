# Zigzag merge

Implement `zigzag_merge(a, b)` that interleaves two lists.

Take one element from `a`, then one from `b`, then the next from `a`, and so on,
alternating. When one list runs out, append the remaining elements of the other
list in order.

```
zigzag_merge([1, 3, 5], [2, 4, 6])  ->  [1, 2, 3, 4, 5, 6]
zigzag_merge([1, 2, 3, 4], [9])     ->  [1, 9, 2, 3, 4]
```

Either list may be empty.
