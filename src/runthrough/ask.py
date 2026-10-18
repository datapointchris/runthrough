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
from typing import NamedTuple

ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
COMMAND_HEADING = re.compile(r'(Available Commands:|Commands\s*$|Commands\s*[─╮])')
SUBCOMMAND = re.compile(r'^[│|]?\s{0,4}([a-z][a-z0-9-]{1,30})\s{2,}\S')
CHAINING = re.compile(r'[;&|`]|\$\(')
# An output redirect: an optional descriptor or `&`, then `>`, `>>` or `>|`, then its target.
REDIRECT = re.compile(r'(?:\d+|&)?>[>|]?\s*(&\d+|&-|[^\s|;&<>()]*)')
WRITES_NO_FILE = re.compile(r'/dev/null|&(?:\d+|-)')

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
            'points the XDG roots at a sandbox directory beside the recording, away '
            "from the user's own data, and that directory is kept between recordings. "
            'Use `sandbox: none` only when every step is purely a read.'
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

# What the model may not do, as a deny list because an allow list does not
# restrict anything: `claude -p --allowedTools ""` runs Bash regardless, since
# that flag pre-approves tools rather than confining the session to them.
#
# Every built-in is here because this session needs none of them. It is handed
# help text and probe output on stdin and returns a tape; the recorder is what
# runs commands, behind check_command, after a person has read the tape. A model
# that could reach the machine itself would be running commands nobody approved,
# and would make the guard on the recorder beside the point.
DENIED_TOOLS = (
    'Bash',
    'Read',
    'Write',
    'Edit',
    'NotebookEdit',
    'Glob',
    'Grep',
    'WebFetch',
    'WebSearch',
    'Task',
    'TodoWrite',
)


class Reply(NamedTuple):
    text: str
    model: str
    claude_version: str = ''


def model_argv() -> list[str]:
    # --verbose fixes the output as one array of frames, whatever the user's config says.
    return ['claude', '-p', '--output-format', 'json', '--verbose', '--disallowed-tools', ','.join(DENIED_TOOLS)]


def frames(stdout: str) -> list[dict[str, object]]:
    """The array of frames `--verbose` prints, or none where stdout is not one."""
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    return [f for f in parsed if isinstance(f, dict)] if isinstance(parsed, list) else []


def primary_model(usage: object) -> str:
    """The model that wrote the most output, ties to the lower name. A call can reach
    a second model for housekeeping, and that one is not the author.

    Named by the entry's `canonicalModel` where it carries one. The key carries the
    context-window suffix, as in `claude-opus-5-5[1m]`, which moves with a setting
    while the same weights answer."""
    if not isinstance(usage, dict):
        return ''
    ranked = sorted(usage.items(), key=lambda item: (-int((item[1] or {}).get('outputTokens', 0)), item[0]))
    if not ranked:
        return ''
    name, entry = ranked[0]
    return str((entry or {}).get('canonicalModel') or name)


class ModelTimedOut(SystemExit):
    """`claude` ran past its deadline. Asking again would wait as long a second time,
    so `request_tape` lets this through instead of retrying it."""


def ask_model(prompt: str, timeout: int = 420) -> Reply:
    """The one door to the model. It is never given tools: it reads help text and
    probe output as plain text and returns a tape, and the recorder does the running."""
    try:
        result = subprocess.run(
            model_argv(),
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ModelTimedOut(f'claude timed out after {timeout}s') from None
    printed = frames(result.stdout)
    # Searched from the end, because nothing promises the result stays the last frame.
    frame = next((f for f in reversed(printed) if f.get('type') == 'result'), None)
    if frame is None:
        raise SystemExit(f'claude failed: {result.stderr.strip() or result.stdout.strip()[:400]}')
    if result.returncode != 0 or frame.get('is_error') or frame.get('subtype') != 'success':
        raise SystemExit(f'claude failed: {frame.get("result") or frame.get("subtype") or result.stderr.strip()}')
    init = next((f for f in printed if f.get('type') == 'system' and f.get('subtype') == 'init'), {})
    return Reply(
        text=str(frame.get('result') or '').strip(),
        model=primary_model(frame.get('modelUsage')),
        claude_version=str(init.get('claude_code_version') or ''),
    )


def request_tape(prompt: str) -> dict:
    """Ask twice before giving up. The model sometimes answers with the tape and then
    a closing remark, and `claude -p` returns only that last message — so the JSON is
    gone rather than malformed, and nothing in the reply can be salvaged.

    `authored_by` is stamped after parsing and replaces anything the model wrote
    there, because a model naming itself would be attesting to its own identity."""
    try:
        reply = ask_model(prompt)
        tape = parse_tape(reply.text)
    except ModelTimedOut:
        raise
    except SystemExit:
        print('  no JSON in the reply, asking again', file=sys.stderr)
        reply = ask_model(prompt + NUDGE)
        tape = parse_tape(reply.text)
    tape['authored_by'] = {'model': reply.model, 'claude_version': reply.claude_version}
    return tape


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


def file_redirect(command: str) -> str | None:
    """The first redirect in `command` that writes a file, as written, or None.

    The descriptor is part of the match, so `2>out.txt` and `1>x` are caught
    alongside a bare `>`. `>/dev/null` and `2>&1` write no file and pass."""
    for match in REDIRECT.finditer(command):
        if not WRITES_NO_FILE.fullmatch(match.group(1)):
            return match.group(0)
    return None


def validate_tape(tape: dict, cli: str) -> dict:
    if 'steps' not in tape:
        raise SystemExit('model did not return a tape')

    for step in tape['steps']:
        command = step.get('run', '')
        if CHAINING.search(command):
            raise SystemExit(f'refusing chained command: {command}')
        if redirect := file_redirect(command):
            raise SystemExit(f'refusing a redirect that writes a file ({redirect}): {command}')
        if command.split()[:1] != [cli]:
            raise SystemExit(f'refusing command that is not {cli}: {command}')
    return tape
