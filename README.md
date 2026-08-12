# runthrough

Record a terminal session that actually happened, and watch it back.

A runthrough is a short animation of real commands producing real output. The commands are
declared in a tape; the recorder types them into a pty, captures what came back with its
timing, and renders a self-contained HTML page. Nothing on that screen is authored by hand,
which is the whole point — a hand-written demo keeps playing perfectly long after the flag
it teaches has been renamed.

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

So the division is strict. The model reads help and writes YAML, with no tools and no ability
to execute anything. The recorder executes, and only after the tape passes a guard that
rejects chaining, redirects, inline scripts, commands outside a read-only allowlist, and
anything longer than a person would plausibly type. `runthrough ask` demonstrates one command
from its own help. `runthrough fleet` answers a question that spans tools, routing through the
tool registry and the semantic index to work out which ones to read.

Before authoring, `fleet` probes: it runs two or three orienting commands for real and feeds
their output to the model. This is not optional polish. Without it the model invents field
names and greps for hostnames the records do not contain, because help text describes flags
and never describes values.

## Why it looks like your terminal

The palette comes from the ghostty theme in use, the font from the ghostty font config, and
the command-line colouring from zsh-syntax-highlighting's own stock styles. Change theme or
font and the next recording follows without an edit. Fonts are subset to the codepoints the
page actually paints and inlined, because a Nerd Font is megabytes and a page that depends on
a font it cannot fetch is a page that renders in the wrong one.

Run `runthrough --help` for the commands.

## Known limits

Sandboxing redirects the four XDG roots, which isolates local state and nothing else. A CLI
whose data lives behind an API is not sandboxed by it — that needs the tape's `env:` block to
point at a non-production endpoint, and a credential the sandbox can see.

A question that asserts something false will still get an investigation. The authoring prompt
asks for the negative verdict where the evidence supports one, but the premise is the model's
to test and it does not always test it.
