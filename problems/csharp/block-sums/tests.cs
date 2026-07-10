namespace Grok;

public class Program
{
    static int Main()
    {
        CheckArr(Solver.BlockSums(new[] { 1, 2, 3, 4, 5, 6 }, 2), new[] { 3, 7, 11 }, "even");
        CheckArr(Solver.BlockSums(new[] { 1, 2, 3, 4, 5 }, 2), new[] { 3, 7, 5 }, "partial last");
        CheckArr(Solver.BlockSums(new[] { 1, 2, 3 }, 5), new[] { 6 }, "k larger than len");
        CheckArr(Solver.BlockSums(Array.Empty<int>(), 3), Array.Empty<int>(), "empty");
        CheckArr(Solver.BlockSums(new[] { 4, 4, 4, 4 }, 1), new[] { 4, 4, 4, 4 }, "k=1");
        Console.WriteLine("ok");
        return 0;
    }

    static void CheckArr(int[] got, int[] expected, string msg)
    {
        if (!got.SequenceEqual(expected))
        {
            Console.Error.WriteLine(
                $"FAIL {msg}: got [{string.Join(",", got)}], expected [{string.Join(",", expected)}]");
            Environment.Exit(1);
        }
    }
}
