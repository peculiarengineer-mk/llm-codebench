export function lisLength(nums: number[]): number {
  // tails[i] = smallest possible tail value of an increasing subsequence
  // of length i + 1 seen so far. tails is kept strictly increasing.
  const tails: number[] = [];
  for (const x of nums) {
    // find leftmost index with tails[idx] >= x (strictly increasing => >=)
    let lo = 0;
    let hi = tails.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (tails[mid] < x) {
        lo = mid + 1;
      } else {
        hi = mid;
      }
    }
    if (lo === tails.length) {
      tails.push(x);
    } else {
      tails[lo] = x;
    }
  }
  return tails.length;
}
