"""Record a declarative tape of real CLI commands into a watchable animation.

Commands are genuinely executed in a pty, so the output is whatever the CLI
actually printed. Nothing about the terminal contents is authored by hand.
"""

from __future__ import annotations

import codecs
import html
import os
import pty
import select
import struct
import subprocess
import sys
import termios
import time
from dataclasses import dataclass
from pathlib import Path

import pyte
import yaml

PROMPT = '\x1b[32m❯\x1b[0m '

GHOSTTY_THEME = Path.home() / '.config/ghostty/themes/current.conf'
ANSI_NAMES = ('black', 'red', 'green', 'brown', 'blue', 'magenta', 'cyan', 'white')


def load_terminal_theme() -> tuple[dict[str, str], str, str, list[str]]:
    """Read the palette the terminal is actually using, so a recording looks like
    the shell it was taken from and follows `theme apply` without being re-cut."""
    swatches: dict[int, str] = {}
    foreground, background = '#d5d8e2', '#191b22'

    if GHOSTTY_THEME.exists():
        for line in GHOSTTY_THEME.read_text().splitlines():
            key, _, value = line.partition('=')
            key, value = key.strip(), value.strip()
            if key == 'palette' and '=' in value:
                index, _, color = value.partition('=')
                swatches[int(index)] = color
            elif key == 'foreground':
                foreground = value
            elif key == 'background':
                background = value

    ansi = [swatches.get(index, foreground) for index in range(16)]
    palette = {name: ansi[index] for index, name in enumerate(ANSI_NAMES)}
    palette['yellow'] = palette['brown']
    return palette, foreground, background, ansi


PALETTE, FOREGROUND, BACKGROUND, ANSI = load_terminal_theme()

try:
    from pyte.graphics import FG_BG_256

    PYTE_256_TO_THEME = {FG_BG_256[index]: ANSI[index].lstrip('#') for index in range(16)}
except (ImportError, AttributeError, IndexError):
    PYTE_256_TO_THEME = {}


GHOSTTY_FONT = Path.home() / '.config/ghostty/fonts/current.conf'


def load_terminal_font() -> tuple[str, int]:
    family, size = 'monospace', 13
    if GHOSTTY_FONT.exists():
        for line in GHOSTTY_FONT.read_text().splitlines():
            key, _, value = line.partition('=')
            key, value = key.strip(), value.strip().strip('"')
            if key == 'font-family':
                family = value
            elif key == 'font-size':
                size = int(float(value))
    return family, size


FONT_FAMILY, FONT_SIZE = load_terminal_font()


def resolve_font_file(family: str, bold: bool) -> Path | None:
    query = f'{family}:bold' if bold else family
    try:
        result = subprocess.run(
            ['fc-match', '-f', '%{file}', query],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    path = Path(result.stdout.strip())
    return path if path.is_file() else None


def embed_font(path: Path, codepoints: set[int]) -> str | None:
    """A Nerd Font ships thousands of icon glyphs and runs to megabytes. Subset to
    the codepoints this page actually paints, or the artifact is mostly font."""
    import base64
    import io

    from fontTools.subset import Options
    from fontTools.subset import Subsetter
    from fontTools.ttLib import TTFont
    from fontTools.ttLib import TTLibError

    try:
        font = TTFont(path)
        options = Options()
        options.drop_tables += ['FFTM', 'PfEd']
        subsetter = Subsetter(options=options)
        subsetter.populate(unicodes=codepoints)
        subsetter.subset(font)
        font.flavor = 'woff2'
        buffer = io.BytesIO()
        font.save(buffer)
        return base64.b64encode(buffer.getvalue()).decode()
    except (TTLibError, OSError, ValueError, KeyError) as error:
        print(f'  font subset failed for {path.name}: {error}', file=sys.stderr)
        return None


def font_face_rules(codepoints: set[int]) -> tuple[str, str]:
    faces = []
    for bold in (False, True):
        path = resolve_font_file(FONT_FAMILY, bold)
        if path is None:
            continue
        encoded = embed_font(path, codepoints)
        if encoded is None:
            continue
        faces.append(
            f"@font-face {{ font-family: 'RecordedTerminal';"
            f' font-weight: {700 if bold else 400}; font-style: normal;'
            f' font-display: block;'
            f" src: url(data:font/woff2;base64,{encoded}) format('woff2'); }}"
        )
    stack = (
        "'RecordedTerminal', ui-monospace, Menlo, Consolas, monospace"
        if faces
        else "ui-monospace, 'JetBrains Mono', Menlo, Consolas, monospace"
    )
    return '\n'.join(faces), stack


PRECOMMANDS = {'sudo', 'doas', 'env', 'command', 'nohup', 'time', 'exec', 'builtin'}
RESERVED_WORDS = {
    'if',
    'then',
    'else',
    'elif',
    'fi',
    'for',
    'while',
    'until',
    'do',
    'done',
    'case',
    'esac',
    'select',
    'function',
    'repeat',
    'coproc',
}
SGR_CODES = {'red': '31', 'green': '32', 'yellow': '33', 'bold': '1', 'underline': '4'}


def scan_tokens(command: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    index, length = 0, len(command)
    while index < length:
        character = command[index]
        start = index
        if character.isspace():
            while index < length and command[index].isspace():
                index += 1
            kind = 'space'
        elif character in '\'"':
            index += 1
            while index < length and command[index] != character:
                index += 2 if command[index] == '\\' else 1
            index = min(index + 1, length)
            kind = 'quoted'
        elif character in '|&;':
            while index < length and command[index] in '|&;':
                index += 1
            kind = 'separator'
        elif character in '<>':
            while index < length and command[index] in '<>':
                index += 1
            kind = 'redirect'
        else:
            while index < length and not command[index].isspace() and command[index] not in '|&;<>\'"':
                index += 1
            kind = 'word'
        tokens.append((command[start:index], kind))
    return tokens


def highlight_command(command: str) -> list[tuple[str, str]]:
    """Colour a command line the way zsh-syntax-highlighting would, using its
    stock styles. zsh recolours a word as it resolves; this paints the settled
    state from the first keystroke, which reads as intent rather than as a glitch."""
    import shutil

    spans: list[tuple[str, str]] = []
    at_command_position = True

    for text, kind in scan_tokens(command):
        if kind == 'space':
            style = 'none'
        elif kind == 'quoted' or kind == 'redirect':
            style = 'fg=yellow'
        elif kind == 'separator':
            style = 'none'
            at_command_position = True
        elif at_command_position:
            if text in RESERVED_WORDS:
                style = 'fg=yellow'
            elif text in PRECOMMANDS:
                style = 'fg=green,underline'
            elif shutil.which(text):
                style = 'fg=green'
                at_command_position = False
            else:
                style = 'fg=red,bold'
                at_command_position = False
        elif Path(os.path.expanduser(text)).exists():
            style = 'underline'
        else:
            style = 'none'
        spans.append((text, style))
    return spans


def to_sgr(style: str) -> str:
    if style == 'none':
        return '\x1b[0m'
    codes = [SGR_CODES[part.removeprefix('fg=')] for part in style.split(',')]
    return '\x1b[0m\x1b[' + ';'.join(codes) + 'm'


@dataclass
class Step:
    command: str
    narration: str
    pause: float


@dataclass
class Tape:
    name: str
    title: str
    description: str
    tags: list[str]
    cli: str
    sandbox: str
    columns: int
    rows: int
    typing_speed: float
    max_gap: float
    env: dict[str, str]
    steps: list[Step]


def load_tape(path: Path) -> Tape:
    raw = yaml.safe_load(path.read_text())
    steps = [
        Step(
            command=entry['run'],
            narration=entry.get('narrate', ''),
            pause=float(entry.get('pause', 1.5)),
        )
        for entry in raw['steps']
    ]
    return Tape(
        name=raw.get('name', raw['title']),
        title=raw['title'],
        description=raw.get('description', '').strip(),
        tags=raw.get('tags', []),
        cli=raw.get('cli', ''),
        sandbox=raw.get('sandbox', 'none'),
        columns=int(raw.get('columns', 100)),
        rows=int(raw.get('rows', 24)),
        typing_speed=float(raw.get('typing_speed', 0.035)),
        max_gap=float(raw.get('max_gap', 1.2)),
        env={key: str(value) for key, value in (raw.get('env') or {}).items()},
        steps=steps,
    )


def build_environment(tape: Tape, sandbox_root: Path) -> dict[str, str]:
    """Every fleet tool resolves its paths through XDG, so redirecting the four
    XDG roots sandboxes any of them without the recorder knowing what it is."""
    environment = dict(os.environ)
    environment.update(
        TERM='xterm-256color',
        COLUMNS=str(tape.columns),
        LINES=str(tape.rows),
        NO_COLOR='',
        FORCE_COLOR='1',
        PS1='',
    )
    environment.pop('NO_COLOR')

    if tape.sandbox == 'xdg':
        for variable, leaf in (
            ('XDG_DATA_HOME', 'data'),
            ('XDG_CONFIG_HOME', 'config'),
            ('XDG_STATE_HOME', 'state'),
            ('XDG_CACHE_HOME', 'cache'),
        ):
            directory = sandbox_root / leaf
            directory.mkdir(parents=True, exist_ok=True)
            environment[variable] = str(directory)

    environment.update(tape.env)
    return environment


def execute_in_pty(command: str, environment: dict[str, str], columns: int, rows: int) -> list[tuple[float, bytes]]:
    master, slave = pty.openpty()
    termios.tcsetattr(slave, termios.TCSANOW, termios.tcgetattr(slave))
    import fcntl

    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', rows, columns, 0, 0))

    process = subprocess.Popen(
        command,
        shell=True,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=environment,
        close_fds=True,
        start_new_session=True,
    )
    os.close(slave)

    events: list[tuple[float, bytes]] = []
    started = time.monotonic()
    while True:
        readable, _, _ = select.select([master], [], [], 0.05)
        if readable:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            events.append((time.monotonic() - started, chunk))
        elif process.poll() is not None:
            break

    while True:
        readable, _, _ = select.select([master], [], [], 0.05)
        if not readable:
            break
        try:
            chunk = os.read(master, 65536)
        except OSError:
            break
        if not chunk:
            break
        events.append((time.monotonic() - started, chunk))

    os.close(master)
    process.wait()
    return events


def record_tape(tape: Tape, sandbox_root: Path) -> tuple[list[tuple[float, bytes]], list[tuple[float, float, str, str]]]:
    environment = build_environment(tape, sandbox_root)
    cast: list[tuple[float, bytes]] = []
    narration_track: list[tuple[float, float, str, str]] = []
    clock = 0.0

    for step in tape.steps:
        narration_start = clock
        cast.append((clock, PROMPT.encode()))
        clock += 0.35

        for text, style in highlight_command(step.command):
            pending = to_sgr(style)
            for character in text:
                cast.append((clock, (pending + character).encode()))
                pending = ''
                clock += tape.typing_speed
        clock += 0.35
        cast.append((clock, b'\x1b[0m\r\n'))
        clock += 0.1

        print(f'  running: {step.command}', file=sys.stderr)
        output = execute_in_pty(step.command, environment, tape.columns, tape.rows)

        previous_offset = 0.0
        for offset, chunk in output:
            clock += min(offset - previous_offset, tape.max_gap)
            previous_offset = offset
            cast.append((clock, chunk))

        clock += step.pause
        cast.append((clock, b'\r\n'))
        narration_track.append((narration_start, clock, step.narration, step.command))

    return cast, narration_track


def render_frames(cast: list[tuple[float, bytes]], columns: int, rows: int, fps: int) -> list[tuple[float, list]]:
    screen = pyte.Screen(columns, rows)
    stream = pyte.Stream(screen)
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')

    frames: list[tuple[float, list]] = []
    interval = 1.0 / fps
    next_capture = 0.0
    previous_snapshot = None

    def capture(at: float) -> None:
        nonlocal previous_snapshot
        snapshot = snapshot_screen(screen)
        if snapshot != previous_snapshot:
            frames.append((at, snapshot))
            previous_snapshot = snapshot

    for timestamp, chunk in cast:
        while timestamp >= next_capture:
            capture(next_capture)
            next_capture += interval
        stream.feed(decoder.decode(chunk))

    capture(next_capture)
    return frames


def find_first_painted_frame(frames: list[tuple[float, list]]) -> float:
    """A recording that opens on an empty screen looks broken on first paint."""
    for timestamp, lines in frames:
        if any(run[0].strip() for line in lines for run in line):
            return timestamp
    return 0.0


def snapshot_screen(screen: pyte.Screen) -> list:
    lines = []
    for y in range(screen.lines):
        buffer_row = screen.buffer[y]
        runs: list[tuple[str, str, str, bool]] = []
        text = ''
        style: tuple[str, str, bool] | None = None
        for x in range(screen.columns):
            character = buffer_row[x]
            foreground, background = resolve_colors(character)
            current = (foreground, background, character.bold)
            if current != style:
                if text and style is not None:
                    runs.append((text, *style))
                text = ''
                style = current
            text += character.data
        if text and style is not None:
            runs.append((text, *style))
        while runs and not runs[-1][0].strip() and runs[-1][2] == BACKGROUND:
            runs.pop()
        lines.append(runs)
    return lines


def resolve_colors(character) -> tuple[str, str]:
    foreground = to_hex(character.fg, FOREGROUND, character.bold)
    background = to_hex(character.bg, BACKGROUND, False)
    if character.reverse:
        foreground, background = background, foreground
    return foreground, background


def to_hex(color: str, fallback: str, bold: bool) -> str:
    if color == 'default':
        return fallback
    if color in ANSI_NAMES or color == 'yellow':
        name = 'brown' if color == 'yellow' else color
        index = ANSI_NAMES.index(name)
        return ANSI[index + 8] if bold else ANSI[index]
    color = PYTE_256_TO_THEME.get(color, color)
    if len(color) == 6:
        return f'#{color}'
    return fallback


def mix(first: str, second: str, amount: float) -> str:
    left = [int(first.lstrip('#')[i : i + 2], 16) for i in (0, 2, 4)]
    right = [int(second.lstrip('#')[i : i + 2], 16) for i in (0, 2, 4)]
    blended = [round(a + (b - a) * amount) for a, b in zip(left, right, strict=True)]
    return '#' + ''.join(f'{value:02x}' for value in blended)


def render_html(tape: Tape, frames: list[tuple[float, list]], narration_track, duration: float) -> str:
    rules = []
    frame_markup = []

    for index, (timestamp, lines) in enumerate(frames):
        end = frames[index + 1][0] if index + 1 < len(frames) else duration
        rules.append(keyframe_rule(f'fr{index}', timestamp, end, duration))
        last = ' last' if index == len(frames) - 1 else ''
        body = '\n'.join(render_line(runs) for runs in lines)
        frame_markup.append(f'<pre class="frame fr{index}{last}">{body}</pre>')

    caption_markup = []
    step_markup = []
    final = len(narration_track) - 1
    for index, (start, end, text, command) in enumerate(narration_track):
        rules.append(keyframe_rule(f'cp{index}', start, end, duration))
        rules.append(keyframe_rule(f'st{index}', start, end, duration, dim=0.38))
        last = ' last' if index == final else ''
        caption_markup.append(f'<p class="caption cp{index}{last}">{html.escape(text)}</p>')
        step_markup.append(f'<li class="step st{index}{last}"><span class="ord">{index + 1}</span><code>{html.escape(command)}</code></li>')

    tags = ''.join(f'<li>{html.escape(tag)}</li>' for tag in tape.tags)

    painted = {chr(code) for code in range(0x20, 0x7F)}
    painted.update('❯…—')
    for _, lines in frames:
        for line in lines:
            for run in line:
                painted.update(run[0])
    for text in (tape.name, tape.title, tape.description, *tape.tags):
        painted.update(text)
    for _, _, narration, command in narration_track:
        painted.update(narration + command)
    faces, mono = font_face_rules({ord(character) for character in painted})

    light = (
        f'--ground: {mix("#ffffff", BACKGROUND, 0.05)}; '
        f'--ink: {mix(BACKGROUND, "#000000", 0.12)}; '
        f'--muted: {mix(BACKGROUND, "#ffffff", 0.48)}; '
        f'--rule: {mix(BACKGROUND, "#ffffff", 0.84)}; '
        f'--accent: {mix(ANSI[2], "#000000", 0.32)}; '
        f'--shadow: rgba(0, 0, 0, .16);'
    )
    dark = (
        f'--ground: {mix(BACKGROUND, "#000000", 0.4)}; '
        f'--ink: {FOREGROUND}; '
        f'--muted: {mix(FOREGROUND, BACKGROUND, 0.45)}; '
        f'--rule: {mix(FOREGROUND, BACKGROUND, 0.8)}; '
        f'--accent: {ANSI[10]}; '
        f'--shadow: rgba(0, 0, 0, .5);'
    )

    return f"""<title>{html.escape(tape.name)}</title>
<style>
{faces}
:root {{ {light} }}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{ {dark} }}
}}
:root[data-theme="dark"] {{ {dark} }}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 3rem 1.5rem 5rem; background: var(--ground); color: var(--ink);
  font-family: ui-serif, "Iowan Old Style", "Source Serif 4", Georgia, serif;
  line-height: 1.6; -webkit-font-smoothing: antialiased;
}}
.wrap {{ max-width: 74rem; margin: 0 auto; display: flex; flex-direction: column; gap: 2rem; }}

header {{ display: flex; flex-direction: column; gap: .75rem; }}
.eyebrow {{
  font: 500 .7rem/1 {mono}; letter-spacing: .16em;
  text-transform: uppercase; color: var(--accent); margin: 0;
}}
h1 {{
  font-family: {mono};
  font-size: clamp(1.3rem, 1rem + 1.4vw, 1.85rem); font-weight: 600;
  letter-spacing: -0.02em; margin: 0; text-wrap: balance;
}}
.blurb {{ margin: 0; max-width: 60ch; color: var(--muted); font-size: 1.02rem; }}
.tags {{ display: flex; flex-wrap: wrap; gap: .4rem; list-style: none; margin: 0; padding: 0; }}
.tags li {{
  font: 500 .68rem/1 {mono}; letter-spacing: .08em;
  text-transform: uppercase; color: var(--muted);
  border: 1px solid var(--rule); border-radius: 2px; padding: .35rem .55rem;
}}

.stage {{ display: grid; gap: 1.75rem; align-items: start; }}
@media (min-width: 62rem) {{ .stage {{ grid-template-columns: 15rem minmax(0, 1fr); }} }}

.rail {{ list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .1rem; }}
.rail-title {{
  font: 500 .68rem/1 {mono}; letter-spacing: .16em;
  text-transform: uppercase; color: var(--muted); margin: 0 0 .85rem;
}}
.step {{
  display: grid; grid-template-columns: 1.4rem minmax(0, 1fr); gap: .55rem;
  padding: .6rem .7rem; border-left: 2px solid var(--rule); opacity: .38;
  animation-duration: {duration:.2f}s; animation-iteration-count: infinite;
  animation-timing-function: steps(1, end); animation-name: none;
}}
.step .ord {{
  font: 600 .72rem/1.5 {mono}; color: var(--muted);
  font-variant-numeric: tabular-nums;
}}
.step code {{
  font: .72rem/1.5 {mono};
  word-break: break-word; color: var(--ink);
}}

.player {{
  background: {BACKGROUND}; border: 1px solid var(--rule); border-radius: 6px;
  padding: 1.15rem 1.25rem; overflow-x: auto; box-shadow: 0 14px 40px -12px var(--shadow);
  cursor: pointer;
}}
.player:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 3px; }}
.screen {{
  position: relative; min-width: {tape.columns}ch; height: calc({tape.rows} * 1.34em);
  font: {FONT_SIZE}px/1.34 {mono};
}}
.frame {{
  position: absolute; inset: 0; margin: 0; opacity: 0; white-space: pre;
  color: {FOREGROUND};
  animation-duration: {duration:.2f}s; animation-iteration-count: infinite;
  animation-timing-function: steps(1, end);
}}
.captions {{ position: relative; min-height: 4.2em; margin-top: 1.1rem; }}
.caption {{
  position: absolute; inset: 0; margin: 0; opacity: 0; max-width: 62ch;
  color: var(--muted); font-size: .97rem;
  animation-duration: {duration:.2f}s; animation-iteration-count: infinite;
  animation-timing-function: steps(1, end);
}}
.colophon {{
  border-top: 1px solid var(--rule); padding-top: 1rem; color: var(--muted);
  font-size: .82rem; max-width: 62ch;
}}
.colophon strong {{ color: var(--ink); font-weight: 600; }}

@media (prefers-reduced-motion: reduce) {{
  .frame, .caption, .step {{ animation: none !important; }}
  .frame, .caption {{ opacity: 0; }}
  .frame.last, .caption.last {{ opacity: 1; }}
  .step {{ opacity: 1; }}
}}
{chr(10).join(rules)}
</style>
<div class="wrap">
  <header>
    <p class="eyebrow">Recorded from a live run</p>
    <h1>{html.escape(tape.title)}</h1>
    <p class="blurb">{html.escape(tape.description)}</p>
    <ul class="tags">{tags}</ul>
  </header>

  <div class="stage">
    <div>
      <p class="rail-title">Sequence</p>
      <ol class="rail">{''.join(step_markup)}</ol>
    </div>
    <div>
      <div class="player" id="player" tabindex="0" role="button" aria-label="Pause or resume the recording">
        <div class="screen">{''.join(frame_markup)}</div>
      </div>
      <div class="captions">{''.join(caption_markup)}</div>
    </div>
  </div>

  <p class="colophon">Click the recording to pause. Nothing on that screen was written by
  hand — the tape declares the commands, each one runs in a real pty, and the captured bytes are
  replayed at the speed they arrived. <strong>{len(frames)} distinct screens over
  {duration:.0f} seconds.</strong></p>
</div>
<script>
const player = document.getElementById('player');
const toggle = () => document.querySelectorAll('.frame, .caption, .step').forEach(node => {{
  const state = node.style.animationPlayState === 'paused' ? 'running' : 'paused';
  node.style.animationPlayState = state;
}});
player.addEventListener('click', toggle);
player.addEventListener('keydown', event => {{
  if (event.key === 'Enter' || event.key === ' ') {{ event.preventDefault(); toggle(); }}
}});
</script>
"""


def keyframe_rule(name: str, start: float, end: float, duration: float, dim: float = 0.0) -> str:
    begin = max(0.0, min(100.0, start / duration * 100))
    finish = max(begin, min(100.0, end / duration * 100))
    stops = [f'{begin:.4f}% {{ opacity: 1 }}']
    if begin > 0:
        stops.insert(0, f'0% {{ opacity: {dim} }}')
    if finish < 100:
        stops.append(f'{finish:.4f}% {{ opacity: {dim} }}')
    return f'.{name} {{ animation-name: k{name}; }}\n@keyframes k{name} {{ {" ".join(stops)} }}'


def render_line(runs) -> str:
    if not runs:
        return ''
    parts = []
    for text, foreground, background, bold in runs:
        styles = [f'color:{foreground}']
        if background != BACKGROUND:
            styles.append(f'background:{background}')
        if bold:
            styles.append('font-weight:700')
        parts.append(f'<span style="{";".join(styles)}">{html.escape(text)}</span>')
    return ''.join(parts)


def write_asciicast(cast, tape: Tape, path: Path) -> None:
    import json

    header = {
        'version': 2,
        'width': tape.columns,
        'height': tape.rows,
        'title': tape.title,
        'env': {'TERM': 'xterm-256color', 'SHELL': '/bin/bash'},
    }
    with path.open('w') as handle:
        handle.write(json.dumps(header) + '\n')
        for timestamp, chunk in cast:
            handle.write(json.dumps([round(timestamp, 4), 'o', chunk.decode('utf-8', 'replace')]) + '\n')


def record(
    tape_path: Path,
    page_path: Path,
    cast_path: Path | None = None,
    fps: int = 14,
    sandbox_root: Path | None = None,
) -> Path:
    """Execute a tape and write the watchable page beside it."""
    tape = load_tape(tape_path)
    print(f'recording {tape.title!r} ({len(tape.steps)} steps)', file=sys.stderr)

    sandbox = sandbox_root or page_path.parent / 'sandbox'
    cast, narration_track = record_tape(tape, sandbox)
    frames = render_frames(cast, tape.columns, tape.rows, fps)

    offset = find_first_painted_frame(frames)
    frames = [(stamp - offset, lines) for stamp, lines in frames if stamp >= offset]
    narration_track = [(max(0.0, start - offset), end - offset, text, command) for start, end, text, command in narration_track]
    duration = cast[-1][0] + 1.0 - offset

    page_path.write_text(render_html(tape, frames, narration_track, duration))
    if cast_path:
        write_asciicast(cast, tape, cast_path)

    size = page_path.stat().st_size / 1024
    print(
        f'{len(frames)} frames, {duration:.1f}s, {size:.0f}KB -> {page_path}',
        file=sys.stderr,
    )
    return page_path
