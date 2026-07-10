from solution import zigzag_merge


def test_equal_length():
    assert zigzag_merge([1, 3, 5], [2, 4, 6]) == [1, 2, 3, 4, 5, 6]


def test_a_longer():
    assert zigzag_merge([1, 2, 3, 4], [9]) == [1, 9, 2, 3, 4]


def test_b_longer():
    assert zigzag_merge([0], [7, 8, 9]) == [0, 7, 8, 9]


def test_both_empty():
    assert zigzag_merge([], []) == []


def test_one_empty():
    assert zigzag_merge([], [1, 2]) == [1, 2]
    assert zigzag_merge([1, 2], []) == [1, 2]
