"""Answer a question that spans tools, and record the answer.

Unlike a single-command demo this has to find its own tools first, so it asks
the machine what it has before reading any help. What "what it has" means is
configuration, not something this module knows.

Every command it produces must be one a person would plausibly type: real
tools, pipes allowed, inline shell scripts never.
"""

from __future__ import annotations

import dataclasses as dc
import json
import re
import shlex
import subprocess
import sys
import textwrap
from collections.abc import Callable

from runthrough import config as config_module
from runthrough.ask import ask_model
from runthrough.ask import file_redirect
from runthrough.ask import request_tape
from runthrough.ask import strip_ansi

READ_COMMANDS = {
    'awk',
    'bat',
    'cat',
    'column',
    'comm',
    'cut',
    'date',
    'df',
    'diff',
    'du',
    'echo',
    'eza',
    'fd',
    'file',
    'find',
    'grep',
    'head',
    'hostname',
    'jq',
    'ls',
    'nl',
    'paste',
    'printf',
    'rg',
    'sed',
    'sort',
    'stat',
    'tail',
    'tokei',
    'tr',
    'uname',
    'uniq',
    'wc',
    'which',
    'yq',
    'zoxide',
}
MUTATING_WORDS = {
    'add',
    'apply',
    'chmod',
    'chown',
    'clean',
    'commit',
    'complete',
    'create',
    'delete',
    'deploy',
    'destroy',
    'dd',
    'drop',
    'edit',
    'install',
    'kill',
    'merge',
    'mkdir',
    'mv',
    'new',
    'prune',
    'purge',
    'push',
    'rebase',
    'reset',
    'restart',
    'rm',
    'rmdir',
    'set',
    'start',
    'stop',
    'sync',
    'touch',
    'uninstall',
    'update',
    'upgrade',
    'write',
}


def sed_script_writes(script: str) -> bool:
    """A sed script's `w` and `W` commands write a file and its `e` command runs one,
    as do the `w` and `e` flags of `s`. Each follows the start, a separator, an
    address, or the closing delimiter of `s` and its flags, and is followed by a space."""
    return bool(re.search(r'(?:^|[;{}\n$\d/]|/[gpiImMe\d]*)\s*[wWe](?:\s|$)', script))


def awk_program_writes(program: str) -> bool:
    """`system()` runs a command, and so does a `|` to or from one. Strings and regex
    literals are dropped first, because `split($0, a, "|")` and `/a|b/` pipe nothing.
    Writing to a file needs `>`, which the redirect check refuses wherever it appears."""
    code = re.sub(r'"(?:\\.|[^"\\])*"', '', program)
    code = re.sub(r'/(?:\\.|[^/\\\n])*/', '', code)
    return '|' in code or bool(re.search(r'\bsystem\s*\(', code))


@dc.dataclass(frozen=True)
class WritingArguments:
    """What makes one allowlisted read command write a file or run another program."""

    letters: str = ''  # short flags, caught alone or inside a bundle such as `-ni` or `-i.bak`
    long_flags: frozenset[str] = frozenset()  # also caught as a GNU abbreviation or with `=value`
    primaries: frozenset[str] = frozenset()  # find's, matched whole
    subcommands: frozenset[str] = frozenset()
    # Short flags whose value ends a bundle, so `-F,` or `-ojson` is never read as flags.
    takes_value: str = ''
    long_values: frozenset[str] = frozenset()
    operands: int | None = None  # uniq writes its second operand
    # Reads a sed script or an awk program, given as an operand or as a script flag's value.
    script: Callable[[str], bool] | None = None
    script_flags: frozenset[str] = frozenset()


WRITING_ARGUMENTS = {
    'awk': WritingArguments(
        letters='dDEfilop',
        long_flags=frozenset({'--debug', '--dump-variables', '--exec', '--file', '--include', '--load', '--pretty-print', '--profile'}),
        takes_value='vF',
        script=awk_program_writes,
        script_flags=frozenset({'--source'}),
    ),
    'bat': WritingArguments(long_flags=frozenset({'--pager'}), subcommands=frozenset({'cache'})),
    'fd': WritingArguments(letters='xX', long_flags=frozenset({'--exec', '--exec-batch'}), takes_value='cCdEejoSt'),
    'file': WritingArguments(letters='C', long_flags=frozenset({'--compile'}), takes_value='eFfmP'),
    'find': WritingArguments(
        primaries=frozenset({'-delete', '-exec', '-execdir', '-fls', '-fprint', '-fprint0', '-fprintf', '-ok', '-okdir'}),
    ),
    'rg': WritingArguments(long_flags=frozenset({'--pre'})),
    'sed': WritingArguments(
        letters='fi',
        long_flags=frozenset({'--file', '--in-place'}),
        takes_value='l',
        script=sed_script_writes,
        script_flags=frozenset({'--expression'}),
    ),
    'sort': WritingArguments(letters='o', long_flags=frozenset({'--compress-program', '--output'}), takes_value='kSTt'),
    'uniq': WritingArguments(
        takes_value='fsw',
        long_values=frozenset({'--check-chars', '--skip-chars', '--skip-fields'}),
        operands=1,
    ),
    'yq': WritingArguments(letters='is', long_flags=frozenset({'--inplace', '--split-exp'}), takes_value='fIop'),
    'zoxide': WritingArguments(subcommands=frozenset({'add', 'edit', 'import', 'remove'})),
}


def writing_argument(words: list[str]) -> str | None:
    """The argument that would make an allowlisted read command write a file or run
    another program, or None. A sed or awk script read from a file cannot be checked,
    so `-f` counts as one."""
    rules = WRITING_ARGUMENTS.get(words[0])
    if rules is None:
        return None
    if len(words) > 1 and words[1] in rules.subcommands:
        return words[1]

    operands: list[str] = []
    options_ended = value_follows = False
    for word in words[1:]:
        if value_follows:
            value_follows = False
        elif options_ended or word == '-' or not word.startswith('-'):
            operands.append(word)
        elif word == '--':
            options_ended = True
        elif word.startswith('--'):
            name, _, value = word.partition('=')
            if any(flag.startswith(name) for flag in rules.long_flags):
                return word
            if value and rules.script and any(flag.startswith(name) for flag in rules.script_flags) and rules.script(value):
                return word
            value_follows = name in rules.long_values and not value
        elif word in rules.primaries:
            return word
        else:
            for position, letter in enumerate(word[1:], start=2):
                if letter in rules.letters:
                    return word
                if letter in rules.takes_value:
                    value_follows = position == len(word)
                    break

    if rules.script:
        for operand in operands:
            if rules.script(operand):
                return operand
    if rules.operands is not None and len(operands) > rules.operands:
        return operands[rules.operands]
    return None


FORBIDDEN = re.compile(r"(&&|\|\||;|`|\bsudo\b|\bssh\b|-c\s+['\"])")
# The shell reads these as keywords only at command position. Anywhere else they are
# data: `rg do notes.txt` searches for the word.
SHELL_KEYWORDS = {'do', 'done', 'fi', 'for', 'function', 'if', 'then', 'until', 'while'}

TAPE_SCHEMA = """\
{
  "name": "<2-4 word page name, title case>",
  "title": "<one line, says what the investigation establishes>",
  "description": "<two or three sentences: the question, and why the steps go in this order>",
  "tags": ["<tool>", "<topic>", "<topic>"],
  "sandbox": "none",
  "columns": 100,
  "rows": 22,
  "typing_speed": 0.03,
  "max_gap": 1.0,
  "steps": [
    {"narrate": "<what this step is for, not what it says>",
     "run": "<a single command line>",
     "pause": 3.0}
  ]
}"""


def run_configured(command: str, timeout: int = 60) -> str:
    """Run one of the two routing commands this machine supplies. Shell, because a
    person writes these into their own config and will reach for a pipe."""
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return strip_ansi(result.stdout)


def registry_roster(routing: config_module.Routing) -> str:
    return run_configured(routing.inventory) if routing.inventory else ''


def semantic_hits(routing: config_module.Routing, question: str) -> str:
    command = routing.search_command(question)
    return run_configured(command) if command else ''


def route(question: str, routing: config_module.Routing) -> list[str]:
    prompt = textwrap.dedent(f"""\
        A person wants to answer this question at their terminal:

            {question}

        Below is their installed tool registry and the top semantic-search hits from
        their own repos and notes. Decide which commands are worth reading the help
        for. Prefer a purpose-built tool of theirs over a generic one.

        Return ONLY a JSON array of command paths, most relevant first, at most 4.
        A path may include subcommands, e.g. ["git log", "jq"].
        No prose, no code fences.

        TOOL REGISTRY
        =============
        {registry_roster(routing)}

        SEMANTIC SEARCH HITS
        ====================
        {semantic_hits(routing, question)}
        """)
    raw = ask_model(prompt).text
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if not match:
        raise SystemExit(f'router did not return a list:\n{raw}')
    return [str(item) for item in json.loads(match.group(0))]


def probe(question: str, help_text: str, allowed: set[str]) -> str:
    """Help text says what the flags are; it never says what the values look like.
    Without a look at real output the model invents plausible field names and greps
    for a hostname the records do not contain."""
    prompt = textwrap.dedent(f"""\
        Someone is about to investigate this at their terminal:

            {question}

        Before writing anything, they want to LOOK at the data. Give the 2 or 3
        read-only commands you would run first to see its actual shape — what the
        columns are called, what the values look like, what fields the JSON has.

        Keep each one short and safe. Prefer listing and showing over filtering,
        because the point is to see the shape rather than to answer the question yet.

        Return ONLY a JSON array of command strings. No prose, no code fences.

        HELP OUTPUT
        ===========
        {help_text}
        """)
    raw = ask_model(prompt).text
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if not match:
        return ''

    observations = []
    for command in json.loads(match.group(0))[:3]:
        try:
            check_command(command, allowed)
        except SystemExit as refusal:
            print(f'  skipped probe ({refusal})', file=sys.stderr)
            continue
        print(f'  probing: {command}', file=sys.stderr)
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        output = strip_ansi(result.stdout or result.stderr)[:1500]
        observations.append(f'$ {command}\n{output.rstrip()}')
    return '\n\n'.join(observations)


def author(question: str, help_text: str, observations: str) -> dict:
    prompt = textwrap.dedent(f"""\
        Write a tape for a terminal recording that answers this question by actually
        investigating it:

            {question}

        Below is the help output for the relevant tools. Use ONLY commands, flags and
        subcommands that appear in it.

        The recording teaches someone how to do this themselves, so every command must
        be one a person would realistically type:
        - SHORT. Under about 140 characters. If it does not fit, the step is too big —
          split it, or find the tool that already does it.
        - Prefer their purpose-built command over assembling the same thing by hand.
          If a tool has a verb for this, use the verb.
        - Pipes are welcome and are much of the point: rg, fd, jq, sort, uniq, head.
          At most 4 stages. Command substitution with $(...) is fine.
        - NEVER an inline script. No bash -c, no python -c, no for/while/if, no
          semicolons, no chaining with &&, no heredocs, no writing to files.
        - READ ONLY. Nothing that creates, edits, deletes, installs or syncs anything.

        Structure it as a real investigation, 3 to 5 steps: orient, narrow to the
        thing that looks wrong, then inspect it closely enough to say what happened.
        The last step should land on the evidence, not on a summary.

        The question may be wrong. If the data below does not show the problem it
        assumes, say so and make THAT the demo — the commands that establish nothing
        is wrong are worth as much as the ones that find a fault, and a viewer needs
        to know how to reach a clean verdict. Never manufacture a fault, never treat
        a normal record as suspicious to have something to diagnose, and never let a
        narration claim more than its command's output actually shows.

        The `title` is at most 12 words. Anything longer belongs in `description`.

        Output ONLY JSON in exactly this shape, no prose and no code fences:

        {TAPE_SCHEMA}

        HELP OUTPUT
        ===========
        {help_text}

        WHAT THOSE COMMANDS ACTUALLY PRINT
        ==================================
        Use the real names and values below. Do not grep for a word that does not
        appear here, and do not invent a JSON field.

        {observations}
        """)
    return request_tape(prompt)


def split_pipeline(text: str) -> list[str]:
    """Split on shell pipes only. A jq filter is full of `|` that never reaches the
    shell, and counting those rejects exactly the commands worth demonstrating.

    A quote opens wherever it appears, as it does in the shell, so `-F'|'` is one
    word. Each stage is returned as written, quotes included, for `shlex.split`."""
    stages: list[str] = []
    start = 0
    quote = ''
    escaped = False
    for index, character in enumerate(text):
        if escaped:
            escaped = False
        elif character == '\\' and quote != "'":
            escaped = True
        elif quote:
            quote = '' if character == quote else quote
        elif character in '\'"':
            quote = character
        elif character == '|':
            stages.append(text[start:index])
            start = index + 1
    stages.append(text[start:])
    return [stage.strip() for stage in stages if stage.strip()]


def segments(command: str) -> list[str]:
    inner = re.findall(r'\$\((.*?)\)', command)
    outer = re.sub(r'\$\(.*?\)', ' ', command)
    pieces = split_pipeline(outer)
    for nested in inner:
        pieces.extend(split_pipeline(nested))
    return pieces


def check_command(command: str, allowed: set[str]) -> None:
    if len(command) > 160:
        raise SystemExit(f'too long to be typed by hand ({len(command)} chars): {command}')
    if FORBIDDEN.search(command):
        raise SystemExit(f'not something a person types inline: {command}')
    if redirect := file_redirect(command):
        raise SystemExit(f'refusing a redirect that writes a file ({redirect}): {command}')
    if len(split_pipeline(re.sub(r'\$\(.*?\)', ' ', command))) > 4:
        raise SystemExit(f'too many pipe stages: {command}')

    for segment in segments(command):
        try:
            words = shlex.split(segment)
        except ValueError:
            raise SystemExit(f'unbalanced quoting: {command}') from None
        if not words:
            continue
        if words[0] in SHELL_KEYWORDS:
            raise SystemExit(f'not something a person types inline: {command}')
        if words[0] not in allowed:
            raise SystemExit(f'command not in the read-only allowlist: {words[0]}')
        if writer := writing_argument(words):
            raise SystemExit(f'refusing {writer}, which lets {words[0]} write a file or run a command: {command}')
        if words[0] in READ_COMMANDS:
            # A read command takes patterns and paths, never a subcommand, so a verb
            # among them is data: `rg deploy src/` searches for the word.
            continue
        for word in words[1:]:
            # Only the subcommand path is checked. `--verb apply` is a filter value,
            # not an apply, and blocking it would rule out most report queries.
            if word.startswith('-'):
                break
            if word.lower() in MUTATING_WORDS:
                raise SystemExit(f'refusing a mutating verb ({word}) in: {command}')
