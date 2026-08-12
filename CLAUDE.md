# Claude Code - runthrough

Universal rules live in `~/.claude/CLAUDE.md`; how the fleet builds things lives in
`standards/`. Neither is restated here. `README.md` carries the design reasoning.

**The recording must never be authored** (⚠️ MANDATORY): every character on the screen comes
from a command that ran. Never add a way to inject expected output, stub a slow command, or
patch up a frame after capture. The moment a recording can lie, the library stops being a
drift check and becomes documentation that rots.

**The model gets no tools** (⚠️ MANDATORY): every `claude -p` call passes `--allowedTools ""`.
The model reads help text and probe output as plain text and returns a tape. Execution belongs
to the recorder, behind the guard. Widening this to let the model explore would remove the only
structural reason the guard is trustworthy.

**Every generated command passes `check_command` before it runs.** The guard rejects shell
chaining, redirects, loops, `bash -c`, commands outside the read-only allowlist, and mutating
subcommands. Two things it deliberately gets right, both of which were bugs first:

- Pipe splitting is quote-aware. A jq filter is full of `|` that never reaches the shell, and
  counting those rejects exactly the commands most worth teaching.
- Only the subcommand path is checked for mutating verbs. `--verb apply` is a filter value, not
  an apply, and treating it as one rules out most report queries.

**Appearance is read from the machine, never hardcoded.** Palette from
`~/.config/ghostty/themes/current.conf`, font from `fonts/current.conf`, command colouring from
zsh-syntax-highlighting's stock styles. A colour written into this repo is a bug — it will
disagree with the terminal the recording claims to be.

**The tape is JSON on the wire and YAML on disk.** The model returns JSON because a jq filter
carries colons and quotes that a YAML plain scalar cannot hold; that was a real parse failure,
not a hypothetical. The saved tape is YAML because it is read by people.

**Test by recording.** A change to the recorder is verified by producing a page and looking at
it, not by unit tests alone — the failure modes are visual (a blank opening frame, a font that
did not load, an animation that never advances). `--no-watch` keeps that scriptable.
