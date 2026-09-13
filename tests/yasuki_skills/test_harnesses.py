from yasuki_skills.harnesses import BY_NAME, HARNESSES

# The directory each agent reads, from its own documentation. Pinned here because a typo installs
# to a path nothing reads and nothing else in the suite would notice.
DOCUMENTED = {
    "agents": ".agents/skills",
    "claude": ".claude/skills",
    "copilot": ".github/skills",
    "cursor": ".cursor/skills",
    "opencode": ".opencode/skills",
    "pi": ".pi/skills",
}


def test_each_agent_reads_the_directory_its_documentation_names():
    assert {harness.name: harness.directory for harness in HARNESSES} == DOCUMENTED


def test_every_directory_is_project_relative():
    """A '~' or '/' here would be created as a literal directory of that name."""
    assert all(not harness.directory.startswith(("/", "~")) for harness in HARNESSES)


def test_every_harness_is_addressable_by_name():
    """A duplicated name would drop a harness from the lookup and from the --harness choices."""
    assert len(BY_NAME) == len(HARNESSES)


def test_no_two_harnesses_write_the_same_directory():
    directories = [harness.directory for harness in HARNESSES]

    assert len(set(directories)) == len(directories)
