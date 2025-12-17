import tkinter as tk
from tkinter import scrolledtext


SEARCH_SYNTAX_HELP = """
SEARCH SYNTAX GUIDE
===================

Basic Search
------------
Just type text to search card names and rules text:
  Doji           → Find cards with "Doji" in name or text

Field-Specific Search
---------------------
Use field:value to search specific fields:

  name:Hoturi              → Card name contains "Hoturi"
  text:battle              → Rules text contains "battle"
  type:personality         → Card type is "personality"
  clan:Crane               → Clan is "Crane"
  deck:fate                → From Fate deck (FATE/DYNASTY)
  set:"Imperial Edition"   → From specific set
  rarity:rare              → Rarity is "rare"
  format:"Ivory Edition"   → Legal in format

Numeric Comparisons
-------------------
Use operators for numeric fields:

  force>3        → Force greater than 3
  force>=3       → Force greater than or equal to 3
  chi<2          → Chi less than 2
  chi<=2         → Chi less than or equal to 2
  gold:5         → Gold cost exactly 5
  focus=2        → Focus exactly 2

Numeric Fields:
  force, chi, focus, gold (cost), ph (personal honor),
  province (strength), startinghonor

Special Filters
---------------
  is:unique      → Only unique cards
  has:unique     → Same as is:unique
  is:experienced → Cards with "experienced" keyword
  has:experienced → Same as is:experienced
  is:cavalry     → Cards with "cavalry" keyword
  has:cavalry    → Same as is:cavalry
  is:kenshi      → Cards with "kenshi" keyword
  has:kenshi     → Same as is:kenshi
  is:<keyword>   → Any card keyword
  has:<keyword>  → Same as is:<keyword>

  Multiple keywords use AND logic (must have ALL):
  is:shugenja is:shadowlands  → Cards with BOTH keywords
  has:cavalry has:experienced → Cards with BOTH keywords

Exact Match
-----------
Use quotes for exact phrases:
  "Doji Hoturi"  → Exact name match

Negation
--------
Use minus sign to exclude:
  -type:event    → Exclude events
  -clan:Crab     → Exclude Crab clan

Combining Terms
---------------
Multiple terms are combined with AND by default:
  clan:Crane type:personality force>3

Use OR for alternatives:
  clan:Crane OR clan:Lion

Field Aliases
-------------
Short aliases for quick searching:
  t:personality  → type:personality
  c:Crane        → clan:Crane
  f>3            → force>3
  o:battle       → oracle/text:battle
  s:IE           → set:IE
  r:rare         → rarity:rare

Examples
--------
  name:Doji clan:Crane force>3
    → Crane Doji personalities with Force > 3

  t:personality f>=4 is:unique
    → Unique personalities with Force 4+

  c:Lion OR c:Unicorn
    → Cards from Lion or Unicorn clans

  -type:holding gold<=2
    → Cards costing 2 or less gold (not holdings)

  "Experienced 2" clan:Dragon
    → Experienced 2 Dragon cards

  is:cavalry t:personality
    → Cavalry personalities

  has:cavalry clan:Unicorn
    → Unicorn cavalry cards

  is:shugenja is:shadowlands
    → Cards with BOTH shugenja AND shadowlands keywords

  is:experienced clan:Crane
    → Crane cards with experienced keyword
"""


class SearchHelpDialog:
    """Dialog showing search syntax help."""

    def __init__(self, parent: tk.Misc):
        self.win = tk.Toplevel(parent)
        self.win.title("Search Syntax Help")
        self.win.geometry("700x600")
        if hasattr(parent, "winfo_toplevel"):
            self.win.transient(parent.winfo_toplevel())

        # Create scrolled text widget
        text_widget = scrolledtext.ScrolledText(
            self.win, wrap=tk.WORD, font=("Courier", 10), padx=10, pady=10
        )
        text_widget.pack(fill="both", expand=True, padx=5, pady=5)

        # Insert help text
        text_widget.insert(tk.END, SEARCH_SYNTAX_HELP)
        text_widget.configure(state="disabled")

        # Close button
        close_btn = tk.Button(self.win, text="Close", command=self.win.destroy)
        close_btn.pack(pady=5)

        # Center on parent
        self.win.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (self.win.winfo_width() // 2)
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (self.win.winfo_height() // 2)
        self.win.geometry(f"+{x}+{y}")


def show_search_help(parent: tk.Misc) -> None:
    """
    Show search syntax help dialog.

    Parameters
    ----------
    parent : tk.Misc
        Parent widget
    """
    SearchHelpDialog(parent)
