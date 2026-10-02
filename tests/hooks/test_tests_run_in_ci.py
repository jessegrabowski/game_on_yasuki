from hooks.tests_run_in_ci import pixi_tasks, subset_paths, task_paths, unrun

WORKFLOW = """
jobs:
  test:
    strategy:
      matrix:
        include:
          - subset-name: "Core Tests"
            test-subset: "tests/yasuki_core/"
          - subset-name: "Skills Tests"
            test-subset: "tests/yasuki_skills/ tests/hooks/"
  e2e-test:
    steps:
      - run: pixi run test-e2e
  docker-test:
    steps:
      - run: pixi run db-only
"""

PYPROJECT = """
[tool.pixi.tasks]
test-e2e = "pytest tests/e2e --ignore=tests/e2e/slow"
db-only = "pytest tests/ -m db"
lint = { cmd = "ruff check" }
"""


def test_every_path_of_a_subset_is_collected():
    assert subset_paths(WORKFLOW) == {"tests/yasuki_core/", "tests/yasuki_skills/", "tests/hooks/"}


def test_a_task_filtered_by_marker_collects_nothing():
    collected, ignored = task_paths(WORKFLOW, pixi_tasks(PYPROJECT))

    assert collected == {"tests/e2e"}
    assert ignored == {"tests/e2e/slow"}


def test_a_module_outside_every_collected_path_is_reported():
    files = [
        "tests/yasuki_core/test_cards.py",
        "tests/yasuki_web/test_rooms.py",
        "tests/e2e/test_board.py",
        "tests/e2e/slow/test_long.py",
        "tests/e2e_extra/test_stray.py",
    ]
    collected = subset_paths(WORKFLOW) | {"tests/e2e"}

    assert unrun(files, collected, {"tests/e2e/slow"}) == [
        "tests/yasuki_web/test_rooms.py",
        "tests/e2e/slow/test_long.py",
        "tests/e2e_extra/test_stray.py",
    ]
