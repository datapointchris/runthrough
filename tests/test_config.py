"""What the machine supplies, and how it is read.

The include-following cases are the ones that matter. A generated theme reaches
the terminal through `config-file` includes, so a parser that does not follow them
silently records in fallback colours and nothing looks broken.

The config module is also the one place that reads the machine's settings, and a
walk over the package holds every other module to it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import runthrough
from runthrough import config
from runthrough.recorder import load_terminal_font
from runthrough.recorder import load_terminal_theme

PACKAGE = Path(runthrough.__file__).parent


def is_environ(node: ast.AST) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == 'environ') or (isinstance(node, ast.Name) and node.id == 'environ')


def reads_a_setting(node: ast.AST) -> bool:
    """`os.environ[...]`, `os.environ.get`, `getenv` or `Path.home()`: every way a module
    looks a machine's value up for itself."""
    if isinstance(node, ast.Subscript):
        return is_environ(node.value)
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == 'getenv'
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr == 'getenv' or (func.attr == 'get' and is_environ(func.value)):
        return True
    return func.attr == 'home' and isinstance(func.value, ast.Name) and func.value.id == 'Path'


def setting_reads() -> list[str]:
    found = []
    for path in sorted(PACKAGE.rglob('*.py')):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Subscript | ast.Call) and reads_a_setting(node):
                found.append(f'{path.relative_to(PACKAGE)}:{node.lineno}')
    return found


def test_only_the_config_module_reads_the_machines_settings():
    """A path or command name a module looks up for itself is a machine's specifics
    written into the source, which the tool must take from its config. The config
    module's own reads are asserted too, so a walk that finds nothing cannot pass."""
    reads = setting_reads()

    assert any(read.startswith('config.py:') for read in reads), 'the walk found no read at all, so it proves nothing'
    assert [read for read in reads if not read.startswith('config.py:')] == []


@pytest.fixture
def terminal(tmp_path):
    def write(name: str, body: str):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        return path

    return write


class TestReadTerminalConfig:
    def test_reads_plain_settings(self, terminal):
        path = terminal('config', 'font-family = Hack\nfont-size = 13\n')
        assert config.read_terminal_config(path)['font-family'] == ['Hack']

    def test_ignores_comments_and_blank_lines(self, terminal):
        path = terminal('config', '# a comment\n\nfont-size = 11\n')
        assert config.read_terminal_config(path) == {'font-size': ['11']}

    def test_follows_an_include_relative_to_the_including_file(self, terminal):
        terminal('themes/current.conf', 'background = #101010\n')
        path = terminal('config', 'config-file = themes/current.conf\n')
        assert config.read_terminal_config(path)['background'] == ['#101010']

    def test_an_optional_include_marker_is_not_part_of_the_path(self, terminal):
        """`?` is ghostty's suppress-if-absent marker. Treating it as a path
        character silently yields no palette at all."""
        terminal('themes/current.conf', 'background = #101010\n')
        path = terminal('config', 'config-file = ?themes/current.conf\n')
        assert config.read_terminal_config(path)['background'] == ['#101010']

    def test_a_missing_optional_include_is_not_an_error(self, terminal):
        path = terminal('config', 'config-file = ?nope.conf\nfont-size = 12\n')
        assert config.read_terminal_config(path)['font-size'] == ['12']

    def test_an_include_cycle_terminates(self, terminal):
        terminal('b.conf', 'config-file = config\nfont-size = 9\n')
        path = terminal('config', 'config-file = b.conf\n')
        assert config.read_terminal_config(path)['font-size'] == ['9']

    def test_an_absent_file_yields_nothing(self, tmp_path):
        assert config.read_terminal_config(tmp_path / 'missing') == {}


class TestAppearanceFromSettings:
    def test_palette_entries_become_ansi_colours(self):
        settings = {'palette': ['0=#26211f', '2=#99af6b'], 'foreground': ['#e6d5c2'], 'background': ['#1d1917']}
        palette, foreground, background, ansi = load_terminal_theme(settings)
        assert palette['green'] == '#99af6b'
        assert (foreground, background) == ('#e6d5c2', '#1d1917')
        assert ansi[0] == '#26211f'

    def test_yellow_is_an_alias_of_brown(self):
        palette, *_ = load_terminal_theme({'palette': ['3=#fcba81']})
        assert palette['yellow'] == palette['brown'] == '#fcba81'

    def test_an_empty_config_still_produces_a_usable_palette(self):
        palette, foreground, background, ansi = load_terminal_theme({})
        assert len(ansi) == 16
        assert foreground and background

    def test_config_overrides_the_terminal_font(self):
        settings = {'font-family': ['Hack'], 'font-size': ['13']}
        appearance = config.Appearance(font_family='Comic Shanns', font_size=20)
        assert load_terminal_font(settings, appearance) == ('Comic Shanns', 20)

    def test_the_terminal_font_is_used_when_config_is_silent(self):
        settings = {'font-family': ['"Hack Nerd Font"'], 'font-size': ['14']}
        assert load_terminal_font(settings, config.Appearance()) == ('Hack Nerd Font', 14)


class TestRouting:
    def test_both_halves_are_needed(self):
        assert not config.Routing(inventory='mytools list').configured
        assert config.Routing(inventory='a', search='b {query}').configured

    def test_the_query_is_substituted_and_quoted(self):
        routing = config.Routing(inventory='x', search='search {query} --limit 8')
        assert routing.search_command("it's here") == "search 'it'\"'\"'s here' --limit 8"

    def test_no_search_configured_yields_no_command(self):
        assert config.Routing().search_command('anything') is None


class TestDataHome:
    def test_the_library_lives_under_xdg_data_home_with_the_standard_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
        assert config.xdg_data_home() == tmp_path / 'data'
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.setenv('XDG_DATA_HOME', '')
        assert config.xdg_data_home() == tmp_path / '.local' / 'share'


class TestLoad:
    def test_a_missing_file_is_an_empty_config_rather_than_an_error(self, tmp_path):
        loaded = config.load(tmp_path / 'nope.yml')
        assert not loaded.routing.configured
        assert loaded.appearance.font_family is None

    def test_routing_and_appearance_are_read(self, tmp_path):
        path = tmp_path / 'config.yml'
        path.write_text(
            'routing:\n  inventory: mytools list\n  search: mynotes {query}\nappearance:\n  font_family: Iosevka\n  font_size: 15\n'
        )
        loaded = config.load(path)
        assert loaded.routing.configured
        assert (loaded.appearance.font_family, loaded.appearance.font_size) == ('Iosevka', 15)
