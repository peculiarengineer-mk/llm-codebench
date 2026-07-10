from solution import compress_ranges


def test_example():
    assert compress_ranges([1, 2, 3, 5, 7, 8]) == ["1-3", "5", "7-8"]


def test_single():
    assert compress_ranges([4]) == ["4"]


def test_empty():
    assert compress_ranges([]) == []


def test_all_consecutive():
    assert compress_ranges([10, 11, 12, 13]) == ["10-13"]


def test_none_consecutive():
    assert compress_ranges([1, 3, 5]) == ["1", "3", "5"]


def test_negatives():
    assert compress_ranges([-3, -2, -1, 2]) == ["-3--1", "2"]
