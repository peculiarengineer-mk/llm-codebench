import { maxNonOverlapping } from "./solution";

function assertEq(got: unknown, expected: unknown, msg: string): void {
  const a = JSON.stringify(got);
  const b = JSON.stringify(expected);
  if (a !== b) {
    console.error(`FAIL ${msg}: got ${a}, expected ${b}`);
    process.exit(1);
  }
}

assertEq(maxNonOverlapping([[1, 3], [2, 4], [3, 5]]), 2, "overlap chain");
assertEq(maxNonOverlapping([[1, 2], [2, 3], [3, 4]]), 3, "touching allowed");
assertEq(maxNonOverlapping([[1, 10], [2, 3], [3, 4]]), 2, "drop the long one");
assertEq(maxNonOverlapping([]), 0, "empty");
assertEq(maxNonOverlapping([[5, 6]]), 1, "single");
assertEq(maxNonOverlapping([[1, 4], [1, 4], [1, 4]]), 1, "identical");
assertEq(
  maxNonOverlapping([[3, 4], [0, 2], [1, 3], [2, 5], [4, 6]]),
  3,
  "unsorted mix",
);
assertEq(maxNonOverlapping([[0, 1], [1, 2], [0, 2]]), 2, "prefer short ends");
console.log("ok");
