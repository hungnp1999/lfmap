"""Frozen tests of card QW-S2: common.scoring.decide (spec section 5, rules 2-4)."""

import pytest
from common.scoring import decide

LINES = {"plain": 100, "pydanticai": 100, "langgraph": 100}
PACKAGES = {"plain": 0, "pydanticai": 5, "langgraph": 5}


def call(
    totals: dict[str, float],
    s1: dict[str, int] | None = None,
    capability: dict[str, int] | None = None,
    packages: dict[str, int] | None = None,
) -> str:
    return decide(totals, s1 or LINES, capability or {}, packages or PACKAGES)


def test_plain_only_is_plain() -> None:
    assert call({"plain": 7.0}) == "plain"


def test_framework_without_enough_points_stays_plain() -> None:
    assert call({"plain": 6.0, "pydanticai": 7.4}, {"plain": 100, "pydanticai": 40}) == "plain"


def test_enough_points_and_s1_cut_chooses_framework() -> None:
    assert call({"plain": 5.0, "pydanticai": 7.0}, {"plain": 100, "pydanticai": 60}) == "pydanticai"


def test_exactly_one_and_a_half_points_and_exactly_thirty_percent_qualifies() -> None:
    assert call({"plain": 5.0, "langgraph": 6.5}, {"plain": 100, "langgraph": 70}) == "langgraph"


def test_one_and_a_half_points_survives_float_noise() -> None:
    assert 4.1 - 2.6 < 1.5
    assert call({"plain": 2.6, "langgraph": 4.1}, {"plain": 100, "langgraph": 50}) == "langgraph"


def test_s1_cut_of_twenty_nine_percent_is_not_enough() -> None:
    assert call({"plain": 5.0, "pydanticai": 9.0}, {"plain": 100, "pydanticai": 71}) == "plain"


def test_framework_with_more_lines_than_plain_stays_plain() -> None:
    assert call({"plain": 5.0, "pydanticai": 9.0}, {"plain": 100, "pydanticai": 120}) == "plain"


def test_capability_over_150_lines_replaces_s1_cut() -> None:
    assert call({"plain": 5.0, "langgraph": 7.0}, capability={"langgraph": 151}) == "langgraph"


def test_capability_of_exactly_150_lines_is_not_enough() -> None:
    assert call({"plain": 5.0, "langgraph": 7.0}, capability={"langgraph": 150}) == "plain"


def test_capability_counts_only_for_the_framework_that_provides_it() -> None:
    assert call({"plain": 5.0, "pydanticai": 8.0}, capability={"langgraph": 400}) == "plain"


def test_capability_does_not_replace_the_points_condition() -> None:
    assert call({"plain": 5.0, "langgraph": 6.4}, capability={"langgraph": 400}) == "plain"


def test_both_conditions_must_hold_big_s1_cut_alone_is_not_enough() -> None:
    assert call({"plain": 5.0, "pydanticai": 6.4}, {"plain": 100, "pydanticai": 10}) == "plain"


def test_both_frameworks_qualify_higher_total_wins() -> None:
    s1 = {"plain": 100, "pydanticai": 50, "langgraph": 50}
    assert call({"plain": 4.0, "pydanticai": 7.0, "langgraph": 8.0}, s1) == "langgraph"
    assert call({"plain": 4.0, "pydanticai": 8.5, "langgraph": 8.0}, s1) == "pydanticai"


def test_tie_goes_to_fewer_runtime_packages() -> None:
    s1 = {"plain": 100, "pydanticai": 50, "langgraph": 50}
    totals = {"plain": 4.0, "pydanticai": 7.0, "langgraph": 7.0}
    assert call(totals, s1, packages={"plain": 0, "pydanticai": 9, "langgraph": 4}) == "langgraph"
    assert call(totals, s1, packages={"plain": 0, "pydanticai": 3, "langgraph": 4}) == "pydanticai"


def test_higher_scoring_framework_that_does_not_qualify_loses_to_qualifying_one() -> None:
    s1 = {"plain": 100, "pydanticai": 90, "langgraph": 50}
    assert call({"plain": 4.0, "pydanticai": 9.0, "langgraph": 6.0}, s1) == "langgraph"


def test_framework_dropped_by_section_3_is_absent_from_totals() -> None:
    s1 = {"plain": 100, "pydanticai": 50}
    assert call({"plain": 4.0, "pydanticai": 7.0}, s1) == "pydanticai"
    assert call({"plain": 4.0, "langgraph": 7.0}, {"plain": 100, "langgraph": 50}) == "langgraph"


def test_plain_missing_from_totals_is_value_error() -> None:
    with pytest.raises(ValueError):
        call({"pydanticai": 7.0, "langgraph": 8.0})


def test_zero_plain_s1_lines_does_not_divide_by_zero() -> None:
    assert call({"plain": 5.0, "pydanticai": 9.0}, {"plain": 0, "pydanticai": 0}) == "plain"


def test_result_is_one_of_the_three_names() -> None:
    s1 = {"plain": 100, "pydanticai": 10, "langgraph": 10}
    result = call({"plain": 1.0, "pydanticai": 9.0, "langgraph": 9.5}, s1)
    assert result in {"plain", "pydanticai", "langgraph"}
