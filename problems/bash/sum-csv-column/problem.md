# Sum a CSV column

Define a shell function `sum_column` that takes two arguments:

1. a multi-line CSV string (comma-separated integer fields, one row per line), and
2. a 0-based column index.

It echoes the integer sum of that column across all rows.

```
sum_column $'1,2,3\n4,5,6' 0   ->  5     # 1 + 4
sum_column $'1,2,3\n4,5,6' 2   ->  9     # 3 + 6
sum_column '' 0                 ->  0
```

You may assume every non-empty row has enough columns. An empty input sums to 0.
Values may be negative.
