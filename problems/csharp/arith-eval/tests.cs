namespace Grok;

public class Program
{
    static int Main()
    {
        Check(Solver.Evaluate("2 + 3 * 4"), 14, "precedence");
        Check(Solver.Evaluate("(2 + 3) * 4"), 20, "paren");
        Check(Solver.Evaluate("10 / 3"), 3, "int div");
        Check(Solver.Evaluate("2 * -4"), -8, "unary minus");
        Check(Solver.Evaluate("100"), 100, "literal");
        Check(Solver.Evaluate("1 - 2 - 3"), -4, "left assoc sub");
        Check(Solver.Evaluate("2 + 3 - 4 * 5 / 2"), -5, "mixed");
        Check(Solver.Evaluate("  ( 1 + 2 ) * ( 3 + 4 ) "), 21, "spaces");
        Check(Solver.Evaluate("-7 / 2"), -3, "truncate toward zero");
        Check(Solver.Evaluate("2 * (3 + (4 - 1))"), 12, "nested paren");
        Check(Solver.Evaluate("--5"), 5, "double negative");
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
