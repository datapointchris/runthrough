"""The retry exists because of one observed failure, so that is what it is tested on.

`claude -p` returns only the model's final message. When the model writes the tape
and then adds a closing remark, the JSON is gone rather than malformed, and nothing
in the reply can be salvaged — only asking again recovers it.
"""

from __future__ import annotations

import pytest

from runthrough import ask

TAPE = '{"name": "A Tape", "steps": [{"run": "notes status", "pause": 1.0}]}'
CLOSING_REMARK = 'The tape JSON above was the deliverable; the work is complete.'


@pytest.fixture
def replies(monkeypatch):
    """Queue up what the model returns, and record what it was asked."""
    prompts: list[str] = []

    def queue(*answers: str) -> list[str]:
        remaining = list(answers)

        def fake_ask_model(prompt: str, **_: object) -> str:
            prompts.append(prompt)
            return remaining.pop(0)

        monkeypatch.setattr(ask, 'ask_model', fake_ask_model)
        return prompts

    return queue


class TestRequestTape:
    def test_a_good_reply_is_not_retried(self, replies):
        prompts = replies(TAPE)
        assert ask.request_tape('go')['name'] == 'A Tape'
        assert len(prompts) == 1

    def test_a_closing_remark_with_no_tape_is_retried(self, replies):
        """The exact reply seen live."""
        prompts = replies(CLOSING_REMARK, TAPE)
        assert ask.request_tape('go')['name'] == 'A Tape'
        assert len(prompts) == 2

    def test_the_retry_says_the_json_is_the_only_thing_read(self, replies):
        prompts = replies(CLOSING_REMARK, TAPE)
        ask.request_tape('go')
        assert prompts[0] == 'go'
        assert 'the only thing read' in prompts[1]

    def test_two_bad_replies_give_up_rather_than_loop(self, replies):
        prompts = replies(CLOSING_REMARK, CLOSING_REMARK)
        with pytest.raises(SystemExit, match='did not return a tape'):
            ask.request_tape('go')
        assert len(prompts) == 2
