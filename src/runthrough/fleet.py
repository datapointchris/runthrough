"""Ask a question about the fleet, get a recording of someone answering it.

Unlike a single-CLI demo this has to find its own tools first, so it routes
through the tool registry and the semantic index before reading any help.
Every command it produces must be one a person would plausibly type: real
tools, pipes allowed, inline shell scripts never.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import textwrap

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
    'less',
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
    'log',
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
FORBIDDEN = re.compile(r"(>>|(?<![0-9])>|&&|\|\||;|`|\bsudo\b|\bssh\b|-c\s+['\"])")
LOOPS = re.compile(r'\b(for|while|until|do|done|if|then|fi|function)\b')

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


def registry_roster() -> str:
    return strip_ansi(subprocess.run(['toolbox', 'list'], capture_output=True, text=True, check=False).stdout)


def semantic_hits(question: str) -> str:
    result = subprocess.run(
        ['indy', 'search', question, '--owned', '-n', '8'],
        capture_output=True,
        text=True,
        check=False,
    )
    return strip_ansi(result.stdout)


def ask_model(prompt: str) -> str:
    result = subprocess.run(
        ['claude', '-p', '--allowedTools', ''],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=420,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f'claude failed: {result.stderr.strip()}')
    return result.stdout.strip()


def route(question: str) -> list[str]:
    prompt = textwrap.dedent(f"""\
        A person wants to answer this question at their terminal:

            {question}

        Below is their installed tool registry and the top semantic-search hits from
        their own repos and notes. Decide which commands are worth reading the help
        for. Prefer a purpose-built tool of theirs over a generic one.

        Return ONLY a JSON array of command paths, most relevant first, at most 4.
        A path may include subcommands, e.g. ["dotfiles report", "jq"].
        No prose, no code fences.

        TOOL REGISTRY
        =============
        {registry_roster()}

        SEMANTIC SEARCH HITS
        ====================
        {semantic_hits(question)}
        """)
    raw = ask_model(prompt)
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
    raw = ask_model(prompt)
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


def author(question: str, help_text: str, observations: str) -> str:
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
    return ask_model(prompt)


def split_pipeline(text: str) -> list[str]:
    """Split on shell pipes only. A jq filter is full of `|` that never reaches the
    shell, and counting those rejects exactly the commands worth demonstrating."""
    lexer = shlex.shlex(text, posix=False, punctuation_chars=True)
    lexer.whitespace_split = True
    stages: list[str] = []
    current: list[str] = []
    for token in lexer:
        if token == '|':
            stages.append(' '.join(current))
            current = []
        else:
            current.append(token)
    stages.append(' '.join(current))
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
    if FORBIDDEN.search(command) or LOOPS.search(command):
        raise SystemExit(f'not something a person types inline: {command}')
    if len(split_pipeline(re.sub(r'\$\(.*?\)', ' ', command))) > 4:
        raise SystemExit(f'too many pipe stages: {command}')

    for segment in segments(command):
        words = shlex.split(segment)
        if not words:
            continue
        if words[0] not in allowed:
            raise SystemExit(f'command not in the read-only allowlist: {words[0]}')
        for word in words[1:]:
            # Only the subcommand path is checked. `--verb apply` is a filter value,
            # not an apply, and blocking it would rule out most report queries.
            if word.startswith('-'):
                break
            if word.lower() in MUTATING_WORDS:
                raise SystemExit(f'refusing a mutating verb ({word}) in: {command}')
