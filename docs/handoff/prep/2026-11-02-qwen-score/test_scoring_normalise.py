"""Frozen tests of card QW-S1: common.scoring.normalise (spec section 4)."""

import pytest
from common.scoring import normalise

THREE = ("plain", "pydanticai", "langgraph")


def test_fewer_best_is_ten_worst_is_zero() -> None:
    out = normalise({"S1": {"plain": 100, "pydanticai": 60, "langgraph": 140}}, {"S1": "fewer"})
    assert out["S1"]["pydanticai"] == pytest.approx(10.0)
    assert out["S1"]["langgraph"] == pytest.approx(0.0)


def test_fewer_is_linear_in_between() -> None:
    out = normalise({"S1": {"plain": 100, "pydanticai": 60, "langgraph": 140}}, {"S1": "fewer"})
    assert out["S1"]["plain"] == pytest.approx(5.0)
    out = normalise({"S1": {"a": 0, "b": 25, "c": 100}}, {"S1": "fewer"})
    assert out["S1"]["b"] == pytest.approx(7.5)


def test_higher_best_is_ten_worst_is_zero() -> None:
    out = normalise({"X": {"a": 2.0, "b": 8.0, "c": 5.0}}, {"X": "higher"})
    assert out["X"]["b"] == pytest.approx(10.0)
    assert out["X"]["a"] == pytest.approx(0.0)
    assert out["X"]["c"] == pytest.approx(5.0)


def test_higher_is_linear_in_between() -> None:
    out = normalise({"X": {"a": 0, "b": 1, "c": 4}}, {"X": "higher"})
    assert out["X"]["b"] == pytest.approx(2.5)


def test_single_variant_gets_ten() -> None:
    out = normalise({"S1": {"plain": 123}, "X": {"plain": 0.5}}, {"S1": "fewer", "X": "higher"})
    assert out == {"S1": {"plain": 10.0}, "X": {"plain": 10.0}}


def test_all_equal_gets_ten_for_everyone() -> None:
    out = normalise({"S1": dict.fromkeys(THREE, 42)}, {"S1": "fewer"})
    assert out["S1"] == dict.fromkeys(THREE, 10.0)
    out = normalise({"S1": dict.fromkeys(THREE, 0)}, {"S1": "higher"})
    assert out["S1"] == dict.fromkeys(THREE, 10.0)


def test_two_equal_best_both_ten() -> None:
    out = normalise({"S1": {"a": 10, "b": 10, "c": 30}}, {"S1": "fewer"})
    assert out["S1"] == {"a": pytest.approx(10.0), "b": pytest.approx(10.0), "c": pytest.approx(0.0)}


def test_measures_are_independent_and_use_their_own_direction() -> None:
    raw = {"S1": {"a": 1, "b": 3}, "X": {"a": 1, "b": 3}}
    out = normalise(raw, {"S1": "fewer", "X": "higher"})
    assert out["S1"] == {"a": pytest.approx(10.0), "b": pytest.approx(0.0)}
    assert out["X"] == {"a": pytest.approx(0.0), "b": pytest.approx(10.0)}


def test_negative_and_float_values() -> None:
    out = normalise({"X": {"a": -1.5, "b": 0.0, "c": 1.5}}, {"X": "higher"})
    assert out["X"] == {"a": pytest.approx(0.0), "b": pytest.approx(5.0), "c": pytest.approx(10.0)}


def test_keeps_every_measure_and_variant_and_returns_floats() -> None:
    raw = {"S1": {"a": 1, "b": 2}, "S2": {"a": 5, "b": 5}}
    out = normalise(raw, {"S1": "fewer", "S2": "fewer"})
    assert set(out) == {"S1", "S2"}
    assert set(out["S1"]) == {"a", "b"}
    assert all(isinstance(v, float) for scores in out.values() for v in scores.values())


def test_does_not_modify_its_arguments() -> None:
    raw = {"S1": {"a": 1, "b": 2}}
    better = {"S1": "fewer"}
    normalise(raw, better)
    assert raw == {"S1": {"a": 1, "b": 2}}
    assert better == {"S1": "fewer"}


def test_extra_entries_in_better_are_ignored() -> None:
    out = normalise({"S1": {"a": 1, "b": 2}}, {"S1": "fewer", "S9": "higher"})
    assert set(out) == {"S1"}


def test_empty_raw_gives_empty_result() -> None:
    assert normalise({}, {"S1": "fewer"}) == {}


def test_unknown_better_value_is_value_error() -> None:
    with pytest.raises(ValueError):
        normalise({"S1": {"a": 1, "b": 2}}, {"S1": "lower"})


def test_unknown_better_value_is_error_even_when_all_equal() -> None:
    with pytest.raises(ValueError):
        normalise({"S1": {"a": 1, "b": 1}}, {"S1": "FEWER"})


def test_measure_missing_from_better_is_value_error() -> None:
    with pytest.raises(ValueError):
        normalise({"S1": {"a": 1, "b": 2}, "S2": {"a": 1, "b": 2}}, {"S1": "fewer"})
