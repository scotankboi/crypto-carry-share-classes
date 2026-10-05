"""tests/mutation_check.py must fail the run when a mutant survives or cannot be applied."""
from tests.mutation_check import MUTANTS, exit_status


def test_exit_status():
    assert exit_status(["caught", "caught"]) == 0
    assert exit_status(["caught", "survived"]) == 1
    assert exit_status(["caught", "skipped"]) == 1
    assert exit_status([]) == 1


def test_mutant_names_are_unique():
    names = [m[3] for m in MUTANTS]
    assert len(names) == len(set(names))
