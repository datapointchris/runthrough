"""Recording a tape end to end: real commands under a pty, into a page and an asciicast.

Each step prints text its own command line does not contain, so finding that text
proves it came from the command that ran rather than from the typed prompt. What
only a look at the page catches, such as a font that did not load, is still checked
by recording a page and watching it.
"""

from __future__ import annotations

import json
import os

import pytest

from runthrough.errors import StepTimedOut
from runthrough.recorder import execute_in_pty
from runthrough.recorder import record

TAPE = """\
title: Two steps
columns: 40
rows: 6
typing_speed: 0.001
steps:
  - run: printf '%s-%s\\n' alpha beta
    narrate: first
    pause: 0.1
  - run: printf '%s+%s\\n' gamma delta
    narrate: second
    pause: 0.1
"""


def test_record_writes_each_steps_output_to_the_page_and_the_cast(tmp_path):
    tape = tmp_path / 'tape.yaml'
    tape.write_text(TAPE)
    page = tmp_path / 'page.html'
    cast = tmp_path / 'page.cast'

    record(tape, page, cast_path=cast, sandbox_root=tmp_path / 'sandbox')

    header, *events = [json.loads(line) for line in cast.read_text().splitlines()]
    assert header['version'] == 2
    assert (header['width'], header['height']) == (40, 6)
    assert all(kind == 'o' for _, kind, _ in events)
    printed = ''.join(data for _, _, data in events)
    assert 'alpha-beta' in printed
    assert 'gamma+delta' in printed

    markup = page.read_text()
    assert 'alpha-beta' in markup
    assert 'gamma+delta' in markup


def test_a_step_past_its_deadline_stops_the_recording():
    with pytest.raises(StepTimedOut):
        execute_in_pty('sleep 30', dict(os.environ), 40, 6, deadline=0.5)
