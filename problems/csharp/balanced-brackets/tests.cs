namespace Grok;

public class Program
{
    static int Main()
    {
        Check(Solver.IsBalanced("([]{})"), true, "nested ok");
        Check(Solver.IsBalanced("([)]"), false, "crossed");
        Check(Solver.IsBalanced("(a[b]{c})"), true, "with text");
        Check(Solver.IsBalanced("("), false, "unclosed");
        Check(Solver.IsBalanced(""), true, "empty");
        Check(Solver.IsBalanced(")("), false, "wrong order");
        Check(Solver.IsBalanced("abc"), true, "no brackets");
        Check(Solver.IsBalanced("{[()()]}"), true, "deep nesting");
        Check(Solver.IsBalanced("]"), false, "lone close");
        Console.WriteLine("ok");
        return 0;
    }

    static void Check(bool got, bool expected, string msg)
    {
        if (got != expected)
        {
            Console.Error.WriteLine($"FAIL {msg}: got {got}, expected {expected}");
            Environment.Exit(1);
        }
    }
}
