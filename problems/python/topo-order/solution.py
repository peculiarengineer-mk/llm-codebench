import heapq


def topo_sort(n, edges):
    adj = {u: set() for u in range(n)}
    indeg = [0] * n
    for u, v in edges:
        if v not in adj[u]:
            adj[u].add(v)
            indeg[v] += 1

    heap = [u for u in range(n) if indeg[u] == 0]
    heapq.heapify(heap)

    order = []
    while heap:
        u = heapq.heappop(heap)
        order.append(u)
        for v in sorted(adj[u]):
            indeg[v] -= 1
            if indeg[v] == 0:
                heapq.heappush(heap, v)

    if len(order) != n:
        return []
    return order
