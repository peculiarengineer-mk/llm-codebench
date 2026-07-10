"""Unit tests for the pass@k estimator (T6)."""

import pytest

from bench.runner import pass_at_k


def test_all_pass_at_k1():
    # n=3, c=3, k=1 -> every sample correct -> 1.0
    assert pass_at_k(3, 3, 1) == pytest.approx(1.0)


def test_none_pass():
    assert pass_at_k(3, 0, 2) == 0.0


def test_pass_at_1_is_fraction_correct():
    # pass@1 with n samples reduces to c/n.
    assert pass_at_k(3, 1, 1) == pytest.approx(1 / 3)
    assert pass_at_k(5, 2, 1) == pytest.approx(2 / 5)


def test_unbiased_estimator_value():
    # Standard Chen et al. estimator: 1 - C(n-c,k)/C(n,k).
    # n=3, c=1, k=2 -> 1 - C(2,2)/C(3,2) = 1 - 1/3 = 2/3.
    assert pass_at_k(3, 1, 2) == pytest.approx(2 / 3)
    # n=5, c=2, k=2 -> 1 - C(3,2)/C(5,2) = 1 - 3/10 = 0.7
    assert pass_at_k(5, 2, 2) == pytest.approx(0.7)


def test_k_clamped_to_n():
    # asking pass@5 with only 3 samples clamps k=3; c=1 -> n-c=2 < 3 -> 1.0
    assert pass_at_k(3, 1, 5) == pytest.approx(1.0)


def test_any_pass_when_k_equals_n():
    # With n=k, one correct guarantees the pick contains it -> 1.0.
    assert pass_at_k(3, 1, 3) == pytest.approx(1.0)


def test_zero_samples():
    assert pass_at_k(0, 0, 1) == 0.0
