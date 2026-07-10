def min_intervals_to_cover(intervals, start, end):
    if start >= end:
        return 0
    intervals = sorted(intervals)
    n = len(intervals)
    count = 0
    i = 0
    cur = start
    while cur < end:
        best = cur
        while i < n and intervals[i][0] <= cur:
            best = max(best, intervals[i][1])
            i += 1
        if best == cur:
            return -1
        count += 1
        cur = best
    return count
