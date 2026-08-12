"""The front door: record a tape, or ask for one and record that."""

from __future__ import annotations

import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console

from runthrough import ask as ask_module
from runthrough import fleet as fleet_module
from runthrough.recorder import record

app = typer.Typer(
    no_args_is_help=True,
    add_completion=True,
    help='Record what you actually typed, and what it actually printed.',
)
err = Console(stderr=True)

DEFAULT_LIBRARY = Path.home() / '.local/share/runthrough'


def open_page(path: Path) -> None:
    opener = 'open' if platform.system() == 'Darwin' else 'xdg-open'
    subprocess.Popen(
        [opener, path.resolve().as_uri()],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def slugify(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:48]


def produce(tape: dict, question: str, library: Path, confirm: bool, watch: bool) -> Path:
    body = yaml.safe_dump(tape, sort_keys=False, width=88, allow_unicode=True)
    err.print(body)

    if confirm and input('record this? [y/N] ').strip().lower() != 'y':
        raise typer.Exit(1)

    library.mkdir(parents=True, exist_ok=True)
    slug = slugify(question)
    tape_path = library / f'{slug}.tape.yml'
    page_path = library / f'{slug}.html'
    tape_path.write_text(body)

    record(tape_path, page_path, cast_path=page_path.with_suffix('.cast'))
    if watch:
        open_page(page_path)
    err.print(f'tape kept at {tape_path}')
    return page_path


@app.command(rich_help_panel='Recording')
def play(
    tape: Annotated[Path, typer.Argument(help='A tape file to execute and record.')],
    out: Annotated[Path | None, typer.Option('--out', help='Where to write the page.')] = None,
    cast: Annotated[Path | None, typer.Option('--cast', help='Also write an asciicast v2 file.')] = None,
    fps: Annotated[int, typer.Option('--fps', help='Screen samples per second.')] = 14,
    watch: Annotated[bool, typer.Option('--watch/--no-watch', help='Open the page when done.')] = True,
) -> None:
    """Run a tape you already have and record it."""
    if not tape.is_file():
        raise typer.BadParameter(f'no such tape: {tape}')
    page = out or tape.with_suffix('').with_suffix('.html')
    record(tape, page, cast_path=cast, fps=fps)
    if watch:
        open_page(page)


@app.command(rich_help_panel='Asking')
def ask(
    question: Annotated[list[str], typer.Argument(help='What you want shown, in English.')],
    cli: Annotated[str, typer.Option('--cli', help='Which command to demonstrate.')],
    sandbox: Annotated[bool, typer.Option('--sandbox', help='Redirect XDG roots to a throwaway dir.')] = False,
    yes: Annotated[bool, typer.Option('--yes', help='Record without confirming the tape.')] = False,
    budget: Annotated[int, typer.Option('--budget', help='Help-text characters to read.')] = 40000,
    library: Annotated[Path, typer.Option('--library', help='Where tapes are kept.')] = DEFAULT_LIBRARY,
    watch: Annotated[bool, typer.Option('--watch/--no-watch', help='Open the page when done.')] = True,
) -> None:
    """Ask one command to show you something, reading only its own help."""
    import shutil

    if shutil.which(cli) is None:
        raise typer.BadParameter(f'{cli} is not installed')

    asked = ' '.join(question)
    err.print(f'reading {cli} help')
    help_text = ask_module.gather_help(cli, budget)

    err.print('authoring tape')
    raw = ask_module.author_tape(cli, asked, help_text, sandbox)
    tape = ask_module.validate_tape(ask_module.clean_yaml(raw), cli)
    if sandbox:
        tape['sandbox'] = 'xdg'

    produce(tape, asked, library, confirm=not yes, watch=watch)


@app.command(rich_help_panel='Asking')
def fleet(
    question: Annotated[list[str], typer.Argument(help='What you want answered, in English.')],
    yes: Annotated[bool, typer.Option('--yes', help='Record without confirming the tape.')] = False,
    budget: Annotated[int, typer.Option('--budget', help='Help-text characters to read.')] = 30000,
    library: Annotated[Path, typer.Option('--library', help='Where tapes are kept.')] = DEFAULT_LIBRARY,
    watch: Annotated[bool, typer.Option('--watch/--no-watch', help='Open the page when done.')] = True,
) -> None:
    """Ask a question that spans tools, and let it find which ones to use."""
    asked = ' '.join(question)

    err.print('routing')
    paths = fleet_module.route(asked)
    err.print(f'  tools: {paths}')

    pages: list[str] = []
    allowed = set(fleet_module.READ_COMMANDS)
    for path in paths:
        parts = path.split()
        allowed.add(parts[0])
        text = ask_module.gather_help(parts[0], budget // max(1, len(paths))) if len(parts) == 1 else ask_module.run_help(parts)
        if text.strip():
            pages.append(f'$ {path} --help\n{text}')
    help_text = '\n\n'.join(pages)

    err.print('probing')
    observations = fleet_module.probe(asked, help_text, allowed)

    err.print('authoring')
    tape = fleet_module.parse_tape(fleet_module.author(asked, help_text, observations))
    if 'steps' not in tape:
        raise typer.BadParameter('model did not return a tape')
    for step in tape['steps']:
        fleet_module.check_command(step['run'], allowed)

    produce(tape, asked, library, confirm=not yes, watch=watch)


@app.command(rich_help_panel='Library')
def library(
    path: Annotated[Path, typer.Option('--library', help='Where tapes are kept.')] = DEFAULT_LIBRARY,
) -> None:
    """List the runthroughs you have recorded."""
    tapes = sorted(path.glob('*.tape.yml'))
    if not tapes:
        err.print(f'nothing recorded yet in {path}')
        raise typer.Exit(0)

    for tape in tapes:
        loaded = yaml.safe_load(tape.read_text())
        page = tape.with_name(tape.name.replace('.tape.yml', '.html'))
        mark = '' if page.exists() else '  (no recording)'
        print(f'{loaded.get("name", tape.stem)}  —  {loaded.get("title", "")}{mark}')


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == '__main__':
    main()
