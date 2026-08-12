"""What this machine supplies: how to route a question, and what the terminal looks like.

Both used to be literals in the source — two commands from one person's toolkit, and
one theme generator's output layout. Neither is a property of recording a terminal,
so both are read from here and the tool works without either.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

import yaml


def xdg_config_home() -> Path:
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))


CONFIG_PATH = xdg_config_home() / 'runthrough' / 'config.yml'

ROUTING_HELP = """\
`investigate` needs to know what tools exist on this machine and how to search for
them. Set both in {path}:

    routing:
      inventory: <a command that lists your tools>
      search: <a command that searches your notes, with {{query}} where the text goes>

Anything that prints a list and anything that searches text will do — a registry
command, `ls ~/.local/bin`, a grep over your notes:

    routing:
      inventory: mytools list
      search: mynotes search {{query}} --limit 8

`runthrough ask --cli <command>` needs none of this — it reads one command's own help.\
"""


@dataclass
class Routing:
    inventory: str | None = None
    search: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.inventory and self.search)

    def search_command(self, query: str) -> str | None:
        if not self.search:
            return None
        return self.search.replace('{query}', shell_quote(query))


@dataclass
class Appearance:
    """Where to read the palette and font from, so a recording looks like the terminal
    it was taken in. Defaults to ghostty's own config; any file in `key = value` form
    with `palette = N=#rrggbb` entries will do."""

    terminal_config: Path | None = None
    font_family: str | None = None
    font_size: int | None = None


@dataclass
class Config:
    routing: Routing = field(default_factory=Routing)
    appearance: Appearance = field(default_factory=Appearance)


def shell_quote(text: str) -> str:
    import shlex

    return shlex.quote(text)


def default_terminal_config() -> Path:
    if platform.system() == 'Darwin':
        mac = Path.home() / 'Library/Application Support/com.mitchellh.ghostty/config'
        if mac.exists():
            return mac
    return xdg_config_home() / 'ghostty' / 'config'


def load(path: Path | None = None) -> Config:
    source = path or CONFIG_PATH
    if not source.exists():
        return Config()

    raw = yaml.safe_load(source.read_text()) or {}
    routing = raw.get('routing') or {}
    appearance = raw.get('appearance') or {}
    terminal_config = appearance.get('terminal_config')

    return Config(
        routing=Routing(
            inventory=routing.get('inventory'),
            search=routing.get('search'),
        ),
        appearance=Appearance(
            terminal_config=Path(terminal_config).expanduser() if terminal_config else None,
            font_family=appearance.get('font_family'),
            font_size=appearance.get('font_size'),
        ),
    )


def read_terminal_config(path: Path, seen: set[Path] | None = None) -> dict[str, list[str]]:
    """Parse a ghostty-style config, following `config-file` includes.

    Following includes is what makes a generated theme work without naming the
    generator's layout: a config that points at `themes/current.conf` resolves the
    same way as one declaring its palette inline.
    """
    settings: dict[str, list[str]] = {}
    seen = seen if seen is not None else set()

    resolved = path.expanduser()
    if not resolved.is_file() or resolved in seen:
        return settings
    seen.add(resolved)

    for line in resolved.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        key, separator, value = stripped.partition('=')
        if not separator:
            continue
        key, value = key.strip(), value.strip()

        if key == 'config-file':
            # A leading `?` is ghostty's "optional include" — suppress errors when the
            # file is absent. It is a marker, not part of the path.
            included = Path(value.removeprefix('?')).expanduser()
            if not included.is_absolute():
                included = resolved.parent / included
            for name, values in read_terminal_config(included, seen).items():
                settings.setdefault(name, []).extend(values)
        else:
            settings.setdefault(key, []).append(value)

    return settings
