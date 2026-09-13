# Agent skills

Most contributors now work with a coding agent. This project ships a set of skills for them: short
orientation notes, one per kind of task, that tell an agent where the code for that task lives and
which pages of this site explain it.

They exist because an agent that has not been told where to look will reverse engineer the codebase
from whatever file it landed in, and get the same three things wrong every time -- that a card's id
is derived rather than written, that the committed YAML rather than the database is the source of
truth, and that the engine's game pieces change only through their transition methods.

A skill is orientation, not teaching. It says which area you are in and where its code is. The pages
on this site explain the thing itself, and travel with the skill so that an agent working offline,
or in a project that merely installed this package, can read them.

## Installing them

```bash
pixi run install-skills          # in a checkout of this repository
yasuki-install-skills            # in a project that installed the package
```

It installs into the current directory. Skills follow the [Agent Skills](https://agentskills.io)
standard -- a directory holding a `SKILL.md` with `name` and `description` frontmatter -- so one
copy serves every agent that implements it, and the only difference between agents is which
directory they read. All of them are written, because a contributor should not have to know which
of these their tool wants:

| Directory | Read by |
|---|---|
| `.agents/skills/` | GitHub Copilot, Cursor, opencode, pi |
| `.claude/skills/` | Claude Code, and also read by Copilot and opencode |
| `.github/skills/` | GitHub Copilot |
| `.cursor/skills/` | Cursor |
| `.opencode/skills/` | opencode |
| `.pi/skills/` | pi |

`--harness NAME` narrows it to one, repeatably, if you would rather keep your tree to the directory
your own agent reads.

A project also gets a short delimited block appended to its `AGENTS.md`. The installer owns what
lies between the markers and nothing else in the file, and a file carrying one marker without the
other is left alone. Nothing the installer did not create is ever replaced: an already-installed
skill is skipped unless you pass `--force`, which is how a local edit survives.

## The roster

Eight skills, named for the work rather than for the source directory it happens in.

| Skill | Use it when you are |
|---|---|
| `implementing-a-card` | Modeling a printed card: picking a hook, writing the handler, registering it |
| `card-vocabulary` | Working with what a card can express -- effects, triggers, abilities, costs, stats, gold -- or adding to it |
| `turns-and-actions` | Changing how a turn proceeds: phases, actions, legality, decisions, the replay log |
| `card-data` | Adding a set, correcting a card, issuing an erratum, adding card art |
| `card-search` | Changing the query language or what it compiles to |
| `play-server` | Working on rooms, the websocket play protocol, or the deck-builder backend |
| `desktop-client` | Working on the Tkinter board: rendering, input, the in-client deck builder |
| `accounts` | Working on login, sessions, saved decks, roles, or the accounts database |

Two boundaries are worth knowing, because they are the ones a task crosses mid-way.
`implementing-a-card` covers writing a handler and `card-vocabulary` covers what a handler may say,
so a card that needs a new effect is both. `turns-and-actions` covers the machinery that calls
handlers, not the handlers themselves.

## The instruction file

Alongside the skills is `src/yasuki_skills/AGENTS.md`, the conventions every agent should have read
before it touches anything: the package boundaries, the commands, the code and test conventions, and
what goes wrong most often. It is deliberately harness-neutral.

It does not live at the repository root. The installer places `AGENTS.md` and `CLAUDE.md` there as
symlinks to it, and both root names are in `.gitignore`, so each harness reads the same packaged
file instead of its own copy. Edit it at `src/yasuki_skills/AGENTS.md` rather than through a root
symlink: an editor that saves by writing a new file and renaming it over the old one replaces the
link with a regular file, which git then reports as a typechange.

## What a skill looks like

```
implementing-a-card/
  SKILL.md          # frontmatter, then the router
  references.txt    # the pages this skill carries
  references/       # those pages, written here at install time
```

That is the [Agent Skills](https://agentskills.io) layout: a directory named for the skill, a
`SKILL.md` carrying `name` and `description`, and `references/` for material the agent loads only
when it needs it. `references.txt` is ours -- the manifest the installer reads.

`SKILL.md` carries YAML frontmatter with a `name` and a `description`, then a body of four short
sections: where the code lives, what it does, what checks it, and how it fits the rest of the
project.

The `description` is what decides whether an agent loads the skill at all, so it is written as a
trigger specification rather than a summary: what the task is, the phrasings it should fire on, and
how it differs from the skills next to it. The frontmatter is the part most worth getting right and
the part that rots most quietly, because a description naming a module that has moved still looks
fine.

The body stays a router. A skill that restates its pages is a second copy to keep true, and the
copy is the one that goes stale.

`references.txt` lists the pages the skill carries, one repository-relative path per line. The
installer reads it, resolves each page's `literalinclude` directives against the current source, and
writes the result into `references/`. That is why a skill's code samples are the source's own text
rather than a copy of it: they are re-resolved every time the skill is installed, and an include
whose target has moved fails the install rather than shipping a page with a hole in it.

## Writing or changing one

Skills live in `src/yasuki_skills/skills/`. Edit them there, never in an installed copy -- an
installed skill is generated output, and a check will tell you when one has been edited by hand.

Three rules carry most of the weight:

- **Point at a page rather than summarizing it.** If the explanation does not exist on this site
  yet, write the page first. That is the whole reason the skills stay short.
- **Name real files.** Every path and module name in a `SKILL.md`, the frontmatter included, is
  checked by a pre-commit hook. A renamed module fails the commit that renamed it.
- **Say what the skill is not.** Each description names its neighbors and the boundary with them, so
  an agent picking between two of them picks correctly.
