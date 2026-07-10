# Deterministic topological order

You are given `n` nodes labelled `0` to `n - 1` and a list of directed
`edges`, where each edge `[u, v]` means node `u` must come **before** node `v`.

Implement `topo_sort(n, edges)` returning a topological ordering of all `n`
nodes as a list. If the graph contains a cycle (no valid ordering exists),
return an empty list `[]`.

To make the answer unique: whenever more than one node is ready to be placed
next (all of its prerequisites already placed), choose the **smallest-numbered**
such node.

Duplicate edges may appear and must be treated the same as a single edge.

```
topo_sort(2, [[0, 1]])                    ->  [0, 1]
topo_sort(3, [[0, 2], [1, 2]])            ->  [0, 1, 2]
topo_sort(2, [[0, 1], [1, 0]])            ->  []
topo_sort(3, [])                          ->  [0, 1, 2]
```
