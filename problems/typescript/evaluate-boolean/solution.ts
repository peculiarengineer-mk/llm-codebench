export function evaluateBoolean(expr: string): boolean {
  const tokens = expr.match(/\(|\)|[A-Za-z]+/g) ?? [];
  let pos = 0;
  const peek = (): string | undefined => tokens[pos];
  const next = (): string | undefined => tokens[pos++];

  function parseOr(): boolean {
    let v = parseAnd();
    while (peek() === "or") {
      next();
      const r = parseAnd();
      v = v || r;
    }
    return v;
  }

  function parseAnd(): boolean {
    let v = parseNot();
    while (peek() === "and") {
      next();
      const r = parseNot();
      v = v && r;
    }
    return v;
  }

  function parseNot(): boolean {
    if (peek() === "not") {
      next();
      return !parseNot();
    }
    return parseAtom();
  }

  function parseAtom(): boolean {
    const t = next();
    if (t === "(") {
      const v = parseOr();
      next(); // consume ")"
      return v;
    }
    if (t === "true") return true;
    if (t === "false") return false;
    throw new Error(`unexpected token: ${t}`);
  }

  return parseOr();
}
