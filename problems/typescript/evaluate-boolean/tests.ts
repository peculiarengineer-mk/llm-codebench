import { evaluateBoolean } from "./solution";

function assertEq(got: unknown, expected: unknown, msg: string): void {
  const a = JSON.stringify(got);
  const b = JSON.stringify(expected);
  if (a !== b) {
    console.error(`FAIL ${msg}: got ${a}, expected ${b}`);
    process.exit(1);
  }
}

assertEq(evaluateBoolean("true and false"), false, "and");
assertEq(evaluateBoolean("true or false"), true, "or");
assertEq(evaluateBoolean("not true"), false, "not");
assertEq(evaluateBoolean("not (true and false)"), true, "paren");
assertEq(evaluateBoolean("true and not false"), true, "precedence not");
assertEq(evaluateBoolean("false or true and false"), false, "and binds tighter");
assertEq(evaluateBoolean("(false or true) and true"), true, "paren override");
assertEq(evaluateBoolean("not not true"), true, "double not");
console.log("ok");
