"""The argv is the whole confinement, so it is asserted rather than trusted.

An allow list does not restrict a session — `claude -p --allowedTools ""` runs Bash
regardless, because that flag pre-approves tools instead of confining the session to
them. Only a deny list keeps the model to reading its stdin and returning a tape.
"""

from __future__ import annotations

import pytest

from runthrough import ask


@pytest.fixture
def recorded_argv(monkeypatch):
    """Run ask_model without a model, and hand back what it tried to launch."""
    seen: dict[str, list[str]] = {}

    class Completed:
        returncode = 0
        stdout = '{"steps": []}'
        stderr = ''

    def fake_run(argv, **_: object):
        seen['argv'] = argv
        return Completed()

    monkeypatch.setattr(ask.subprocess, 'run', fake_run)
    ask.ask_model('a prompt')
    return seen['argv']


class TestModelArgv:
    def test_the_session_is_confined_by_a_deny_list(self, recorded_argv):
        assert '--disallowed-tools' in recorded_argv

    def test_an_allow_list_is_never_what_confines_it(self, recorded_argv):
        assert '--allowedTools' not in recorded_argv
        assert '--allowed-tools' not in recorded_argv

    def test_every_tool_that_reaches_the_machine_is_denied(self, recorded_argv):
        denied = set(recorded_argv[recorded_argv.index('--disallowed-tools') + 1].split(','))
        assert {'Bash', 'Read', 'Write', 'Edit', 'NotebookEdit', 'Glob', 'Grep', 'WebFetch', 'WebSearch', 'Task'} <= denied

    def test_the_flag_carries_its_list_as_the_next_argument(self, recorded_argv):
        assert recorded_argv[recorded_argv.index('--disallowed-tools') + 1] == ','.join(ask.DENIED_TOOLS)

    def test_it_is_a_headless_claude_call(self, recorded_argv):
        assert recorded_argv[:2] == ['claude', '-p']
