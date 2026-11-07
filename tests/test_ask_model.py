"""The argv is the whole confinement, so it is asserted rather than trusted.

`--tools ""` leaves the session no tool, `--setting-sources ""` lets no settings file
grant one back, and `--permission-prompts none` refuses anything else rather than
waiting. `--allowed-tools` confines nothing, because it pre-approves tools and leaves
the rest reachable.
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
        stdout = '[{"type": "result", "subtype": "success", "result": "{}"}]'
        stderr = ''

    def fake_run(argv, **_: object):
        seen['argv'] = argv
        return Completed()

    monkeypatch.setattr(ask.subprocess, 'run', fake_run)
    ask.ask_model('a prompt')
    return seen['argv']


def flag(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


class TestModelArgv:
    def test_the_session_has_no_tool_and_no_settings_file_grants_one(self, recorded_argv):
        assert recorded_argv[:2] == ['claude', '-p']
        assert flag(recorded_argv, '--tools') == ''
        assert flag(recorded_argv, '--setting-sources') == ''
        assert flag(recorded_argv, '--permission-prompts') == 'none'
        assert '--safe-mode' in recorded_argv
        assert '--allowed-tools' not in recorded_argv

    def test_the_prompt_never_reaches_argv(self, recorded_argv):
        assert 'a prompt' not in recorded_argv
