namespace Grok;

public static class Solver
{
    public static bool IsBalanced(string s)
    {
        var stack = new Stack<char>();
        foreach (var ch in s)
        {
            if (ch == '(' || ch == '[' || ch == '{')
            {
                stack.Push(ch);
            }
            else if (ch == ')' || ch == ']' || ch == '}')
            {
                if (stack.Count == 0) return false;
                char open = stack.Pop();
                if ((ch == ')' && open != '(') ||
                    (ch == ']' && open != '[') ||
                    (ch == '}' && open != '{'))
                {
                    return false;
                }
            }
        }
        return stack.Count == 0;
    }
}
