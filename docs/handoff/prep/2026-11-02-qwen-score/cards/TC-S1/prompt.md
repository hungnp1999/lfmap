You are a careful Python 3.12 developer. Write ONE new module in the `lfmap` monorepo: `spikes/2a1-framework/common/scoring.py`. Code, comments and docstrings in English. Standard library only. Small functions, type hints everywhere, an English docstring on the module and on every public function.

RULES
- Do NOT edit the tests and do NOT define pytest fixtures.
- Reply with the line `FILE: spikes/2a1-framework/common/scoring.py`, then ONE ```python block with the COMPLETE module. Never answer with an empty block.
- The module holds ONLY `normalise` (plus private helpers and the constant below). Another card adds `decide` later; do not write it.

PURPOSE
A spike compares three agent-orchestration variants (`plain`, `pydanticai`, `langgraph`) on several measures. `normalise` turns the raw measures into scores from 0 to 10 so they can be weighted and summed. Pure function only: no file-system calls, no printing.

API
```python
def normalise(raw: dict[str, dict[str, float]], better: dict[str, str]) -> dict[str, dict[str, float]]: ...
```
- `raw`: measure name (`"S1"`) -> variant name (`"plain"`) -> value.
- `better`: measure name -> `"fewer"` (a smaller value is better) or `"higher"` (a larger value is better).
- Returns the same shape; every value is a `float` score from 0 to 10.

Module-level constant (write it exactly like this):
```python
BETTER = ("fewer", "higher")
```

normalise, step by step (keep this order)
1. For every `measure` in `raw`: if `measure` is not in `better`, `raise ValueError`. If `better[measure]` is not in `BETTER` (exact match; `"FEWER"` and `"lower"` are wrong), `raise ValueError`. This check runs for EVERY measure before any score is computed, even when the values are all equal.
2. Keys of `better` that `raw` does not have are ignored.
3. For each `measure`, `values = raw[measure]`. If `values` is empty, leave that measure out of the result.
4. Compute `best` and `worst`: for `"fewer"`, `best = min(values.values())` and `worst = max(...)`; for `"higher"`, `best = max(...)` and `worst = min(...)`.
5. If `best == worst` (one variant, or all values equal): every variant gets `10.0`.
6. Otherwise the score of a variant is `10.0 * (value - worst) / (best - worst)`. This formula is right for both directions (the best variant gets 10, the worst gets 0).
7. Do not modify `raw` or `better`. The result is a new dict; every value is a `float`.

Examples
| `raw` | `better` | result |
| --- | --- | --- |
| `{"S1": {"a": 100, "b": 60, "c": 140}}` | `{"S1": "fewer"}` | `{"S1": {"a": 5.0, "b": 10.0, "c": 0.0}}` |
| `{"X": {"a": 0, "b": 1, "c": 4}}` | `{"X": "higher"}` | `{"X": {"a": 0.0, "b": 2.5, "c": 10.0}}` |
| `{"S1": {"a": 7, "b": 7}}` | `{"S1": "fewer"}` | `{"S1": {"a": 10.0, "b": 10.0}}` |

Imports available: none needed (standard library only).

TESTS (already in `spikes/2a1-framework/tests/test_scoring_normalise.py`; your module must pass all of them, plus `ruff check` and `ruff format --check` with line length 120):
```python
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
```

NOW WRITE THE COMPLETE scoring.py
