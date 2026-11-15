"""Every command a help screen lists carries an Examples block, so a reader who reaches
it has a line to copy. A new subcommand written with only a docstring fails here.

Every `runthrough ...` line the tool or its README prints for a person to run names a
command that exists, so a hint left behind by a rename fails here rather than sending
its reader to an error."""

import re
from pathlib import Path

import typer
from typer.core import TyperCommand
from typer.core import TyperGroup

from runthrough import cli

REPO = Path(__file__).parent.parent

# A command printed for a person to run: at the start of a string or code span, after
# the two spaces that set a hint off from its lead-in, or after a numbered step. A word
# running into a `/` or a `.` is a path argument, and a flag or placeholder ends the path.
WORDS = r'((?: [a-z][\w-]*(?![\w/.-]))+)'
PRINTED_IN_SOURCE = re.compile(rf"(?:['\"`]|  |\d\. )runthrough{WORDS}")
PRINTED_IN_SPAN = re.compile(rf'`runthrough{WORDS}')
SHELL_FENCE = re.compile(r'^```(?:bash|sh)\n(.*?)^```', re.MULTILINE | re.DOTALL)
PRINTED_IN_FENCE = re.compile(rf'^runthrough{WORDS}', re.MULTILINE)


def visible_leaves(command, path: str) -> list[tuple[str, TyperCommand]]:
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


def printed_commands():
    for source in sorted((REPO / 'src' / 'runthrough').glob('*.py')):
        for match in PRINTED_IN_SOURCE.finditer(source.read_text()):
            yield source.name, match.group(1).split()
    readme = (REPO / 'README.md').read_text()
    for fence in SHELL_FENCE.finditer(readme):
        for match in PRINTED_IN_FENCE.finditer(fence.group(1)):
            yield 'README.md', match.group(1).split()
    for match in PRINTED_IN_SPAN.finditer(readme):
        yield 'README.md', match.group(1).split()


def test_every_command_it_prints_is_in_the_command_tree():
    """The walk stops at a leaf, so the words after it are that command's arguments."""
    tree = typer.main.get_command(cli.app)
    missing = []
    walked = 0
    for source, words in printed_commands():
        walked += 1
        command = tree
        for word in words:
            subcommands = getattr(command, 'commands', None)
            if subcommands is None:
                break
            if word not in subcommands:
                missing.append(f'{source}: runthrough {" ".join(words)}')
                break
            command = subcommands[word]

    assert walked > 20
    assert missing == []
