import ast
import pathlib
import subprocess
import sys

import yasuki_core
from yasuki_core import bots, engine
from yasuki_core.engine import rules

CORE = pathlib.Path(yasuki_core.__file__).parent
RULES = pathlib.Path(rules.__file__).parent
ENGINE = pathlib.Path(engine.__file__).parent
BOTS = pathlib.Path(bots.__file__).parent
# yasuki_core is the substrate the other two packages sit on. It may not import either of them, or
# the dependency runs both ways and neither can be used without the other.
FORBIDDEN = ("yasuki_web", "yasuki_gui")


def _imported_modules(source: pathlib.Path) -> set[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_core_imports_nothing_from_the_ui_packages():
    # Reports every offender at once: a back-edge is usually introduced by a move that touches
    # several files, and fixing them one failure at a time is needless.
    offending = [
        f"{source.relative_to(CORE)} imports {name}"
        for source in sorted(CORE.rglob("*.py"))
        for name in sorted(_imported_modules(source))
        if name.split(".")[0] in FORBIDDEN
    ]

    assert offending == []


def test_the_scan_can_see_an_offending_import(tmp_path):
    # Guards the test above: a scanner that found nothing would pass it vacuously.
    probe = tmp_path / "probe.py"
    probe.write_text("from yasuki_gui.session import build_demo_state\nimport yasuki_web.main\n")

    found = {name.split(".")[0] for name in _imported_modules(probe)}

    assert found >= set(FORBIDDEN)


def test_no_package_reexports():
    # Empty __init__ files buy one import path per symbol, which is what makes a module relocatable
    # by rewriting its path everywhere. A facade doubles that: the symbol is importable from the
    # package and from the module that defines it, so a rewrite silently misses half its call
    # sites. It also makes the package one import node, which puts a cycle within reach --
    # test_the_rules_package_has_no_import_cycle is what catches that if one closes. Every package
    # under engine/ and bots/ is scanned, so one added later is covered without being listed here.
    # cards/ is the documented exception -- it aggregates its set modules on purpose, guarded by
    # its own test.
    offenders = {
        str(path.relative_to(CORE))
        for root in (ENGINE, BOTS)
        for path in root.rglob("__init__.py")
        if path.parent.name != "cards"
        and any(
            isinstance(node, ast.Import | ast.ImportFrom)
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        )
    }

    assert offenders == set()


def test_the_rules_layer_does_not_reach_into_the_bots():
    # A policy reads a redacted GameView and decides; a rule decides what is legal. The dependency
    # runs one way, with no exception: the one that used to exist was a validator filed as a rule.
    reaching = {
        str(source.relative_to(RULES))
        for source in sorted(RULES.rglob("*.py"))
        for name in _imported_modules(source)
        if name.startswith("yasuki_core.bots")
    }

    assert reaching == set()


def test_the_stats_package_never_reads_the_gold_economy():
    # A stat is what a card is; gold is what a seat has and pays. Gold reads stats -- a Gold Cost is
    # a stat and effective_gold_cost is one line over effective_stat -- so the dependency has to run
    # one way or the two are a single tangle again under new names.
    reaching = {
        str(source.relative_to(RULES))
        for source in sorted((RULES / "stats").rglob("*.py"))
        for name in _imported_modules(source)
        if name.startswith("yasuki_core.engine.rules.gold")
    }

    assert reaching == set()


def test_the_favor_and_lobby_surfaces_stay_out_of_abilities():
    # abilities.py held the favor payment surface, the Lobby bars and the Lobby bonuses in three
    # places, none of them consumed by its own ability model. They are one subject each now, in
    # rulebook/. A three-way split is exactly the shape that regrows, so this names the words
    # rather than the symbols -- a new favor helper written into abilities/ fails here.
    offenders = {
        f"{source.relative_to(RULES)}:{number}"
        for source in sorted((RULES / "abilities").rglob("*.py"))
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1)
        if line.startswith(("def ", "class ", "FAVOR", "LOBBY", "MAY_NOT_LOBBY"))
        and ("favor" in line.lower() or "lobby" in line.lower())
    }

    assert offenders == set()


def test_importing_the_engine_registers_the_cards():
    # The registries are populated by importing the card modules for their side effects, so a
    # dropped import leaves every one of them empty and every card silently inert. The suite would
    # not notice: any test that touches a card puts the modules in sys.modules for the rest of the
    # session. A subprocess is the only way to see what a fresh consumer sees.
    program = (
        "from yasuki_core.engine.session import EngineSession\n"
        "from yasuki_core.engine.rules.abilities.registry import _ABILITIES\n"
        "print(len(_ABILITIES))\n"
    )
    registered = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=True
    )

    assert int(registered.stdout) > 0


def test_the_rules_package_has_no_import_cycle():
    # Every module by name in a fresh interpreter, in sorted order: a cycle that the package's own
    # import order happens to paper over still breaks the first consumer that reaches the modules
    # in a different order, and nothing else in the suite imports them one at a time. One order
    # rather than every order, so this catches a cycle sorted order reaches and not a cycle only
    # some other order would.
    modules = sorted(
        "yasuki_core.engine.rules." + str(path.relative_to(RULES))[:-3].replace("/", ".")
        for path in RULES.rglob("*.py")
        if path.name != "__init__.py" and "cards" not in path.parts
    )
    program = "".join(f"import {name}\n" for name in modules)
    attempt = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True)

    assert attempt.returncode == 0, attempt.stderr


def test_the_board_substrate_does_not_read_the_rules():
    # engine/ is one flat namespace holding two tiers, and only the import graph says which is
    # which. Everything below names the board -- zones, cards, the ops that move them -- and the
    # rules layer is built on it, so a substrate module reading a rule inverts the dependency and
    # drags the whole turn structure into the manual intent path that yasuki_gui and yasuki_web
    # drive. Only the two surfaces above the rules are excepted, and both are named here.
    #
    # Deliberately shallow: engine/rules/ is not substrate, so a recursive scan would report the
    # layering working as intended.
    above_the_rules = {"session.py", "driver.py"}
    reaching = {
        source.name
        for source in sorted(ENGINE.glob("*.py"))
        if source.name not in above_the_rules
        for name in _imported_modules(source)
        if name.startswith("yasuki_core.engine.rules")
    }

    assert reaching == set()


def test_the_board_substrate_does_not_read_the_bots():
    # A policy is a consumer of the engine, at the same level as sim/, and bots/ sits beside engine/
    # to say so. A substrate module importing one inverts that and drags the AI into the manual
    # intent path yasuki_gui and yasuki_web drive. The headless driver is the exception and stays
    # one, because running a game means handing it an Agent and a Policy.
    drives_a_policy = {"driver.py"}
    reaching = {
        source.name
        for source in sorted(ENGINE.glob("*.py"))
        if source.name not in drives_a_policy
        for name in _imported_modules(source)
        if name.startswith("yasuki_core.bots")
    }

    assert reaching == set()
