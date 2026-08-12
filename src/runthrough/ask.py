"""Ask for a demo in English, get a recording of the real commands.

The help text is gathered deterministically here and handed to the model as
plain text — the model never runs anything. It only writes the tape, and the
tape is what gets executed, after you have seen it.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap

ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
COMMAND_HEADING = re.compile(r'(Available Commands:|Commands\s*$|Commands\s*[─╮])')
SUBCOMMAND = re.compile(r'^[│|]?\s{0,4}([a-z][a-z0-9-]{1,30})\s{2,}\S')
CHAINING = re.compile(r'[;&|`]|\$\(|>>|(?<![0-9])>')

TAPE_SCHEMA = """\
{
  "name": "<2-4 word page name, title case>",
  "title": "<one line, sentence case, says what the sequence achieves>",
  "description": "<two or three sentences: what this shows and why the order matters>",
  "tags": ["<cli>", "<topic>", "<topic>"],
  "cli": "<cli>",
  "sandbox": "none | xdg",
  "columns": 100,
  "rows": 22,
  "typing_speed": 0.03,
  "max_gap": 1.0,
  "steps": [
    {"narrate": "<one sentence, present tense, says what this step is for>",
     "run": "<a single command>",
     "pause": 3.0}
  ]
}"""


def strip_ansi(text: str) -> str:
    return ANSI.sub('', text)


def run_help(argv: list[str]) -> str:
    try:
        result = subprocess.run(argv + ['--help'], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return strip_ansi(result.stdout or result.stderr)


def extract_subcommands(help_text: str) -> list[str]:
    names: list[str] = []
    inside = False
    for line in help_text.splitlines():
        if COMMAND_HEADING.search(line):
            inside = True
            continue
        if not inside:
            continue
        if line.strip().startswith('╰') or re.match(r'^\s*(Flags|Options|Usage)', line):
            inside = False
            continue
        match = SUBCOMMAND.match(line)
        if match and match.group(1) not in names:
            names.append(match.group(1))
    return names


def gather_help(cli: str, budget: int) -> str:
    """Walk the subcommand tree breadth-first until the budget runs out, so a big
    CLI spends its allowance on breadth rather than exhausting it on one branch."""
    collected: list[str] = []
    spent = 0
    queue: list[list[str]] = [[cli]]
    seen: set[tuple[str, ...]] = set()

    while queue and spent < budget:
        path = queue.pop(0)
        key = tuple(path)
        if key in seen:
            continue
        seen.add(key)

        text = run_help(path)
        if not text.strip():
            continue
        block = f'$ {" ".join(path)} --help\n{text.rstrip()}\n'
        collected.append(block)
        spent += len(block)

        if len(path) < 4:
            queue.extend(path + [name] for name in extract_subcommands(text))

    print(f'  read {len(collected)} help pages ({spent} chars)', file=sys.stderr)
    return '\n'.join(collected)


def author_tape(cli: str, question: str, help_text: str, force_sandbox: bool) -> dict:
    sandbox_rule = (
        'Set `sandbox: xdg` on this tape.'
        if force_sandbox
        else (
            'Set `sandbox: xdg` if ANY step creates, edits or deletes data — that '
            'redirects the XDG roots to a throwaway directory. Use `sandbox: none` '
            'only when every step is purely a read.'
        )
    )

    prompt = textwrap.dedent(f"""\
        Write a tape for a terminal demo answering this request:

            {question}

        Below is the complete help output for `{cli}`. Use ONLY commands, subcommands
        and flags that appear in it — never invent one, never guess a flag.

        Rules:
        - 2 to 4 steps. Each `run` is ONE invocation of `{cli}`. No pipes, no
          semicolons, no shell chaining, no redirects.
        - The steps must form a real sequence, where a later step uses something the
          earlier steps established. That ordering is the point of the demo; a list of
          unrelated commands is not worth recording.
        - If a step needs an id or name produced by an earlier step, prefer a command
          that lists it first, so a viewer can see where the value came from.
        - `narrate` explains WHY this step, not what the command says.
        - {sandbox_rule}

        Output ONLY JSON in exactly this shape, with no prose and no code fences:

        {TAPE_SCHEMA}

        HELP OUTPUT FOLLOWS
        ===================
        {help_text}
        """)

    return request_tape(prompt)


NUDGE = (
    '\n\nYour entire reply must be the JSON object. It must start with `{` and end '
    'with `}`. Do not introduce it, do not comment on it afterwards, and do not say '
    'the work is complete — the JSON is the only thing read.'
)


def ask_model(prompt: str, timeout: int = 420) -> str:
    """The one door to the model. It is never given tools: it reads help text and
    probe output as plain text and returns a tape, and the recorder does the running."""
    result = subprocess.run(
        ['claude', '-p', '--allowedTools', ''],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f'claude failed: {result.stderr.strip()}')
    return result.stdout.strip()


def request_tape(prompt: str) -> dict:
    """Ask twice before giving up. The model sometimes answers with the tape and then
    a closing remark, and `claude -p` returns only that last message — so the JSON is
    gone rather than malformed, and nothing in the reply can be salvaged."""
    try:
        return parse_tape(ask_model(prompt))
    except SystemExit:
        print('  no JSON in the reply, asking again', file=sys.stderr)
        return parse_tape(ask_model(prompt + NUDGE))


def strip_fences(raw: str) -> str:
    if '```' in raw:
        blocks = re.findall(r'```(?:json|ya?ml)?\n(.*?)```', raw, re.DOTALL)
        if blocks:
            return blocks[0]
    return raw


def parse_tape(raw: str) -> dict:
    """JSON, not YAML: a command carrying a jq filter or any `: ` is a colon inside
    what YAML would read as a plain scalar, and the tape fails to load."""
    match = re.search(r'\{.*\}', strip_fences(raw), re.DOTALL)
    if not match:
        raise SystemExit(f'model did not return a tape:\n{raw[:400]}')
    return json.loads(match.group(0))


def validate_tape(tape: dict, cli: str) -> dict:
    if 'steps' not in tape:
        raise SystemExit('model did not return a tape')

    for step in tape['steps']:
        command = step.get('run', '')
        if CHAINING.search(command):
            raise SystemExit(f'refusing chained or redirecting command: {command}')
        if command.split()[:1] != [cli]:
            raise SystemExit(f'refusing command that is not {cli}: {command}')
    return tape
