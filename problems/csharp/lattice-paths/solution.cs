namespace Grok;

public static class Solver
{
    public static long CountPaths(int rows, int cols, int[][] blocked)
    {
        const long MOD = 1_000_000_007L;
        var block = new HashSet<(int, int)>();
        foreach (var b in blocked)
        {
            block.Add((b[0], b[1]));
        }

        var dp = new long[rows, cols];
        for (int r = 0; r < rows; r++)
        {
            for (int c = 0; c < cols; c++)
            {
                if (block.Contains((r, c)))
                {
                    dp[r, c] = 0;
                    continue;
                }
                if (r == 0 && c == 0)
                {
                    dp[r, c] = 1;
                    continue;
                }
                long total = 0;
                if (r > 0) total += dp[r - 1, c];
                if (c > 0) total += dp[r, c - 1];
                dp[r, c] = total % MOD;
            }
        }
        return dp[rows - 1, cols - 1];
    }
}
