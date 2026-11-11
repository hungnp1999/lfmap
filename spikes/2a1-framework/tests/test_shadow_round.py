"""shadow_round.py: dry run (two loops, late stop, stop on surprise) and case table."""

import shadow_round as sr


def test_dry_run_passes(capsys):
    assert sr.dry_run() == 0
    assert "DRY RUN OK" in capsys.readouterr().out


def test_every_case_has_a_folder_and_a_gate():
    for case in sr.CASES:
        assert (sr.HERE / "cases" / case / "expected.json").exists()
        assert sr.gate_of(case).target in (sr.HERE / "cases" / case / "diff.patch").read_text(encoding="utf-8")
    assert len(sr.CASES) == len(set(sr.CASES)) == 15
