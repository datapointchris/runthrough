"""The guard decides what is allowed to execute, so its edges are the tests.

Every case here is a real failure or a real near-miss from building the tool,
not a hypothetical: the jq pipes and the `--verb apply` filter both rejected
legitimate commands before they were fixed.
"""

from __future__ import annotations

import pytest

from runthrough.fleet import READ_COMMANDS
from runthrough.fleet import check_command
from runthrough.fleet import segments
from runthrough.fleet import split_pipeline

ALLOWED = READ_COMMANDS | {'dotfiles', 'indy', 'toolbox'}


class TestSplitPipeline:
    def test_splits_on_shell_pipes(self):
        assert split_pipeline('dotfiles report list | rg macmini') == [
            'dotfiles report list',
            'rg macmini',
        ]

    def test_a_jq_filters_pipes_are_not_shell_pipes(self):
        """This rejected the commands most worth teaching."""
        stages = split_pipeline("""jq '..|objects|select(.kind)'""")
        assert len(stages) == 1

    def test_a_quoted_pipe_is_not_a_split(self):
        assert len(split_pipeline("rg '^a|^b' file.txt")) == 1

    def test_empty_stages_are_dropped(self):
        assert split_pipeline('  ') == []


class TestSegments:
    def test_command_substitution_is_inspected_too(self):
        found = segments('jq . "$(dotfiles report path 20260811Z-macmini-apply)"')
        assert any(stage.startswith('jq') for stage in found)
        assert any(stage.startswith('dotfiles report path') for stage in found)


class TestCheckCommand:
    @pytest.mark.parametrize(
        'command',
        [
            'dotfiles report list',
            'dotfiles report list | rg macmini',
            'indy search "coordinate axes" --repo dotfiles -n 3',
            'jq . "$(dotfiles report path abc123)"',
        ],
    )
    def test_accepts_what_a_person_would_type(self, command):
        check_command(command, ALLOWED)

    def test_accepts_a_real_pipe_into_a_jq_filter_full_of_pipes(self):
        """Four `|` characters, one of them a shell pipe. Counting the character
        instead of splitting on it rejected this, which is the whole idiom."""
        check_command("dotfiles report list | jq '..|objects|select(.a)|.b'", ALLOWED)

    def test_accepts_a_mutating_word_as_a_flag_value(self):
        """`--verb apply` filters for applies; it does not apply anything."""
        check_command('dotfiles report list --verb apply', ALLOWED)

    def test_rejects_a_mutating_subcommand(self):
        with pytest.raises(SystemExit, match='mutating verb'):
            check_command('dotfiles apply symlinks', ALLOWED)

    @pytest.mark.parametrize(
        'command',
        [
            'dotfiles report list > out.txt',
            'dotfiles report list >> out.txt',
            'dotfiles report list && rg macmini',
            'dotfiles report list; rg macmini',
            'bash -c "dotfiles report list"',
            'sudo dotfiles report list',
            'ssh macmini dotfiles report list',
        ],
    )
    def test_rejects_what_a_person_would_not_type_inline(self, command):
        with pytest.raises(SystemExit):
            check_command(command, ALLOWED)

    def test_rejects_a_loop(self):
        with pytest.raises(SystemExit, match='not something a person types'):
            check_command('for f in *.json do jq . $f done', ALLOWED)

    def test_rejects_a_command_outside_the_allowlist(self):
        with pytest.raises(SystemExit, match='allowlist'):
            check_command('curl https://example.com', ALLOWED)

    def test_checks_every_stage_not_only_the_first(self):
        with pytest.raises(SystemExit, match='allowlist'):
            check_command('dotfiles report list | xargs rm', ALLOWED)

    def test_rejects_too_many_stages(self):
        with pytest.raises(SystemExit, match='pipe stages'):
            check_command('cat a | sort | uniq | head | wc -l', ALLOWED)

    def test_rejects_something_too_long_to_type(self):
        with pytest.raises(SystemExit, match='too long'):
            check_command('indy search "' + 'x' * 200 + '"', ALLOWED)
