# Lattice paths with obstacles

Inside `namespace Grok;`, expose a `public static class Solver` with the method:

```csharp
public static long CountPaths(int rows, int cols, int[][] blocked)
```

Count the number of distinct paths from the top-left cell `(0, 0)` to the
bottom-right cell `(rows - 1, cols - 1)` on a grid, moving only **right** or
**down** one cell at a time. Cells listed in `blocked` (each `[row, col]`) may
not be entered. Return the count **modulo 1_000_000_007**. If the start or end
cell is blocked, the answer is `0`.

```
CountPaths(2, 2, [])              ->  2
CountPaths(3, 3, [])              ->  6
CountPaths(3, 3, [[1, 1]])        ->  2
CountPaths(2, 2, [[0, 1], [1, 0]]) -> 0
```
