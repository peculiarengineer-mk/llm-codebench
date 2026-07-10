namespace Grok;

public static class Solver
{
    public static long Evaluate(string expr)
    {
        var parser = new Parser(expr);
        long value = parser.ParseExpr();
        return value;
    }

    private sealed class Parser
    {
        private readonly string _s;
        private int _pos;

        public Parser(string s)
        {
            _s = s;
            _pos = 0;
        }

        private void SkipSpaces()
        {
            while (_pos < _s.Length && _s[_pos] == ' ')
            {
                _pos++;
            }
        }

        private char Peek()
        {
            SkipSpaces();
            return _pos < _s.Length ? _s[_pos] : '\0';
        }

        // expr := term (('+' | '-') term)*
        public long ParseExpr()
        {
            long value = ParseTerm();
            while (true)
            {
                char c = Peek();
                if (c == '+')
                {
                    _pos++;
                    value += ParseTerm();
                }
                else if (c == '-')
                {
                    _pos++;
                    value -= ParseTerm();
                }
                else
                {
                    break;
                }
            }
            return value;
        }

        // term := factor (('*' | '/') factor)*
        private long ParseTerm()
        {
            long value = ParseFactor();
            while (true)
            {
                char c = Peek();
                if (c == '*')
                {
                    _pos++;
                    value *= ParseFactor();
                }
                else if (c == '/')
                {
                    _pos++;
                    value /= ParseFactor(); // C# long division truncates toward zero
                }
                else
                {
                    break;
                }
            }
            return value;
        }

        // factor := '-' factor | '(' expr ')' | number
        private long ParseFactor()
        {
            char c = Peek();
            if (c == '-')
            {
                _pos++;
                return -ParseFactor();
            }
            if (c == '(')
            {
                _pos++;
                long value = ParseExpr();
                Peek(); // skip spaces before ')'
                _pos++; // consume ')'
                return value;
            }
            return ParseNumber();
        }

        private long ParseNumber()
        {
            SkipSpaces();
            long value = 0;
            while (_pos < _s.Length && _s[_pos] >= '0' && _s[_pos] <= '9')
            {
                value = value * 10 + (_s[_pos] - '0');
                _pos++;
            }
            return value;
        }
    }
}
