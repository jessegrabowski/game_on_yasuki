import re
import tkinter as tk
from pathlib import Path


def test_a_root_built_inside_a_test_is_never_mapped():
    # The suite builds two dozen Tk roots, and a mapped one takes the developer's keyboard focus
    # from whatever else they are doing. The autouse guard in conftest withdraws every root at
    # construction; this is what stops that guard being removed or bypassed unnoticed.
    root = tk.Tk()
    try:
        assert root.winfo_viewable() == 0
        assert root.state() == "withdrawn"
    finally:
        root.destroy()


def test_a_dialog_window_is_never_mapped_either():
    # A dialog maps the moment anything pumps the event loop, and the test that opened it usually
    # has no handle to close it again — so one left open sits on the developer's screen for the rest
    # of the run. Withdrawing it changes nothing the widgets measure.
    root = tk.Tk()
    try:
        dialog = tk.Toplevel(root)
        root.update_idletasks()

        assert dialog.winfo_viewable() == 0
        assert dialog.state() == "withdrawn"
        dialog.destroy()
    finally:
        root.destroy()


def test_no_gui_test_binds_tk_past_the_guard():
    # The guard patches ``tkinter.Tk``, so every ``tk.Tk()`` call goes through it. ``from tkinter
    # import Tk`` binds the name at import time, before any fixture runs, and would map a window
    # again — invisibly, since the suite would still pass.
    binds_tk = re.compile(r"^\s*from tkinter import .*\bTk\b", re.MULTILINE)
    suite = Path(__file__).parent
    offenders = sorted(
        str(path.relative_to(suite))
        for path in suite.rglob("*.py")
        if binds_tk.search(path.read_text())
    )

    assert offenders == []
