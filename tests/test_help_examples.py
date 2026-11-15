"""Every command a help screen lists carries an Examples block, so a reader who reaches
it has a line to copy. A new subcommand written with only a docstring fails here."""

import typer
from typer.core import TyperGroup

from runthrough import cli


def visible_leaves(command, path: str) -> list[tuple[str, object]]:
    if command.hidden:
        return []
    if isinstance(command, TyperGroup):
        return [leaf for name, child in command.commands.items() for leaf in visible_leaves(child, f'{path} {name}')]
    return [(path, command)]


def test_every_listed_leaf_has_an_examples_epilog():
    leaves = visible_leaves(typer.main.get_command(cli.app), 'runthrough')
    missing = [path for path, command in leaves if 'Examples:' not in (command.epilog or '')]
    assert leaves
    assert missing == []
