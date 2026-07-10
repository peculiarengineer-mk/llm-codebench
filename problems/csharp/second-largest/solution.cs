namespace Grok;

public static class Solver
{
    public static int SecondLargest(int[] xs)
    {
        var distinct = xs.Distinct().OrderByDescending(x => x).ToArray();
        return distinct[1];
    }
}
