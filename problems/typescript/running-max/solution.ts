export function runningMax(nums: number[]): number[] {
  const out: number[] = [];
  let m = -Infinity;
  for (const n of nums) {
    m = Math.max(m, n);
    out.push(m);
  }
  return out;
}
