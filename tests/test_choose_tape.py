"""How `play` turns what you typed into one kept tape."""

from __future__ import annotations

import pytest
import typer

from runthrough.cli import choose_tape


def test_picks_by_number_name_part_or_path_and_refuses_an_ambiguous_part(tmp_path):
    (tmp_path / 'what-changed.tape.yml').write_text('name: What Changed\nsteps: []\n')
    (tmp_path / 'who-changed-it.tape.yml').write_text('name: Who Changed It\nsteps: []\n')
    second = tmp_path / 'who-changed-it.tape.yml'

    assert choose_tape('2', tmp_path) == second
    assert choose_tape('who', tmp_path) == second
    assert choose_tape(str(second), tmp_path) == second
    with pytest.raises(typer.Exit):
        choose_tape('changed', tmp_path)
