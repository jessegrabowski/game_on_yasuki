import pathlib
import subprocess
import sys

from yasuki_core.engine import rules

RULES = pathlib.Path(rules.__file__).parent


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
