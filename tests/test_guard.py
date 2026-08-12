"""The guard decides what is allowed to execute, so its edges are the tests.

Every case here is a real failure or a real near-miss from building the tool,
not a hypothetical: the jq pipes and the `--verb apply` filter both rejected
legitimate commands before they were fixed.
"""

from __future__ import annotations

import pytest

from runthrough.investigate import READ_COMMANDS
from runthrough.investigate import check_command
from runthrough.investigate import segments
from runthrough.investigate import split_pipeline

ALLOWED = READ_COMMANDS | {'deploy', 'notes'}


class TestSplitPipeline:
    def test_splits_on_shell_pipes(self):
        assert split_pipeline('deploy runs list | rg staging') == [
            'deploy runs list',
            'rg staging',
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
        found = segments('jq . "$(deploy runs path 20260811Z-staging)"')
        assert any(stage.startswith('jq') for stage in found)
        assert any(stage.startswith('deploy runs path') for stage in found)


class TestCheckCommand:
    @pytest.mark.parametrize(
        'command',
        [
            'deploy runs list',
            'deploy runs list | rg staging',
            'notes search "deployment rollback" --limit 3',
            'jq . "$(deploy runs path abc123)"',
        ],
    )
    def test_accepts_what_a_person_would_type(self, command):
        check_command(command, ALLOWED)

    def test_accepts_a_real_pipe_into_a_jq_filter_full_of_pipes(self):
        """Four `|` characters, one of them a shell pipe. Counting the character
        instead of splitting on it rejected this, which is the whole idiom."""
        check_command("deploy runs list | jq '..|objects|select(.a)|.b'", ALLOWED)

    def test_accepts_a_mutating_word_as_a_flag_value(self):
        """`--verb apply` filters for applies; it does not apply anything."""
        check_command('deploy runs list --verb apply', ALLOWED)

    def test_rejects_a_mutating_subcommand(self):
        with pytest.raises(SystemExit, match='mutating verb'):
            check_command('deploy apply production', ALLOWED)

    @pytest.mark.parametrize(
        'command',
        [
            'deploy runs list > out.txt',
            'deploy runs list >> out.txt',
            'deploy runs list && rg staging',
            'deploy runs list; rg staging',
            'bash -c "deploy runs list"',
            'sudo deploy runs list',
            'ssh buildbox deploy runs list',
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
            check_command('deploy runs list | xargs rm', ALLOWED)

    def test_rejects_too_many_stages(self):
        with pytest.raises(SystemExit, match='pipe stages'):
            check_command('cat a | sort | uniq | head | wc -l', ALLOWED)

    def test_rejects_something_too_long_to_type(self):
        with pytest.raises(SystemExit, match='too long'):
            check_command('notes search "' + 'x' * 200 + '"', ALLOWED)
