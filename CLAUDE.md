# Claude Code - runthrough

Universal rules live in `~/.claude/CLAUDE.md`. `README.md` carries the design reasoning.

**This repo is public, and it names nothing private** (⚠️ MANDATORY): no tool of Chris's, no
hostname, no machine layout, no internal directory — not in source, not in tests, not in help
text, not in a fixture. It went public once carrying `toolbox`, `indy`, `macmini` and a
pointer to the standards directory, and a peer's sweep is what caught it. Before any commit
that touches docs, tests or help strings:

```bash
rg -i -w 'toolbox|indy|icb|doit|forge|dotfiles|macmini|mbp|ichrisbirch|syncthing' \
  --glob '!uv.lock' --glob '!CHANGELOG.md' .
```

Sample data uses invented names — `deploy`, `notes`, `mytools`, `staging`. The only surviving
hit is the generated `[tool.forge]` block in `pyproject.toml`, which is a build marker.

**The machine's specifics are configuration, never literals** (⚠️ MANDATORY): the routing
commands and the terminal appearance both come from `config.py`. `toolbox list` and
`indy search` were hardcoded in the source and made the tool unusable by anyone else while
leaking what Chris runs. A path or command name written into a module is the same bug
returning.

**The recording must never be authored** (⚠️ MANDATORY): every character on the screen comes
from a command that ran. Never add a way to inject expected output, stub a slow command, or
patch up a frame after capture. The moment a recording can lie, the library stops being a
drift check and becomes documentation that rots.

**The model gets no tools** (⚠️ MANDATORY): every `claude -p` call goes through `ask_model`
in `ask.py` and passes `--allowedTools ""`. One door, per the fleet standard that an external
effect gets exactly one chokepoint. Widening this to let the model explore would remove the
only structural reason the guard is trustworthy.

**Every generated command passes `check_command` before it runs.** Three things it gets right
that were bugs first, all three now pinned by tests:

- Pipe splitting is quote-aware. A jq filter is full of `|` that never reaches the shell, and
  counting those rejects exactly the commands most worth teaching.
- Only the subcommand path is checked for mutating verbs. `--verb apply` is a filter value,
  not an apply.
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
