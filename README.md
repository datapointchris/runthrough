# runthrough

Record a terminal session that actually happened, and watch it back.

A runthrough is a short animation of real commands producing real output. A tape declares the
commands. The recorder types each one into a pty, captures what came back with its timing, and
renders a self-contained HTML page. Nothing on that screen is authored by hand. That is the whole
point: a hand-written demo keeps playing perfectly long after the flag it teaches has been renamed.

It is not a screen recorder. Nobody sits at the keyboard during a recording, so one tape records
again after every release. A model can write the tape from a question in English. The model never
runs anything. It writes the tape, a guard reads it, and the recorder runs it.

## Install

runthrough installs as a uv tool, from the package index every release is published to. It needs
Python 3.13 or later.

```bash
uv tool install --index https://pypi.ichrisbirch.com/simple/ runthrough   # the newest release
runthrough --version                                                       # the release, and the commit it was built from
runthrough update --check                                                  # whether a newer release exists
```

Name the index on the install: without it uv asks PyPI, which does not carry runthrough. uv records
the index beside the tool, which is where `runthrough update` reads it back.

`runthrough update` reinstalls the newest release over the running one. It refuses an install from
a local checkout or from a branch, because neither carries a release version to compare. Every
other command checks for a newer release at most once a day, and names one it finds in a line on
stderr. Setting `RUNTHROUGH_NO_AUTO_UPDATE` turns that check
off.

Three programs sit outside the install:

- `claude`, Claude Code's CLI, installed and logged in. `ask` and `investigate` call it to write the
  tape. `play` never does.
- `fc-match`, from fontconfig. It finds the font file the page embeds. Without it, the page names a
  stock monospace stack instead.
- `xdg-open` on Linux, or `open` on macOS. It opens the finished page. `--no-watch` skips it.

## Starting from scratch

```bash
cd path/to/any/git/repo                                      # every step runs in the directory you start in
runthrough ask --cli git "what changed and who changed it"   # reads git's help, prints a tape, records only on y
runthrough library                                           # every kept demo, numbered
runthrough play                                              # pick one from that list, run it again, watch it
```

`ask` prints the tape it wrote to stderr, then asks `record this? [y/N]`. Any answer but `y` writes
nothing. A `y` writes three files into `~/.local/share/runthrough/`, each named from the question:
the tape, the page and an asciicast. The page opens when the recording ends.

`play` is the drift check. It runs the kept tape against the `git` installed today, and a renamed
flag shows up on the screen as git's own error.

A tape needs no model, and `play` never calls one. The `play` section below shows a tape written by
hand.

## Which surface answers which question

| Ask | Surface | Reads |
| --- | --- | --- |
| How do I show this with one command | `ask --cli <command>` | that command's `--help`, walked down its subcommands |
| How would I answer this across my tools | `investigate` | the two routing commands, the chosen tools' help, and the output of a few probe commands |
| Does this demo still hold after a release | `play` | the tape, and whatever its commands print now |
| What have I recorded | `library` | the `*.tape.yml` files in `~/.local/share/runthrough/` |
| Is a newer release out | `update --check` | the project's GitHub releases |

## `play` — the tape is the source, and the page is a build artifact

```bash
runthrough play 2                                # demo 2 in library; any part of a demo's name works too
runthrough play demo.tape.yml                    # runs each step in a pty, writes demo.html beside it, opens it
runthrough play demo.tape.yml --no-watch         # the same, with no browser
runthrough play demo.tape.yml --cast demo.cast   # also an asciicast v2 file, for any asciicast player
```

A tape is YAML. This one records against any git repository with three commits:

```yaml
title: What changed, and who changed it               # the page's heading; required
description: The files that moved, then the people who moved them.
sandbox: none                                         # xdg points the XDG roots into sandbox/ beside the page
steps:                                                # required
  - narrate: Every file the last two commits touched. # the caption while this step plays
    run: git diff --stat HEAD~2                       # required; run by the shell, in the pty
    pause: 2.0                                        # seconds to hold on the output
  - narrate: Who wrote each of those commits.
    run: git log --format='%h %an %s' -3
```

`name` titles the browser tab and the `library` listing. `tags` print on the page. `columns` and
`rows` size the screen. `typing_speed` is seconds per typed character. `max_gap` caps how long
playback sits on silence, so a slow command plays fast and none of its output changes. `env` sets
variables for every step.

Keep tapes, and regenerate pages.

`play` runs a tape exactly as written. The guards below belong to `ask` and `investigate`, which run
what a model wrote. A tape you wrote is yours, pipes and chaining included.

Each step's output goes to a terminal, so a tool that pages would open its pager and wait for a
keypress. Every step runs with its pager pointed at `cat`, so `git log` prints straight to the
screen. A step still running after two minutes is killed with everything it started, and the
recording stops on a line naming it.

`sandbox: xdg` redirects `XDG_DATA_HOME`, `XDG_CONFIG_HOME`, `XDG_STATE_HOME` and `XDG_CACHE_HOME`
into a `sandbox/` directory beside the page. That isolates local state and nothing else. The
directory outlives the recording, so the next one into the same place starts from what the last one
left. A CLI whose data lives behind an API is not sandboxed by it. That needs the tape's `env:`
block to point at a non-production endpoint, with a credential the sandbox can see. `env:` is
applied after the sandbox, so it can override any of the four.

## `ask` — one command, taught from nothing but its own help

```bash
runthrough ask --cli git "show me what changed and then who changed it"
runthrough ask --cli notes --sandbox "add a note, then find it"   # forces sandbox: xdg, for a demo that writes
runthrough ask --cli git --yes --no-watch "what changed today"    # no confirmation, and no browser
```

Help text is a grammar. It says which subcommands exist and which flags they take. It cannot say
that showing "one item blocked by another" means creating the first item, reading its number out of
the output, and passing that to a second command. That ordering is a sentence. It appears nowhere
in `--help`.

So the division is strict. The model reads help and writes JSON. It gets no tools. The `claude`
call denies each built-in tool by name, so the model cannot read a file or run a command. That list
is a deny list because `--allowedTools` pre-approves tools and leaves the rest reachable. The
recorder executes, and only after the tape passes a guard.

`ask`'s guard holds each step to one invocation of the named command. It refuses a pipe, `;`, `&`,
a backtick and `$(`. It refuses a redirect that writes a file, with or without a descriptor number,
so `2>out.txt` is refused and `2>/dev/null` passes. Past that, it does not judge whether a command
writes. The printed tape and the confirmation are for that. The prompt tells the model to set `sandbox: xdg` when any
step creates, edits or deletes data. `--sandbox` sets it regardless.

`ask` needs no configuration. It works against anything with a `--help`, because it parses both
rich/Typer panels and Cobra command lists. It walks the subcommand tree breadth-first until
`--budget` characters are spent, so a large CLI spends its allowance on breadth rather than on one
branch.

A tape the model wrote carries `authored_by`: the model that answered and the `claude` version that
asked it. Both are stamped after the reply is parsed, replacing anything the model put there, so
the model never attests to its own identity. When two regenerations of one tape differ, that field
says whether the model changed or the command did.

## `investigate` — a question across tools, answered only after it looks at the data

```bash
runthrough investigate "which deploys failed on staging this week"
```

`investigate` reads two routing commands from `$XDG_CONFIG_HOME/runthrough/config.yml`, which is
`~/.config/runthrough/config.yml` by default. Without both, it prints what to add and exits 1.
Nothing else reads them.

```yaml
routing:
  inventory: mytools list                    # a command that lists what you have
  search: mynotes search {query} --limit 8   # searches prose; {query} becomes the question, shell-quoted
```

Anything that prints a list works as an inventory. Anything that searches text works as a search.

It runs both, and a model picks the tools whose help is worth reading. It reads that help, then
**probes**. A model names two or three orienting commands, and each one runs for real. Their output
goes to the model before it writes anything. Help text describes flags and never describes values.
Without a look at the data, the model invents field names and greps for hostnames the records do
not contain.

The probes run before any tape is shown, so they pass the same guard as the steps. It allows pipes,
because a pipeline is much of what makes a query worth teaching. A `|` inside a quoted jq filter is
not a pipe stage. The guard refuses:

- chaining with `;`, `&&` or `||`, and a backtick
- a redirect that writes a file, where `2>/dev/null` and `2>&1` write none and pass
- `sudo`, `ssh`, an inline `-c` script, and a shell loop or conditional
- a command outside the read-only allowlist, which is `READ_COMMANDS` in
  `src/runthrough/investigate.py` plus each tool the router picked
- an argument that makes an allowlisted command write a file or run another, such as `sed -i`,
  `sort -o`, `find -delete`, a sed `w` command or an awk `system()`, as `WRITING_ARGUMENTS` in the
  same file lists them
- a mutating verb in the subcommand path of a tool the router picked, where `--verb apply` is a
  filter value and passes. An allowlisted command takes patterns and paths rather than
  subcommands, so `rg deploy src/` passes too.
- a pipeline or a line longer than a person would plausibly type

A question that asserts something false still gets an investigation. The authoring prompt asks for
the negative verdict where the evidence supports one. The premise is still the model's to test, and
it does not always test it.

## The page looks like your terminal, and carries its own font

```yaml
appearance:
  terminal_config: ~/.config/ghostty/config   # defaults to ghostty's own location
  font_family: Iosevka                        # defaults to the font-family that file names
  font_size: 14                               # defaults to the font-size that file names
```

That block sits in the same `config.yml`, and every key in it is optional.

The palette and font come from the terminal's own config. ghostty's is the default. On macOS that
is `~/Library/Application Support/com.mitchellh.ghostty/config` where it exists. Otherwise it is
`$XDG_CONFIG_HOME/ghostty/config`. Any file of `key = value` lines with `palette = N=#rrggbb`
entries works. `config-file` includes are followed, so a generated theme resolves the same way as
one written inline. A leading `?` on an include marks it optional, as it does in ghostty. Changing
theme or font changes the next recording with no edit here. A file with no palette renders every
ANSI color as the foreground.

Command-line coloring follows zsh-syntax-highlighting's stock styles.

Fonts are subset to the codepoints the page actually paints, then inlined. A Nerd Font runs to
megabytes. A page that depends on a font it cannot fetch renders in the wrong one.

The page follows the system's light or dark scheme. A click pauses it. With reduced motion
requested, it shows the last frame and no animation.

## Where it writes

- `ask` and `investigate` keep each tape, page and asciicast in `~/.local/share/runthrough/`. Their
  `--library` names another directory, and `library --library` reads it.
- `play` writes the page beside the tape, or at `--out`. It writes an asciicast only with `--cast`.
- A tape with `sandbox: xdg` gets a `sandbox/` directory beside its page.
- The update check records when it last ran under `$XDG_STATE_HOME/runthrough/`, which is
  `~/.local/state/runthrough/` by default.
- `config.yml` is read and never written.
