from solution import min_intervals_to_cover


def test_basic():
    assert min_intervals_to_cover([[0, 3], [1, 4], [3, 5]], 0, 5) == 2


def test_impossible_gap():
    assert min_intervals_to_cover([[0, 1], [2, 3]], 0, 3) == -1


def test_single_covers():
    assert min_intervals_to_cover([[0, 10]], 2, 8) == 1


def test_empty_span():
    assert min_intervals_to_cover([[0, 1]], 5, 5) == 0


def test_no_intervals():
    assert min_intervals_to_cover([], 0, 1) == -1


def test_choose_fewer():
    assert min_intervals_to_cover([[0, 1], [1, 2], [0, 2], [2, 3]], 0, 3) == 2
