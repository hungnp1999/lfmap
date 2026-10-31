"""The `pydanticai` variant (task F2): not implemented yet; the contract test marks it xfail(strict=True)."""

from pathlib import Path

from common.models import Card, Models, Package, RunResult

VARIANT = "pydanticai"


def run_flow(package: Package, *, models: Models, state_dir: Path, replay_cards: list[Card] | None = None) -> RunResult:
    """Run Plan, Work and Review, then pause for approval (spec section 2)."""
    raise NotImplementedError(f"{VARIANT} variant: task F2")


def resume(run_id: str, *, approve: bool, state_dir: Path) -> RunResult:
    """Finish a paused run in a new process."""
    raise NotImplementedError(f"{VARIANT} variant: task F2")
