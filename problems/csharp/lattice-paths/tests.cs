namespace Grok;

public class Program
{
    static int Main()
    {
        Check(Solver.CountPaths(2, 2, System.Array.Empty<int[]>()), 2, "2x2");
        Check(Solver.CountPaths(3, 3, System.Array.Empty<int[]>()), 6, "3x3");
        Check(Solver.CountPaths(3, 3, new[] { new[] { 1, 1 } }), 2, "blocked center");
        Check(Solver.CountPaths(1, 5, System.Array.Empty<int[]>()), 1, "single row");
        Check(Solver.CountPaths(2, 2, new[] { new[] { 0, 1 }, new[] { 1, 0 } }), 0, "sealed");
        Console.WriteLine("ok");
        return 0;
    }

    static void Check(long got, long expected, string msg)
    {
        if (got != expected)
        {
            Console.Error.WriteLine($"FAIL {msg}: got {got}, expected {expected}");
            Environment.Exit(1);
        }
    }
}
