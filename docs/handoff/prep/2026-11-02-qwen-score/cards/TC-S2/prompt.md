You are a careful Python 3.12 developer. Write ONE new module in the `lfmap` monorepo: `spikes/2a1-framework/common/scoring.py`. Code, comments and docstrings in English. Standard library only. Small functions, type hints everywhere, an English docstring on the module and on every public function.

RULES
- Do NOT edit the tests and do NOT define pytest fixtures.
- Reply with the line `FILE: spikes/2a1-framework/common/scoring.py`, then ONE ```python block with the COMPLETE module. Never answer with an empty block.
- The module holds ONLY `decide` (plus private helpers and the constants below). Another card adds `normalise` later; do not write it.

PURPOSE
A spike compares three agent-orchestration variants (`plain`, `pydanticai`, `langgraph`). `decide` applies the decision rules and names the winner. Pure function only: no file-system calls, no printing.

Rules of the spec (rule 3 shortened):
> 2. A framework (`pydanticai` or `langgraph`) is chosen over `plain` only if **both**: its total score is at least 1.5 points higher, and S1 is at least 30 % fewer lines or it provides a capability that `plain` needed more than 150 lines to build (named in the report).
> 3. Otherwise the result is "no framework": the `plain` code becomes the base for the Phase 2 orchestration.
> 4. Between the two frameworks, the higher total score wins; a tie goes to fewer runtime packages.

Rule 1 (drop a variant that failed) is already done by the caller: a failed variant is simply NOT a key of `totals`.

API
```python
def decide(
    totals: dict[str, float],
    s1_lines: dict[str, int],
    plain_capability_lines: dict[str, int],
    packages: dict[str, int],
) -> str: ...
```
Returns `"plain"`, `"pydanticai"` or `"langgraph"`.
- `totals`: weighted total score (0-10) of each remaining variant. Must contain `"plain"`; `"pydanticai"` and `"langgraph"` may be missing.
- `s1_lines`: S1, the orchestration line count of each variant (has a key for every variant in `totals`).
- `plain_capability_lines`: for each framework, the number of lines `plain` had to write to get a capability that the framework gives for free. A framework missing from this dict means 0.
- `packages`: number of new runtime packages of each variant (has a key for every framework in `totals`).

Module-level constants (write them exactly like this):
```python
FRAMEWORKS = ("pydanticai", "langgraph")
MIN_GAIN = 1.5
MIN_S1_CUT_PERCENT = 30
CAPABILITY_LINES = 150
EPSILON = 1e-9
```

decide, step by step (keep this order)
1. If `"plain"` is not in `totals`, `raise ValueError`.
2. `candidates = []`. For every `name` in `FRAMEWORKS` with `name in totals`, check rule 2 (steps 3 to 5); if it passes, append `name` to `candidates`.
3. Score condition: `totals[name] - totals["plain"] >= MIN_GAIN - EPSILON`. (`EPSILON` lets `4.1 - 2.6`, which is `1.4999999999999996`, still count as 1.5.) If it fails, `name` is out, even when the other condition holds.
4. S1 condition: `plain = s1_lines["plain"]`, `fw = s1_lines[name]`. It holds when `plain > 0` and `(plain - fw) * 100 >= MIN_S1_CUT_PERCENT * plain` (integer arithmetic, no floats; exactly 30 % passes, 29 % does not). If `plain == 0` this condition never holds.
5. Capability condition: it holds when `plain_capability_lines.get(name, 0) > CAPABILITY_LINES` (strictly greater: exactly 150 does not pass; only the framework `name` itself counts). Rule 2 needs the score condition (step 3) AND (the S1 condition OR the capability condition) (step 4 or step 5).
6. If `candidates` is empty, return `"plain"` (rule 3).
7. Rule 4 looks only at `candidates` (a framework that fails rule 2 never competes, even with a higher score). `top = max(totals[n] for n in candidates)`; `leaders = [n for n in candidates if top - totals[n] <= EPSILON]`.
8. Return the element of `leaders` with the smallest `packages[n]`: `min(leaders, key=lambda n: packages[n])`. On a full tie `min` keeps the first one, which follows the order of `FRAMEWORKS`.

Examples
| `totals` | `s1_lines` | `plain_capability_lines` | result |
| --- | --- | --- | --- |
| plain 5.0, pydanticai 7.0 | plain 100, pydanticai 60 | `{}` | `pydanticai` |
| plain 5.0, pydanticai 9.0 | plain 100, pydanticai 71 | `{}` | `plain` (S1 only 29 % fewer) |
| plain 5.0, langgraph 7.0 | plain 100, langgraph 100 | langgraph 151 | `langgraph` |
| plain 5.0, langgraph 6.4 | plain 100, langgraph 10 | langgraph 400 | `plain` (short of 1.5 points) |

Imports available: none needed (standard library only).

TESTS (already in `spikes/2a1-framework/tests/test_scoring_decide.py`; your module must pass all of them, plus `ruff check` and `ruff format --check` with line length 120):
```python
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
```

NOW WRITE THE COMPLETE scoring.py
