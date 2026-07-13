import tkinter as tk

import pytest

from yasuki_gui.ui.prompt_box import PromptBox


@pytest.fixture
def root():
    r = tk.Tk()
    r.withdraw()
    yield r
    r.destroy()


def _buttons(box: PromptBox) -> list[tk.Button]:
    return [w for w in box._actions.winfo_children() if isinstance(w, tk.Button)]


def test_show_renders_the_status_text(root):
    box = PromptBox(root)
    box.show("Your turn", [])
    assert box._status.cget("text") == "Your turn"


def test_show_renders_a_button_per_spec_and_invokes_its_command(root):
    clicks = []
    box = PromptBox(root)
    box.show("Your turn", [("Pass", lambda: clicks.append("pass"), True)])

    buttons = _buttons(box)
    assert [b.cget("text") for b in buttons] == ["Pass"]
    buttons[0].invoke()
    assert clicks == ["pass"]


def test_show_disables_buttons_marked_not_enabled(root):
    box = PromptBox(root)
    box.show("discard 1 card(s)", [("Discard", lambda: None, False)])
    assert str(_buttons(box)[0].cget("state")) == "disabled"


def test_show_replaces_the_previous_buttons(root):
    box = PromptBox(root)
    box.show("Your turn", [("Pass", lambda: None, True)])
    box.show("Opponent's turn", [])
    assert _buttons(box) == []


def test_invoke_primary_clicks_the_sole_enabled_button(root):
    clicks = []
    box = PromptBox(root)
    box.show("Your turn", [("Pass", lambda: clicks.append("pass"), True)])
    box.invoke_primary()
    assert clicks == ["pass"]


def test_invoke_primary_ignores_a_disabled_button(root):
    clicks = []
    box = PromptBox(root)
    box.show("pay 5 gold", [("Pay", lambda: clicks.append("pay"), False)])
    box.invoke_primary()
    assert clicks == []


def test_invoke_primary_clicks_the_first_button_not_a_secondary(root):
    clicks = []
    box = PromptBox(root)
    box.show(
        "Pay 5 gold",
        [
            ("Pay", lambda: clicks.append("pay"), True),
            ("Cancel", lambda: clicks.append("cancel"), True),
        ],
    )
    box.invoke_primary()
    assert clicks == ["pay"]  # the affirmative action, never the trailing Cancel


def test_invoke_primary_skips_a_disabled_primary_even_with_an_enabled_secondary(root):
    clicks = []
    box = PromptBox(root)
    box.show(
        "Pay 5 gold",
        [
            ("Pay", lambda: clicks.append("pay"), False),
            ("Cancel", lambda: clicks.append("cancel"), True),
        ],
    )
    box.invoke_primary()
    assert clicks == []  # spacebar must not fire Cancel when Pay is unaffordable


def test_invoke_primary_is_safe_with_no_buttons(root):
    box = PromptBox(root)
    box.show("Opponent's turn", [])
    box.invoke_primary()  # must not raise
