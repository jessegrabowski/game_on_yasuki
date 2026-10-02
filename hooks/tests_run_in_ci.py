import pathlib
import re
import shlex
import subprocess
import sys
import tomllib

WORKFLOW = ".github/workflows/ci.yml"

TEST_SUBSET = re.compile(r'^\s*test-subset:\s*"([^"]*)"', re.MULTILINE)

PIXI_TASK = re.compile(r"pixi run (?:-e \S+ )?([\w-]+)")


def subset_paths(workflow: str) -> set[str]:
    """Return every path a ``test-subset`` of the test matrix names."""
    return {path for subset in TEST_SUBSET.findall(workflow) for path in subset.split()}


def task_paths(workflow: str, tasks: dict[str, str]) -> tuple[set[str], set[str]]:
    """Return the paths the pytest tasks ``workflow`` runs collect, and the paths they ignore.

    A task counts when its command starts with ``pytest``. One run with ``-m`` is left out: a
    marker filter runs only the tests that carry the marker, not every test under its paths.

    Parameters
    ----------
    workflow : str
        The workflow file's text.
    tasks : dict of str to str
        Each pixi task's name and command.

    Returns
    -------
    collected : set of str
        The test paths the tasks name.
    ignored : set of str
        The paths those tasks pass to ``--ignore``.
    """
    collected, ignored = set(), set()
    for name in PIXI_TASK.findall(workflow):
        words = shlex.split(tasks.get(name, ""))
        if words[:1] != ["pytest"] or "-m" in words:
            continue

        collected |= {word for word in words if word.startswith("tests")}
        ignored |= {
            word.removeprefix("--ignore=") for word in words if word.startswith("--ignore=")
        }

    return collected, ignored


def pixi_tasks(pyproject: str) -> dict[str, str]:
    """Return each pixi task's name and command, for the tasks written as a plain string."""
    tasks = tomllib.loads(pyproject).get("tool", {}).get("pixi", {}).get("tasks", {})

    return {name: command for name, command in tasks.items() if isinstance(command, str)}


def test_files(repo: pathlib.Path) -> list[str]:
    """Return every tracked test module under ``tests/``, as a path relative to ``repo``."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "tests/"], cwd=repo, capture_output=True, text=True, check=True
    )
    paths = (path for path in listed.stdout.split("\0") if path)

    modules = (pathlib.PurePosixPath(path) for path in paths)

    return sorted(str(module) for module in modules if module.match("test_*.py"))


def unrun(files: list[str], collected: set[str], ignored: set[str]) -> list[str]:
    """Return the ``files`` under no ``collected`` path, or under one only by way of ``ignored``."""

    def under(path: str, roots: set[str]) -> bool:
        return any(path == root or path.startswith(root.rstrip("/") + "/") for root in roots)

    return [path for path in files if not under(path, collected) or under(path, ignored)]


def main() -> int:
    """Report every test module that no CI job runs.

    Returns
    -------
    status : int
        Zero when every test module is under a path some job collects.
    """
    repo = pathlib.Path.cwd()
    workflow = (repo / WORKFLOW).read_text(encoding="utf-8")
    tasks = pixi_tasks((repo / "pyproject.toml").read_text(encoding="utf-8"))

    collected, ignored = task_paths(workflow, tasks)
    missing = unrun(test_files(repo), subset_paths(workflow) | collected, ignored)

    for path in missing:
        print(f"{path}: no job in {WORKFLOW} runs it")

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
