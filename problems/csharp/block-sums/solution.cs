namespace Grok;

public static class Solver
{
    public static int[] BlockSums(int[] xs, int k)
    {
        var result = new List<int>();
        for (int i = 0; i < xs.Length; i += k)
        {
            int sum = 0;
            for (int j = i; j < i + k && j < xs.Length; j++)
            {
                sum += xs[j];
            }
            result.Add(sum);
        }
        return result.ToArray();
    }
}
