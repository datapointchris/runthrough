# CHANGELOG


## v1.0.1 (2026-08-21)

### Bug Fixes

- **ask**: Confine the model session with a deny list
  ([`067c66f`](https://github.com/datapointchris/runthrough/commit/067c66ffb925a22d4217b496694e314032abda31))

An allow list does not restrict a session. `claude -p --allowedTools ""` pre-approves tools and
  leaves every other one reachable, so the session that authors a tape could run Bash, read the
  machine, and reach the network. On a machine whose settings set bypassPermissions there was
  nothing else between it and the disk.

The session is handed help text and probe output on stdin and returns JSON. It needs no tool at all,
  so every built-in is denied. Execution stays with the recorder, behind check_command, after a
  person has read the tape.

The argv is asserted in tests/test_ask_model.py, because the confinement is entirely a property of
  the arguments and nothing else would catch a regression.

### Chores

- **pyproject**: Raise assertion verbosity instead of test verbosity
  ([`1bfbc71`](https://github.com/datapointchris/runthrough/commit/1bfbc719714bbe4b1f47f96c43272e8546ca0ca6))

A failing assertion truncated its diff and printed "use -vv to show", so the reader re-ran the whole
  suite to see it. addopts = "-vv" answered that by raising test-list verbosity as well, which is a
  different question: a green run printed a line per test and said nothing. verbosity_assertions
  raises only the half that was wanted.

Written by the forge pyproject die.

### Continuous Integration

- Regenerate validate.yml at toolchain 16
  ([`51285ab`](https://github.com/datapointchris/runthrough/commit/51285ab705ec1b270f039a67c45837289cf1883b))

Catches this repo up with the version manifest: StyLua pinned to a release rather than latest, a
  reworded bats discovery note, and double quotes in the node block. Only the blocks this repo
  declares are affected.

Triggers and job structure are unchanged.

### Documentation

- Stop naming private tooling in a public repo
  ([`fc3b094`](https://github.com/datapointchris/runthrough/commit/fc3b0944339091d9a42144fd47ed6a67a5809833))

The rule against it was stated at the top of CLAUDE.md and broken seven lines below, in the sweep
  meant to catch it — and again in the incident telling, twice in a docstring, and once in a
  comment.

The sweep itself is gone from here. It had drifted from the canonical one in both directions, so
  each list missed what the other caught. One copy now, in the authoring standard.

The repo sweeps clean.

### Refactoring

- Remove the module investigate.py replaced
  ([`0ed17da`](https://github.com/datapointchris/runthrough/commit/0ed17da94fcc1d62e8407f3a6f5b8eaf08ff2ea9))

The rename commit added the new module but its pathspec never named the deletion, so both files
  shipped. The old one still carried the hardcoded routing commands this repo had just moved into
  config.


## v1.0.0 (2026-08-12)

### Refactoring

- Read the machine's specifics from config, not from source
  ([`21b937c`](https://github.com/datapointchris/runthrough/commit/21b937cc58c623785ce98a74144bd3431d6f0dc9))

Two commands and one theme layout were written into the source: `toolbox list` and `indy search` as
  the routing pair, and a generated theme file's path as the palette. Neither is a property of
  recording a terminal. Both made the tool unusable by anyone else, and both described the author's
  machine in a public repo.

Routing is now `routing.inventory` and `routing.search` in ~/.config/runthrough/config.yml. Anything
  that lists and anything that searches will do. Without them `investigate` says what to set and
  why; `play` and `ask` never needed them.

Appearance now reads the terminal's own config and follows `config-file` includes, which is both
  general and more correct than naming a generator's output: a `?` prefix is ghostty's
  suppress-if-absent marker, and treating it as part of the path was why the palette silently fell
  back to defaults.

BREAKING CHANGE: `runthrough fleet` is now `runthrough investigate`, and the module with it. The old
  name described whose machine it was written on rather than what the command does.

Sample data throughout the tests now uses invented tools rather than real ones.

### Breaking Changes

- `runthrough fleet` is now `runthrough investigate`, and the module with it. The old name described
  whose machine it was written on rather than what the command does.


## v0.1.0 (2026-08-12)

### Bug Fixes

- Parse every tape as JSON, from one place
  ([`959af70`](https://github.com/datapointchris/runthrough/commit/959af709d8de6193c77f3970ff1a68fabb367818))

`ask` still asked the model for YAML, so any command carrying a colon — a jq filter, a quoted phrase
  with `: ` in it — produced a tape that would not load. That failure was already hit and fixed in
  `fleet`; this brings `ask` onto the same footing instead of leaving the bug latent in the path
  that is reached first.

parse_tape now lives beside the help gathering that `fleet` already imports from, so there is one
  parser rather than a copy per caller, and clean_yaml becomes strip_fences, which is what it always
  did.

- Retry when the reply arrives without the tape
  ([`fbdf1ec`](https://github.com/datapointchris/runthrough/commit/fbdf1ecc7c4762632e2ccc8891b5f2ed3bb0dc83))

The model sometimes answers with the tape and then a closing remark, and `claude -p` returns only
  that last message — so the JSON is gone rather than malformed and nothing in the reply can be
  salvaged. Seen live: a fleet run came back with "The tape JSON above was the deliverable; the work
  is complete" and no tape. Asking again, with a line saying the JSON is the only thing read,
  recovers it.

The retry needs somewhere to live, and there were two model call sites to choose between. Both now
  go through one function in ask.py, per the fleet standard that an external effect gets exactly one
  door — which is also where the no-tools guarantee is stated once instead of twice.

### Build System

- Release on push to main via python-semantic-release
  ([`6f7c400`](https://github.com/datapointchris/runthrough/commit/6f7c400024e9a82d9f85fbf1c1ca2a90643b32fb))

The standard Python release for this fleet: conventional commits drive the bump, the tag and the
  GitHub release follow, and no binaries are needed.

The package name in build_command is written out rather than referenced as $PACKAGE_NAME.
  python-semantic-release does not set that variable, so the variable form no-ops silently and ships
  a stale uv.lock inside the release.

Dormant until the repo has a remote, which is Chris's call to make.

### Chores

- Adopt the generated tool configuration
  ([`ee9ce8c`](https://github.com/datapointchris/runthrough/commit/ee9ce8ccebbe708062a7febd24811bc305e838fa))

The pyproject and markdownlintignore dies own [tool.*] and the ignore list, so the hand-written mypy
  block becomes generator-managed and the source is reformatted to the standard's line length, quote
  style and import order.

### Features

- Answer --version, and make the read verb scriptable
  ([`188b1e4`](https://github.com/datapointchris/runthrough/commit/188b1e4654bb7cb42216e7de79fa819e6841a22e))

Every tool in the fleet answers --version in one line naming itself, with the commit appended when
  the build came from a git ref — which is how the fleet installs everything. Read from the
  installed dist-info, so it costs no dependency and no network.

`library` gains --json like every other read verb, and its empty state now says what to type instead
  of only reporting the absence.

The retry added in the previous commit had no tests, which is the same gap that let the guard suite
  pass with its bug reintroduced. Removing the retry now fails three of the four cases.

- Record real terminal sessions and author them from a question
  ([`fdc482e`](https://github.com/datapointchris/runthrough/commit/fdc482eeb3a916155c42e57a0e178f11e294d213))

A runthrough is a short animation of commands that actually ran. The tape declares them, the
  recorder types them into a pty and captures what came back with its timing, and the page is
  rendered from those frames. Nothing on the screen is authored, so a recording that stops matching
  the CLI fails loudly instead of teaching a flag that no longer exists.

Three entry points. `play` records a tape you already have. `ask` reads one command's own help and
  writes the tape for it. `fleet` answers a question spanning tools, routing through the tool
  registry and the semantic index to choose them, then probing with real commands before authoring —
  help text describes flags and never describes values, and without a look at the data the model
  invents field names and greps for hostnames the records lack.

The model never executes anything: every call passes --allowedTools "" and returns only a tape.
  Execution belongs to the recorder, behind a guard that rejects chaining, redirects, inline
  scripts, commands outside a read-only allowlist, and anything longer than a person would plausibly
  type. Pipe splitting is quote-aware so a jq filter's own pipes do not count, and only the
  subcommand path is scanned for mutating verbs so --verb apply reads as the filter it is.

Appearance is read from the machine rather than hardcoded: palette from the active ghostty theme,
  font subset from the configured family and inlined as woff2, command colouring from
  zsh-syntax-highlighting's stock styles.

### Testing

- Cover the guard, which decides what is allowed to run
  ([`c1203b5`](https://github.com/datapointchris/runthrough/commit/c1203b5996ef4fca6611d4589c511e4a14f66165))

Every case is a real failure or near-miss from building the tool rather than a hypothetical, because
  the two bugs found so far both rejected legitimate commands: counting a jq filter's own pipes as
  shell pipes, and reading a `--verb apply` filter value as an apply.

The jq case is written as a whole command through check_command, not only against split_pipeline.
  Asserting on the helper alone let the original bug be reintroduced with the suite still green,
  which a mutation run confirmed before this case was added.
