import tkinter as tk


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


def test_a_toplevel_window_is_left_alone():
    # Only the root is forced out of sight. A Toplevel a widget opens for itself is untouched, so a
    # test that means to exercise a dialog still gets one.
    root = tk.Tk()
    try:
        dialog = tk.Toplevel(root)
        root.update_idletasks()
        assert dialog.state() == "normal"
        dialog.destroy()
    finally:
        root.destroy()
