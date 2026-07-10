import { lisLength } from "./solution";

function assertEq(got: unknown, expected: unknown, msg: string): void {
  const a = JSON.stringify(got);
  const b = JSON.stringify(expected);
  if (a !== b) {
    console.error(`FAIL ${msg}: got ${a}, expected ${b}`);
    process.exit(1);
  }
}

assertEq(lisLength([10, 9, 2, 5, 3, 7, 101, 18]), 4, "classic");
assertEq(lisLength([0, 1, 0, 3, 2, 3]), 4, "with dips");
assertEq(lisLength([7, 7, 7, 7]), 1, "all equal (strict)");
assertEq(lisLength([]), 0, "empty");
assertEq(lisLength([1]), 1, "single");
assertEq(lisLength([5, 4, 3, 2, 1]), 1, "decreasing");
assertEq(lisLength([1, 2, 3, 4, 5]), 5, "already increasing");
assertEq(lisLength([-2, -1, 0, -3, 5]), 4, "negatives");

// Performance: an O(n^2) approach should time out here; O(n log n) is instant.
const big: number[] = [];
for (let i = 0; i < 200000; i++) {
  big.push((i * 48271) % 100003);
}
const r = lisLength(big);
if (r < 100 || r > 100003) {
  console.error(`FAIL perf-range: got ${r}`);
  process.exit(1);
}

console.log("ok");
