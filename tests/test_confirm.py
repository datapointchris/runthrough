"""A script that pipes into `ask` or `investigate` gets a usage error before any model call."""

import pytest
from typer.testing import CliRunner

from runthrough import cli

runner = CliRunner()


@pytest.mark.parametrize('command', [['ask', '--cli', 'git', 'what changed'], ['investigate', 'what failed']])
def test_no_terminal_and_no_yes_stops_before_any_work(monkeypatch, command):
    monkeypatch.setattr(cli, 'notify', lambda config: None)
    started = []
    monkeypatch.setattr(cli, 'preflight', lambda **kwargs: started.append(kwargs))

    result = runner.invoke(cli.app, command)

    assert result.exit_code == 2
    assert started == []
