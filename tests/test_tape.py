"""Parsing what the model returns, and reading help well enough to prompt with."""

from __future__ import annotations

import pytest

from runthrough.ask import extract_subcommands
from runthrough.ask import parse_tape
from runthrough.ask import strip_ansi
from runthrough.ask import strip_fences
from runthrough.recorder import mix

RICH_HELP = """\
 Usage: indy [OPTIONS] COMMAND [ARGS]...

╭─ Commands ───────────────────────────────────────────╮
│ status        Show index health.                     │
│ search        Semantic search across indexed code.   │
│ errors-clear  Remove all error records.              │
╰──────────────────────────────────────────────────────╯
"""

COBRA_HELP = """\
Usage:
  icb [command]

Available Commands:
  articles           List and manage your saved articles
  projects           List, inspect, and manage your projects

Flags:
  -h, --help   help for icb
"""


class TestParseTape:
    def test_a_command_carrying_a_colon_survives(self):
        """The failure that moved the wire format off YAML."""
        raw = '{"steps": [{"run": "jq \'select(.a)|.b+\\": \\"+.c\'", "pause": 1.0}]}'
        assert 'jq' in parse_tape(raw)['steps'][0]['run']

    def test_prose_around_the_json_is_ignored(self):
        tape = parse_tape('Here is the tape:\n{"name": "A", "steps": []}\nHope that helps.')
        assert tape['name'] == 'A'

    def test_missing_json_is_an_error_naming_what_came_back(self):
        with pytest.raises(SystemExit, match='did not return a tape'):
            parse_tape('I cannot do that.')


class TestStripFences:
    @pytest.mark.parametrize('label', ['', 'json', 'yaml', 'yml'])
    def test_a_fenced_block_is_unwrapped_whatever_it_claims_to_be(self, label):
        assert strip_fences(f'```{label}\n{{"a": 1}}\n```').strip() == '{"a": 1}'

    def test_unfenced_text_passes_through(self):
        assert strip_fences('{"a": 1}') == '{"a": 1}'


class TestExtractSubcommands:
    def test_reads_a_rich_panel(self):
        assert extract_subcommands(RICH_HELP) == ['status', 'search', 'errors-clear']

    def test_reads_a_cobra_list(self):
        assert extract_subcommands(COBRA_HELP) == ['articles', 'projects']

    def test_stops_before_the_flags_section(self):
        assert 'help' not in extract_subcommands(COBRA_HELP)

    def test_help_with_no_commands_yields_none(self):
        assert extract_subcommands('Usage: rg [OPTIONS] PATTERN') == []


class TestStripAnsi:
    def test_removes_colour_and_keeps_the_text(self):
        assert strip_ansi('\x1b[1;36mindex_into\x1b[0m') == 'index_into'


class TestMix:
    def test_no_blend_returns_the_first_colour(self):
        assert mix('#102030', '#ffffff', 0.0) == '#102030'

    def test_full_blend_returns_the_second(self):
        assert mix('#102030', '#ffffff', 1.0) == '#ffffff'

    def test_halfway_is_halfway(self):
        assert mix('#000000', '#ffffff', 0.5) == '#808080'
