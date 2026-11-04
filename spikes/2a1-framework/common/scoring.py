"""Spike scoring: normalise raw measures to 0-10 and apply the decision rule (spec section 5).

Written by qwen2.5-coder:14b with the L1b store (cards QW-S1, QW-S2); the two answers were joined in review.
"""

BETTER = ("fewer", "higher")
FRAMEWORKS = ("pydanticai", "langgraph")
MIN_GAIN = 1.5
MIN_S1_CUT_PERCENT = 30
CAPABILITY_LINES = 150
EPSILON = 1e-9


def normalise(raw: dict[str, dict[str, float]], better: dict[str, str]) -> dict[str, dict[str, float]]:
    """Normalise raw measures into scores from 0 to 10 for comparison."""
    for measure in raw:
        if measure not in better:
            raise ValueError(f"Measure '{measure}' not found in 'better'")
        if better[measure] not in BETTER:
            raise ValueError(f"Invalid 'better' value for measure '{measure}': {better[measure]}")

    result = {}
    for measure, values in raw.items():
        if not values:
            continue

        direction = better[measure]
        if direction == "fewer":
            best = min(values.values())
            worst = max(values.values())
        else:
            best = max(values.values())
            worst = min(values.values())

        if best == worst:
            result[measure] = {variant: 10.0 for variant in values}
        else:
            result[measure] = {
                variant: 10.0 * (value - worst) / (best - worst) + 0.0 for variant, value in values.items()
            }

    return result


def decide(
    totals: dict[str, float],
    s1_lines: dict[str, int],
    plain_capability_lines: dict[str, int],
    packages: dict[str, int],
) -> str:
    """Determine the best agent-orchestration variant based on decision rules."""
    if "plain" not in totals:
        raise ValueError("plain must be in totals")

    candidates = []
    for name in FRAMEWORKS:
        if name in totals:
            if _meets_score_condition(totals, name) and _meets_s1_or_capability_condition(
                s1_lines, plain_capability_lines, name
            ):
                candidates.append(name)

    if not candidates:
        return "plain"

    top_score = max(totals[n] for n in candidates)
    leaders = [n for n in candidates if top_score - totals[n] <= EPSILON]

    return min(leaders, key=lambda n: packages[n])


def _meets_score_condition(totals: dict[str, float], name: str) -> bool:
    """Check if the score condition is met for the given framework."""
    return totals[name] - totals["plain"] >= MIN_GAIN - EPSILON


def _meets_s1_or_capability_condition(
    s1_lines: dict[str, int],
    plain_capability_lines: dict[str, int],
    name: str,
) -> bool:
    """Check if either S1 condition or capability condition is met for the given framework."""
    plain_s1 = s1_lines["plain"]
    fw_s1 = s1_lines[name]

    s1_condition = plain_s1 > 0 and (plain_s1 - fw_s1) * 100 >= MIN_S1_CUT_PERCENT * plain_s1
    capability_condition = plain_capability_lines.get(name, 0) > CAPABILITY_LINES

    return s1_condition or capability_condition
