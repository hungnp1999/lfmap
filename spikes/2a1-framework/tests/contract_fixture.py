"""Shared glue of the contract test (S3): a two-card toy package and scripted FakeModels.

`python tests/contract_fixture.py <variant> <tmp>` runs the "full" scenario under the socket guard in a
fresh process, prints the run id and exits, so the test can resume it from yet another process (E4).
"""

import importlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from common.fake import FakeModel, plan_reply, review_reply, work_reply  # noqa: E402
from common.gates import make_diff  # noqa: E402
from common.guard import SocketGuard  # noqa: E402
from common.metrics import Trace, traced  # noqa: E402
from common.models import Card, Models, Package  # noqa: E402

GOOD_CALC = "def add(a: int, b: int) -> int:\n    return a + b\n"
BAD_CALC = "def add(a: int, b: int) -> int:\n    return a - b\n"
GOOD_GREET = 'def hello(name: str) -> str:\n    return f"hello {name}"\n'
TESTS = {
    "tests/test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    "tests/test_greet.py": 'from greet import hello\n\n\ndef test_hello():\n    assert hello("x") == "hello x"\n',
}
CARDS = [
    {"id": "calc", "title": "add", "target": "calc.py", "tests": ["tests/test_calc.py"], "prompt": "Write add(a, b)."},
    {"id": "greet", "title": "hello", "target": "greet.py", "tests": ["tests/test_greet.py"], "prompt": "Write hello."},
]
REAL = {"check": "C1", "file": "calc.py", "quote": "return a + b", "problem": "needs an overflow note"}
FAKE = {"check": "C3", "file": "calc.py", "quote": "os.system(cmd)", "problem": "invented line"}


def make_package(root: Path) -> Package:
    """Toy workdir with two frozen tests and a pytest.ini; gates run with this interpreter."""
    workdir = root / "work"
    for rel, text in {**TESTS, "pytest.ini": "[pytest]\npythonpath = .\n"}.items():
        (workdir / rel).parent.mkdir(parents=True, exist_ok=True)
        (workdir / rel).write_text(text, encoding="utf-8")
    return Package(id="toy", goal="Two tiny modules.", workdir=workdir)


def full_models() -> Models:
    """Plan two cards; calc fails its gate once, gets one rework (one real, one invented finding), then ready."""
    leading = FakeModel("leading")
    leading.on("WORK PACKAGE", plan_reply(CARDS))
    leading.on("CARD ID: calc", review_reply("rework", [REAL, FAKE]), review_reply("ready"))
    leading.on("CARD ID: greet", review_reply("ready"))
    working = FakeModel("working")
    working.on("CARD ID: calc", work_reply("calc.py", BAD_CALC), work_reply("calc.py", GOOD_CALC))
    working.on("CARD ID: greet", work_reply("greet.py", GOOD_GREET))
    return Models(leading=leading, working=working)


def escalate_models() -> Models:
    """Every review says rework: the second rework must become escalate."""
    leading = FakeModel("leading").on("WORK PACKAGE", plan_reply(CARDS[:1])).on("CARD ID", review_reply("rework"))
    working = FakeModel("working").on("CARD ID: calc", work_reply("calc.py", GOOD_CALC))
    return Models(leading=leading, working=working)


def replay_card() -> Card:
    """The calc card with a known diff, as a replay case would give it."""
    return Card(**CARDS[0], replay_diff=make_diff("calc.py", "", GOOD_CALC))


def replay_models() -> Models:
    """Replay: no Plan, no Work call; one ready review."""
    return Models(leading=FakeModel("leading").on("CARD ID: calc", review_reply("ready")), working=FakeModel("working"))


def flow(variant: str):
    """The variant's flow module."""
    return importlib.import_module(f"variants.{variant}.flow")


def main(variant: str, root: Path) -> int:
    """Run the full scenario until the pause, print the run id, exit."""
    trace = Trace()
    with SocketGuard() as guard:
        result = flow(variant).run_flow(
            make_package(root), models=traced(full_models(), trace), state_dir=root / "state"
        )
    print(result.run_id)
    return 3 if guard.blocked else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], Path(sys.argv[2])))
