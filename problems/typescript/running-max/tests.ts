import { runningMax } from "./solution";

function assertEq(got: unknown, expected: unknown, msg: string): void {
  const a = JSON.stringify(got);
  const b = JSON.stringify(expected);
  if (a !== b) {
    console.error(`FAIL ${msg}: got ${a}, expected ${b}`);
    process.exit(1);
  }
}

assertEq(runningMax([1, 3, 2, 5, 4]), [1, 3, 3, 5, 5], "basic");
assertEq(runningMax([]), [], "empty");
assertEq(runningMax([-1, -3, -2]), [-1, -1, -1], "negatives");
assertEq(runningMax([7]), [7], "single");
console.log("ok");
