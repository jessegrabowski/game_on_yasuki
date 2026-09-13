from dataclasses import dataclass


@dataclass(frozen=True)
class Harness:
    """One place skills are read from, named for the agent that reads it."""

    name: str
    directory: str
    reads: str


# Where each agent looks, taken from its own documentation. `.agents/skills/` is the neutral
# location several agents adopted; Claude Code reads only its own directory. Copilot and opencode
# read both. All of them are written unless --harness narrows it: they are small, inert where
# nothing reads them, and a contributor should not have to know which of these their tool wants.
HARNESSES = (
    Harness(
        name="agents", directory=".agents/skills", reads="GitHub Copilot, Cursor, opencode, pi"
    ),
    Harness(
        name="claude",
        directory=".claude/skills",
        reads="Claude Code, and also read by Copilot and opencode",
    ),
    Harness(name="copilot", directory=".github/skills", reads="GitHub Copilot"),
    Harness(name="cursor", directory=".cursor/skills", reads="Cursor"),
    Harness(name="opencode", directory=".opencode/skills", reads="opencode"),
    Harness(name="pi", directory=".pi/skills", reads="pi"),
)

BY_NAME = {harness.name: harness for harness in HARNESSES}
