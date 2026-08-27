import tkinter as tk


def widget_size(widget: tk.Misc) -> tuple[int, int]:
    """How big ``widget`` is to lay out into: the size Tk has laid it out at, or the size it asked
    for while Tk has not laid it out at all.

    A widget Tk has not reached yet reports one pixel, and a layout computed against that collapses
    to its floors. The requested size stands in until then — but only until then, since a widget
    that has since been made smaller than it asked for is genuinely that size.

    Returns
    -------
    width : int
        The widget's width in pixels, never below one.
    height : int
        The widget's height in pixels, never below one.
    """
    width, height = widget.winfo_width(), widget.winfo_height()
    return (
        width if width > 1 else max(widget.winfo_reqwidth(), 1),
        height if height > 1 else max(widget.winfo_reqheight(), 1),
    )
