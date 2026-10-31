"""Reference solution for cards QW-S1 and QW-S2 (spike scoring); becomes `common/scoring.py` in the spike."""

FRAMEWORKS = ("pydanticai", "langgraph")
BETTER = ("fewer", "higher")
MIN_GAIN = 1.5
MIN_S1_CUT_PERCENT = 30
CAPABILITY_LINES = 150
EPSILON = 1e-9


def _scale(values: dict[str, float], better: str) -> dict[str, float]:
    best = min(values.values()) if better == "fewer" else max(values.values())
    worst = max(values.values()) if better == "fewer" else min(values.values())
    if best == worst:
        return {variant: 10.0 for variant in values}
    return {variant: 10.0 * (value - worst) / (best - worst) for variant, value in values.items()}


def normalise(raw: dict[str, dict[str, float]], better: dict[str, str]) -> dict[str, dict[str, float]]:
    """Scores 0-10 per measure and variant: best 10, worst 0, linear between."""
    for measure in raw:
        if measure not in better:
            raise ValueError(f"no 'better' entry for measure {measure!r}")
        if better[measure] not in BETTER:
            raise ValueError(f"unknown 'better' value {better[measure]!r} for measure {measure!r}")
    return {measure: _scale(values, better[measure]) for measure, values in raw.items() if values}


def _s1_cut_enough(plain: int, framework: int) -> bool:
    return plain > 0 and (plain - framework) * 100 >= MIN_S1_CUT_PERCENT * plain


def _qualifies(
    name: str,
    totals: dict[str, float],
    s1_lines: dict[str, int],
    plain_capability_lines: dict[str, int],
) -> bool:
    if totals[name] - totals["plain"] < MIN_GAIN - EPSILON:
        return False
    if _s1_cut_enough(s1_lines["plain"], s1_lines[name]):
        return True
    return plain_capability_lines.get(name, 0) > CAPABILITY_LINES


def decide(
    totals: dict[str, float],
    s1_lines: dict[str, int],
    plain_capability_lines: dict[str, int],
    packages: dict[str, int],
) -> str:
    """Spec section 5 rules 2-4: 'plain', 'pydanticai' or 'langgraph'."""
    if "plain" not in totals:
        raise ValueError("'plain' is missing from totals")
    candidates = [
        name for name in FRAMEWORKS if name in totals and _qualifies(name, totals, s1_lines, plain_capability_lines)
    ]
    if not candidates:
        return "plain"
    top = max(totals[name] for name in candidates)
    leaders = [name for name in candidates if top - totals[name] <= EPSILON]
    return min(leaders, key=lambda name: packages[name])
