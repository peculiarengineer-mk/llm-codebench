import { compareSemver } from "./solution";

function assertEq(got: unknown, expected: unknown, msg: string): void {
  const a = JSON.stringify(got);
  const b = JSON.stringify(expected);
  if (a !== b) {
    console.error(`FAIL ${msg}: got ${a}, expected ${b}`);
    process.exit(1);
  }
}

assertEq(compareSemver("1.0.0", "1.0.1"), -1, "patch lower");
assertEq(compareSemver("2.0.0", "1.9.9"), 1, "major higher");
assertEq(compareSemver("1.2.3", "1.2.3"), 0, "equal");
assertEq(compareSemver("1.10.0", "1.9.0"), 1, "numeric not lexical");
assertEq(compareSemver("0.0.1", "0.1.0"), -1, "minor beats patch");
console.log("ok");
