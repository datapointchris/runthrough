"""The front door: record a tape, or ask for one and record that."""

from __future__ import annotations

import importlib.metadata
import json
import platform
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pyselfupdate import Config
from pyselfupdate import notify
from pyselfupdate.typercmd import run_update
from rich.console import Console

from runthrough import ask as ask_module
from runthrough import config as config_module
from runthrough import investigate as investigate_module
from runthrough.recorder import record


def examples(*rows: tuple[str, str]) -> str:
    """A help epilog listing each command beside the situation it answers, commands aligned.
    Keep each row inside 78 characters, the width an 80-column terminal leaves inside rich's padding."""
    width = max(len(command) for command, _ in rows)
    return 'Examples:\n' + '\n'.join(f'{command.ljust(width)}   {situation}' for command, situation in rows)


app = typer.Typer(
    no_args_is_help=True,
    add_completion=True,
    help=(
        'Turn a question about a command into a recorded terminal demo. '
        'The commands run for real, and the demo plays back as an HTML page.\n\n'
        'A tape is the YAML list of commands a demo runs. '
        'ask writes one for you, then records it.'
    ),
    epilog=(
        'Your first demo:\n'
        '1. cd into a directory the demo should run in, such as a git repo.\n'
        '2. runthrough ask --cli git "show what changed and who changed it"\n'
        "   Claude reads git's --help and prints a tape. Nothing has run yet.\n"
        '3. Answer y to "record this? \\[y/N]".\n'
        '   Each command runs, and the page opens in your browser.\n'
        '4. The tape, page and .cast file are kept in ~/.local/share/runthrough/.\n'
        '\n'
        'Later:\n'
        'runthrough library                    list every demo you kept, numbered\n'
        'runthrough play                       pick a demo, run it again, watch it\n'
        'runthrough play 2                     the same, for demo 2 in library\n'
        'runthrough investigate "<question>"   a demo across several tools; needs\n'
        '                                      routing set in\n'
        '                                      ~/.config/runthrough/config.yml\n'
        '\n'
        'ask and investigate need Claude Code (claude) installed and logged in.\n'
        'play runs a tape with no model.'
    ),
)
err = Console(stderr=True)

DEFAULT_LIBRARY = Path.home() / '.local/share/runthrough'

# One config for `update` and the notice, so the notice never names a release `update` would not install.
UPDATE_CONFIG = Config(tool='runthrough', owner='datapointchris')


def installed_commit() -> str | None:
    """Read the git commit from the installed dist-info. uv records it for any git
    install, which is how this tool is normally installed."""
    try:
        distribution = importlib.metadata.distribution('runthrough')
        direct_url = distribution.read_text('direct_url.json')
        if direct_url:
            return json.loads(direct_url).get('vcs_info', {}).get('commit_id')
    except Exception:
        return None
    return None


def version_callback(asked: bool) -> None:
    """`runthrough --version`, in the one line every CLI here answers it with."""
    if not asked:
        return
    try:
        version = importlib.metadata.version('runthrough')
    except importlib.metadata.PackageNotFoundError:
        version = 'unknown'
    commit = installed_commit()
    print(f'runthrough {version}{f" @ {commit[:8]}" if commit else ""}')
    raise typer.Exit()


@app.callback()
def root(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option('--version', callback=version_callback, is_eager=True, help='Show the installed version and exit.'),
    ] = None,
) -> None:
    """Turn a question about a command into a recorded terminal demo."""
    # `update` is already installing the release the notice would name.
    if ctx.invoked_subcommand != 'update':
        notify(UPDATE_CONFIG)


def open_page(path: Path) -> None:
    opener = 'open' if platform.system() == 'Darwin' else 'xdg-open'
    subprocess.Popen(
        [opener, path.resolve().as_uri()],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def preflight(cli: str | None = None, routing: config_module.Routing | None = None) -> None:
    """Stop before any work, naming every missing prerequisite in one message."""
    problems = []
    if shutil.which('claude') is None:
        problems.append(
            'claude is not on PATH. ask and investigate write the tape through Claude Code.\n'
            'Install it from https://code.claude.com/docs/en/setup, then run: claude auth login'
        )
    elif ask_module.claude_logged_in() is False:
        problems.append('claude is installed but not logged in. Run: claude auth login\nSetting ANTHROPIC_API_KEY works too.')
    if cli is not None and shutil.which(cli) is None:
        problems.append(f'{cli} is not installed, so there is no help to read. --cli takes a command on your PATH.')
    if routing is not None and not routing.configured:
        problems.append(config_module.ROUTING_HELP.format(path=config_module.CONFIG_PATH))
    if problems:
        err.print('\n\n'.join(problems), markup=False, highlight=False, soft_wrap=True)
        raise typer.Exit(1)


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
    name = tape.get('name') or slug
    err.print(f'play it again with:  runthrough play {shlex.quote(str(name).lower())}', markup=False, highlight=False)
    return page_path


def kept_tapes(library: Path) -> list[dict]:
    """Every tape in the library, in the order `library` numbers them."""
    kept = []
    for tape in sorted(library.glob('*.tape.yml')):
        loaded = yaml.safe_load(tape.read_text()) or {}
        page = tape.with_name(tape.name.replace('.tape.yml', '.html'))
        kept.append(
            {
                'name': str(loaded.get('name') or tape.name.removesuffix('.tape.yml')),
                'title': loaded.get('title', ''),
                'tags': loaded.get('tags', []),
                'steps': len(loaded.get('steps', [])),
                'tape': str(tape),
                'page': str(page) if page.exists() else None,
            }
        )
    return kept


def print_numbered(kept: list[dict]) -> None:
    for number, entry in enumerate(kept, 1):
        mark = '' if entry['page'] else '  (never recorded)'
        print(f'{number:>3}  {entry["name"]}  —  {entry["title"]}{mark}')
    sys.stdout.flush()


def stem(entry: dict) -> str:
    return Path(entry['tape']).name.removesuffix('.tape.yml')


def choose_tape(given: str | None, library: Path) -> Path:
    """Read a tape path, a number from `library`, or any part of a kept tape's name."""
    if given and Path(given).expanduser().is_file():
        return Path(given).expanduser()
    kept = kept_tapes(library)
    if not kept:
        err.print(f'No demos kept in {library} yet. Make one with:  runthrough ask --cli git "what changed"', markup=False)
        raise typer.Exit(1)
    if given is None:
        print_numbered(kept)
        if not sys.stdin.isatty():
            err.print('Name one:  runthrough play <number or name>', markup=False)
            raise typer.Exit(1)
        given = input('play which? ').strip()
    if given.isdigit() and 1 <= int(given) <= len(kept):
        return Path(kept[int(given) - 1]['tape'])
    wanted = given.lower()
    exact = [e for e in kept if wanted in (e['name'].lower(), stem(e))]
    matches = exact or [e for e in kept if wanted in e['name'].lower() or wanted in stem(e)]
    if len(matches) == 1:
        return Path(matches[0]['tape'])
    err.print(f'{"Several" if matches else "No"} kept demos match "{given}". Pick one by number:', markup=False)
    print_numbered(kept)
    raise typer.Exit(1)


@app.command(
    rich_help_panel='Make a demo',
    epilog=examples(
        ('runthrough ask --cli git "who changed what"', 'write a tape, record on y'),
        ('runthrough ask --cli git --yes "who changed what"', 'record without asking'),
    ),
)
def ask(
    question: Annotated[list[str], typer.Argument(metavar='QUESTION...', help='What you want shown, in English.')],
    cli: Annotated[str, typer.Option('--cli', metavar='COMMAND', help='The installed command to demonstrate, such as git.')],
    sandbox: Annotated[
        bool,
        typer.Option(
            '--sandbox', help='For a demo that writes: point the XDG roots at sandbox/ beside the page, which is kept between recordings.'
        ),
    ] = False,
    yes: Annotated[bool, typer.Option('--yes', help='Record without confirming the tape.')] = False,
    budget: Annotated[int, typer.Option('--budget', help='Help-text characters to read.')] = 40000,
    library: Annotated[Path, typer.Option('--library', help='Where tapes are kept.')] = DEFAULT_LIBRARY,
    watch: Annotated[bool, typer.Option('--watch/--no-watch', help='Open the page when done.')] = True,
) -> None:
    """Demo one command: Claude reads its --help, writes a tape, and you record it."""
    preflight(cli=cli)
    asked = ' '.join(question)
    err.print(f'reading {cli} help')
    help_text = ask_module.gather_help(cli, budget)

    err.print('authoring tape')
    tape = ask_module.validate_tape(ask_module.author_tape(cli, asked, help_text, sandbox), cli)
    if sandbox:
        tape['sandbox'] = 'xdg'

    produce(tape, asked, library, confirm=not yes, watch=watch)


@app.command(
    rich_help_panel='Make a demo',
    epilog=examples(
        ('runthrough investigate "what failed today"', 'probe data, write a tape'),
        ('runthrough investigate --yes "what failed today"', 'record without asking'),
    ),
)
def investigate(
    question: Annotated[list[str], typer.Argument(metavar='QUESTION...', help='What you want answered, in English.')],
    yes: Annotated[bool, typer.Option('--yes', help='Record without confirming the tape.')] = False,
    budget: Annotated[int, typer.Option('--budget', help='Help-text characters to read.')] = 30000,
    library: Annotated[Path, typer.Option('--library', help='Where tapes are kept.')] = DEFAULT_LIBRARY,
    watch: Annotated[bool, typer.Option('--watch/--no-watch', help='Open the page when done.')] = True,
) -> None:
    """Demo a question that spans tools: it picks the tools, writes a tape, and you record it."""
    routing = config_module.load().routing
    preflight(routing=routing)
    asked = ' '.join(question)

    err.print('routing')
    paths = investigate_module.route(asked, routing)
    err.print(f'  tools: {paths}')

    pages: list[str] = []
    allowed = set(investigate_module.READ_COMMANDS)
    for path in paths:
        parts = path.split()
        allowed.add(parts[0])
        text = ask_module.gather_help(parts[0], budget // max(1, len(paths))) if len(parts) == 1 else ask_module.run_help(parts)
        if text.strip():
            pages.append(f'$ {path} --help\n{text}')
    help_text = '\n\n'.join(pages)

    err.print('probing')
    observations = investigate_module.probe(asked, help_text, allowed)

    err.print('authoring')
    tape = investigate_module.author(asked, help_text, observations)
    if 'steps' not in tape:
        raise typer.BadParameter('model did not return a tape')
    for step in tape['steps']:
        investigate_module.check_command(step['run'], allowed)

    produce(tape, asked, library, confirm=not yes, watch=watch)


@app.command(
    rich_help_panel='Use what you kept',
    epilog=examples(
        ('runthrough play', 'list your demos and pick one'),
        ('runthrough play 2', 'the second demo library lists'),
        ('runthrough play trace a symbol', 'any part of a demo name'),
        ('runthrough play demo.tape.yml --no-watch', 'a tape file, with no browser'),
    ),
)
def play(
    which: Annotated[
        list[str] | None, typer.Argument(metavar='[DEMO...]', help='A number or name from library, or a tape file. Leave out to pick.')
    ] = None,
    out: Annotated[Path | None, typer.Option('--out', metavar='PATH', help='Where to write the page.')] = None,
    cast: Annotated[Path | None, typer.Option('--cast', metavar='PATH', help='Also write an asciicast v2 file.')] = None,
    fps: Annotated[int, typer.Option('--fps', help='Screen samples per second.')] = 14,
    library: Annotated[Path, typer.Option('--library', help='Where tapes are kept.')] = DEFAULT_LIBRARY,
    watch: Annotated[bool, typer.Option('--watch/--no-watch', help='Open the page when done.')] = True,
) -> None:
    """Run a demo's commands again and open the new recording."""
    tape = choose_tape(' '.join(which) if which else None, library)
    page = out or tape.with_suffix('').with_suffix('.html')
    record(tape, page, cast_path=cast, fps=fps)
    if watch:
        open_page(page)


@app.command(
    rich_help_panel='Use what you kept',
    epilog=examples(
        ('runthrough library', 'every kept tape, and which have no page'),
        ('runthrough library --json', 'the same list as JSON, for a script'),
    ),
)
def library(
    path: Annotated[Path, typer.Option('--library', help='Where tapes are kept.')] = DEFAULT_LIBRARY,
    as_json: Annotated[bool, typer.Option('--json', help='Output as JSON to stdout.')] = False,
) -> None:
    """List the demos you kept, numbered for play."""
    recorded = kept_tapes(path)
    if as_json:
        print(json.dumps(recorded))
        return

    if not recorded:
        err.print(f'Nothing recorded yet in {path}.', markup=False)
        err.print('Record one with:  runthrough ask --cli <command> "what you want shown"', markup=False)
        return

    print_numbered(recorded)
    err.print('\nPlay one with:  runthrough play <number or name>', markup=False)


@app.command(
    rich_help_panel='Update',
    epilog=examples(
        ('runthrough update --check', 'whether a newer release exists'),
        ('runthrough update', 'install the newest release over this one'),
    ),
)
def update(
    check_only: Annotated[bool, typer.Option('--check', help='Report whether an update is available without installing it.')] = False,
) -> None:
    """Update runthrough to the latest GitHub release."""
    run_update(UPDATE_CONFIG, check_only=check_only)


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == '__main__':
    main()
