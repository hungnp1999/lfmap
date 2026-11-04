"""Plan phase checks (F6): a card the harness cannot gate is refused, never sent to Work."""

from common.gates import read_in
from common.models import Card, Package


def complete_cards(package: Package, cards: list[Card]) -> list[Card]:
    """Cards with the package's frozen tests and an explicit scope; ValueError for a card that cannot be gated.

    The package's `tests` table wins over what the model wrote. A card needs at least one test, every test must
    exist in the workdir, and when the package lists its targets no card may name another file.
    """
    done = []
    for card in cards:
        if package.tests and card.target not in package.tests:
            raise ValueError(f"card {card.id}: target {card.target} is not one of the package's modules")
        tests = package.tests.get(card.target) or card.tests
        if not tests:
            raise ValueError(f"card {card.id}: no frozen tests for {card.target}; the pytest gate would not run")
        missing = [t for t in tests if package.workdir is not None and not read_in(package.workdir, t)]
        if missing:
            raise ValueError(f"card {card.id}: frozen tests not found in the workdir: {missing}")
        done.append(card.model_copy(update={"tests": tests, "scope": card.scope or [card.target]}))
    return done
