# Claude Code - runthrough

Universal rules live in `~/.claude/CLAUDE.md`. `README.md` carries the design reasoning.

**This repo is public, and it names nothing private** (⚠️ MANDATORY): no private tool name, no
hostname, no machine layout, no internal directory — not in source, not in tests, not in help
text, not in a fixture. It went public once carrying three of them plus a pointer to an internal
directory, and someone else's sweep is what caught it.

Sweep before any commit that touches docs, tests or help strings. The term list is maintained in
one place, and this repo deliberately does not keep a second copy of it — it had one, and the two
diverged in both directions. The sweep is in the authoring standard, under "A repo is a product
for a stranger".

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
in `ask.py` and denies every built-in with `--disallowed-tools`. Naming that boundary here is
what `standards/repo-structure.md` § "Every external effect goes through one named chokepoint"
requires; widening it to let the model explore would remove the only structural reason the
guard is trustworthy.

The list is a deny list because an allow list does not confine a session: `--allowedTools`
pre-approves tools and leaves the rest reachable, so a session passed an empty allow list runs
Bash anyway. A tool added to the CLI's built-in set is a tool this list does not yet name.

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
