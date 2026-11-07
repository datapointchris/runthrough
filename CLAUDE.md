# Claude Code - runthrough

Universal rules live in `~/.claude/CLAUDE.md`. `README.md` carries the design reasoning.

`task setup` makes a fresh checkout runnable and installs the hooks. `task test`, `task lint`
(ruff and mypy, writing nothing) and `task format` are the everyday jobs. `task install` puts this
checkout in place of the released uv tool. `task --list` shows the rest.

**This repo is public, and it names nothing private** (⚠️ MANDATORY): no private tool name, no
hostname, no machine layout, no internal directory — not in source, not in tests, not in help
text, not in a fixture. It went public once carrying three of them plus a pointer to an internal
directory, and someone else's sweep is what caught it.

Sweep before any commit that touches docs, tests or help strings, and read every hit rather than
deleting it. The test is a stranger: someone who installs the tool, has never heard of the
author's setup, and runs it on its defaults gets a working tool and reads nothing that assumes
otherwise. The term list names the private things, so it never lives in this repo.

Keep the lesson of an incident and drop the locale. "A config deployed from a shared source
pointed one machine at a directory that only existed on another" carries the whole lesson and
names nothing private.

Sample data uses invented names: `deploy`, `notes`, `mytools`, `staging`.

**The machine's specifics are configuration, never literals** (⚠️ MANDATORY): the routing
commands and the terminal appearance both come from `config.py`. Two private tool invocations
were once hardcoded in the source, which made the tool unusable by anyone else and leaked what
the author runs. A path or command name written into a module is the same bug returning.

**The recording must never be authored** (⚠️ MANDATORY): every character on the screen comes
from a command that ran. Never add a way to inject expected output, stub a slow command, or
patch up a frame after capture. The moment a recording can lie, the library stops being a
drift check and becomes documentation that rots.

**The model gets no tools** (⚠️ MANDATORY): every `claude -p` call goes through `ask_model`
in `ask.py`, whose argv comes from `model_argv`. The boundary is named here because an effect
with one door is where a timeout, error translation and a test stub attach once, and an
undocumented door is one a future change walks straight past. Widening it to let the model
explore would remove the only structural reason the guard is trustworthy.

argv states the whole confinement, so it is the same on every machine and a test asserts it
without a model call:

- `--tools ""` gives the session no tool. `--allowed-tools` is never the confinement: it
  pre-approves tools and leaves the rest reachable.
- `--setting-sources ""` loads no settings file, so a machine's own settings cannot grant a tool
  back. A deny list fails there, because a settings file that allows a tool outranks it.
- `--permission-prompts none` refuses anything outside the list rather than waiting.
- `--safe-mode` keeps the user's CLAUDE.md, skills, hooks and MCP servers out of a call that
  answers only from its stdin.

**Every shell command line runs through `run_shell` in `investigate.py`**: the two routing
commands from the config and each probe that passed `check_command`. A timeout or error
translation for them changes there once. The direct process calls outside the two doors are
named, and nothing else spawns a process:

- `recorder.py` runs each tape step under a pty through `subprocess.Popen`, because the screen is
  read from the terminal it drives.
- `open_page` in `cli.py` starts the system opener detached, and waits for nothing.
- `run_help` and `claude_logged_in` in `ask.py`, and `resolve_font_file`'s `fc-match` in
  `recorder.py`, run a fixed argv with no shell.

**Every command `investigate` generates passes `check_command` before it runs**, and every step
`ask` writes passes `validate_tape`. What the code gets right that was a bug first, each pinned
by a test:

- Pipe splitting is quote-aware. A jq filter is full of `|` that never reaches the shell, and
  counting those rejects exactly the commands most worth teaching.
- Only a routed tool's subcommand path is checked for mutating verbs. `--verb apply` is a
  filter value, not an apply, and `deploy` in `rg deploy src/` is a search pattern.
- A redirect is read with its descriptor. `2>out.txt` writes a file as surely as `>out.txt`,
  while `>/dev/null` and `2>&1` write none.
- A `?` prefix on a `config-file` include is ghostty's suppress-if-absent marker, not part of
  the path. Treating it as a path yields no palette and nothing looks broken.

**A guard test that passes is not a guard test that works.** The suite went green with the
original pipe bug reintroduced, because it asserted on the helper rather than through
`check_command`. Reintroduce the bug and confirm a test dies before believing new coverage.

**The tape is JSON on the wire and YAML on disk.** The model returns JSON because a jq filter
carries colons and quotes that a YAML plain scalar cannot hold; that was a real parse failure
in both authoring paths. The saved tape is YAML because it is read by people.

**Test by recording.** A change to the recorder is verified by producing a page and looking at
it, not by unit tests alone — the failure modes are visual: a blank opening frame, a font that
did not load, an animation that never advances. `--no-watch` keeps that scriptable.
