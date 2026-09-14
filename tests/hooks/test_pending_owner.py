import pathlib

from hooks.pending_owner import main

HANDLER = """def apply_thing(game, request, response):
    game.pending = None
    game.pending = ask_again(game)
"""


def written(tmp_path: pathlib.Path, relative: str, source: str) -> str:
    module = tmp_path / relative
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(source, encoding="utf-8")
    return str(module)


def test_a_handler_that_clears_the_request_is_reported_by_line(tmp_path, capsys):
    module = written(tmp_path, "src/yasuki_core/engine/rules/rulebook/thing.py", HANDLER)

    assert main([module]) == 1
    assert (
        capsys.readouterr().out == f"{module}:2: clears game.pending; only submit and cancel may\n"
    )


def test_the_decision_layer_may_clear_it(tmp_path):
    module = written(tmp_path, "src/yasuki_core/engine/rules/turn/action_sequence.py", HANDLER)

    assert main([module]) == 0


def test_setting_a_request_is_not_clearing_it(tmp_path):
    module = written(
        tmp_path, "src/yasuki_core/engine/rules/rulebook/thing.py", "game.pending = ask(game)\n"
    )

    assert main([module]) == 0
