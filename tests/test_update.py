"""`runthrough update` and the update notice share one pyselfupdate config."""

from typer.testing import CliRunner

from runthrough import cli

runner = CliRunner()


def test_update_installs_the_published_release(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, 'run_update', lambda config, **kwargs: calls.append((config, kwargs)))

    result = runner.invoke(cli.app, ['update', '--check'])

    assert result.exit_code == 0
    config, kwargs = calls[0]
    assert (config.tool, config.owner) == ('runthrough', 'datapointchris')
    assert kwargs == {'check_only': True}


def test_update_does_not_also_print_the_update_notice(monkeypatch, tmp_path):
    # The notice would name the release the command is already installing.
    monkeypatch.setattr(cli, 'run_update', lambda config, **kwargs: None)
    notices = []
    monkeypatch.setattr(cli, 'notify', notices.append)

    runner.invoke(cli.app, ['update'])
    runner.invoke(cli.app, ['library', '--library', str(tmp_path)])

    assert notices == [cli.UPDATE_CONFIG]
