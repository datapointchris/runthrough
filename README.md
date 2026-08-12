# runthrough

Record a terminal session that actually happened, and watch it back.

A runthrough is a short animation of real commands producing real output. The commands are
declared in a tape; the recorder types them into a pty, captures what came back with its
timing, and renders a self-contained HTML page. Nothing on that screen is authored by hand,
which is the whole point — a hand-written demo keeps playing perfectly long after the flag
it teaches has been renamed.

```bash
runthrough ask --cli git "show me what changed and then who changed it"
runthrough play mytape.yml
runthrough library
```

## Why the recording is executed rather than drawn

A synthetic animation is documentation that cannot fail. It rots silently: the CLI changes,
the demo still plays, and it now teaches something false. Executing the tape inverts that.
When a command loses a flag, the recorder captures the error onto the screen where it is
impossible to miss, so regenerating the library after a release doubles as a drift check.

The tape is the source and the page is a build artifact. Keep tapes, regenerate pages.

## Why a model writes the tape and a program runs it

Help text is a grammar. It says which subcommands exist and which flags they take. It cannot
say that showing "one item blocked by another" means creating the first item, reading its
number out of the output, and passing that to a second command — that ordering is a sentence,
and it appears nowhere in `--help`.

So the division is strict. The model reads help and writes JSON, with no tools and no ability
to execute anything. The recorder executes, and only after the tape passes a guard that
rejects chaining, redirects, inline scripts, commands outside a read-only allowlist, and
anything longer than a person would plausibly type.

`runthrough ask` demonstrates one command, reading only that command's own help. It needs no
configuration and works against anything with a `--help`, since it parses both rich/Typer
panels and Cobra command lists.

`runthrough investigate` answers a question spanning several tools. It asks the machine what
it has, reads the help for what looks relevant, then **probes** — running two or three
orienting commands for real and feeding their output to the model before it writes anything.
That step is not optional polish. Help text describes flags and never describes values, so
without a look at the data the model invents field names and greps for hostnames the records
do not contain.

## Configuration

`~/.config/runthrough/config.yml`, and everything in it is optional.

```yaml
routing:
  inventory: mytools list                 # a command that lists what you have
  search: mynotes search {query} --limit 8  # a command that searches prose

appearance:
  terminal_config: ~/.config/ghostty/config  # defaults to ghostty's own location
  font_family: Iosevka                       # defaults to whatever that config says
  font_size: 14
```

`investigate` needs the two `routing` commands and says so if they are missing; nothing else
does. Anything that prints a list works as an inventory, and anything that searches text works
as a search.

## Why it looks like your terminal

The palette and font come from the terminal's own config, and `config-file` includes are
followed — so a generated theme resolves the same way as one written inline, and changing
theme or font changes the next recording with no edit here. Command-line colouring follows
zsh-syntax-highlighting's stock styles.

Fonts are subset to the codepoints the page actually paints and inlined, because a Nerd Font
runs to megabytes and a page that depends on a font it cannot fetch renders in the wrong one.

## Known limits

Sandboxing redirects the four XDG roots, which isolates local state and nothing else. A CLI
whose data lives behind an API is not sandboxed by it — that needs the tape's `env:` block to
point at a non-production endpoint, and a credential the sandbox can see.

A question that asserts something false will still get an investigation. The authoring prompt
asks for the negative verdict where the evidence supports one, but the premise is the model's
to test and it does not always test it.

`ask` and `investigate` shell out to `claude`. `play` does not, and needs nothing but the tape.
