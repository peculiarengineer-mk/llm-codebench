from solution import topo_sort


def test_simple_chain():
    assert topo_sort(2, [[0, 1]]) == [0, 1]


def test_smallest_first():
    assert topo_sort(3, [[0, 2], [1, 2]]) == [0, 1, 2]


def test_cycle_returns_empty():
    assert topo_sort(2, [[0, 1], [1, 0]]) == []


def test_no_edges():
    assert topo_sort(3, []) == [0, 1, 2]


def test_tie_break_prefers_small():
    # 2 must precede 0; among ready nodes the smallest is chosen.
    assert topo_sort(3, [[2, 0]]) == [1, 2, 0]


def test_duplicate_edges():
    assert topo_sort(3, [[0, 1], [0, 1], [1, 2]]) == [0, 1, 2]


def test_larger_dag():
    edges = [[0, 1], [0, 2], [1, 3], [2, 3], [3, 4]]
    assert topo_sort(5, edges) == [0, 1, 2, 3, 4]


def test_self_loop_is_cycle():
    assert topo_sort(1, [[0, 0]]) == []


def test_single_node():
    assert topo_sort(1, []) == [0]
