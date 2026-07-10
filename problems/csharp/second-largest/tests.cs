namespace Grok;

public class Program
{
    static int Main()
    {
        Check(Solver.SecondLargest(new[] { 1, 2, 3 }), 2, "basic");
        Check(Solver.SecondLargest(new[] { 5, 5, 4 }), 4, "dup max");
        Check(Solver.SecondLargest(new[] { -1, -2, -3 }), -2, "negatives");
        Check(Solver.SecondLargest(new[] { 10, 10, 9, 9 }), 9, "dups");
        Console.WriteLine("ok");
        return 0;
    }

    static void Check(int got, int expected, string msg)
    {
        if (got != expected)
        {
            Console.Error.WriteLine($"FAIL {msg}: got {got}, expected {expected}");
            Environment.Exit(1);
        }
    }
}
