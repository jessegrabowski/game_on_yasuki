import tkinter as tk

import pytest

from yasuki_gui.ui.options_view import OptionsView


@pytest.fixture
def view():
    root = tk.Tk()
    root.geometry("1200x900")
    root.update_idletasks()
    yield OptionsView(root)
    root.destroy()


def _widgets(widget, kind):
    found = []
    for child in widget.winfo_children():
        if isinstance(child, kind):
            found.append(child)
        found.extend(_widgets(child, kind))
    return found


def _ask(view, answers, *, on_cancel=None):
    view.ask(
        "Which Invests do you pay?",
        ("Invest 2", "Invest 3"),
        lambda ticked: len(ticked) >= 1,
        answers.append,
        on_cancel,
    )


def test_submit_answers_with_what_is_ticked_once_it_is_accepted(view):
    answers = []
    _ask(view, answers)
    submit = next(b for b in _widgets(view.body, tk.Button) if b.cget("text") == "Submit")
    assert str(submit.cget("state")) == "disabled"

    _widgets(view.body, tk.Checkbutton)[1].invoke()
    submit.invoke()

    assert answers == [("Invest 3",)]


def test_cancel_is_offered_only_when_the_question_may_be_backed_out_of(view):
    cancelled = []
    _ask(view, [], on_cancel=lambda: cancelled.append(True))
    next(b for b in _widgets(view.body, tk.Button) if b.cget("text") == "Cancel").invoke()

    assert cancelled == [True]
    _ask(view, [])
    assert [b.cget("text") for b in _widgets(view.body, tk.Button)] == ["Submit"]


def _placed_height(view, options):
    view.ask("Which Invests do you pay?", options, lambda ticked: True, lambda ticked: None, None)
    view.open_at(0, 0)
    height = int(view.place_info()["height"])
    view.close()
    return height


def test_the_panel_is_as_tall_as_its_question_needs(view):
    four = _placed_height(view, tuple(f"Invest {cost}: a long printed effect" for cost in range(4)))
    two = _placed_height(view, ("Invest 2", "Invest 3"))

    assert two < four
    assert two == view.winfo_reqheight()
