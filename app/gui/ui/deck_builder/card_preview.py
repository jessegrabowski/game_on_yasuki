import logging
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageTk

from app import paths as asset_paths
from app.paths import ASSETS_DIR
from app.gui.constants import CARD_W, CARD_H

logger = logging.getLogger(__name__)

PREVIEW_CARD_W = 4 * CARD_W
PREVIEW_CARD_H = 4 * CARD_H

DEFAULT_BY_TYPE: dict[str, Path] = {
    "strategy": asset_paths.DEFAULT_STRATEGY,
    "ring": asset_paths.DEFAULT_RING,
    "sensei": asset_paths.DEFAULT_SENSEI,
    "wind": asset_paths.DEFAULT_WIND,
    "stronghold": asset_paths.DEFAULT_STRONGHOLD,
    "item": asset_paths.DEFAULT_ITEM,
    "follower": asset_paths.DEFAULT_FOLLOWER,
    "spell": asset_paths.DEFAULT_SPELL,
    "personality": asset_paths.DEFAULT_PERSONALITY,
    "holding": asset_paths.DEFAULT_HOLDING,
    "event": asset_paths.DEFAULT_EVENT,
    "region": asset_paths.DEFAULT_REGION,
    "celestial": asset_paths.DEFAULT_CELESTIAL,
}


def _extract_base_name(full_name: str) -> str:
    """
    Extract base personality name without subtitle.

    Handles patterns like:
    - "Daigotsu Kanpeki, Clan Champion" -> "Daigotsu Kanpeki"
    - "Daigotsu Kanpeki" -> "Daigotsu Kanpeki"
    - "Daigotsu Kanpeki (Bio)" -> "Daigotsu Kanpeki (Bio)"

    Parameters
    ----------
    full_name : str
        Full card name possibly including subtitle after comma

    Returns
    -------
    base_name : str
        Name without subtitle (before first comma, or full name if no comma)
    """
    if ", " in full_name:
        return full_name.split(", ")[0]
    return full_name


def _extract_experience_from_extended_title(extended_title: str) -> str:
    """
    Extract the experience marker from extended title.

    Examples:
    - "Daigotsu Kanpeki • Experienced 2" -> "- Experienced 2"
    - "Daigotsu Kanpeki" -> ""

    Parameters
    ----------
    extended_title : str
        Extended title from database

    Returns
    -------
    experience : str
        Experience marker with leading dash, or empty string
    """
    if " • " in extended_title:
        parts = extended_title.split(" • ", 1)
        if len(parts) > 1:
            return f" - {parts[1]}"
    return ""


def format_card_display_name(
    card: dict, set_name: str | None = None, include_subtitle: bool = False
) -> str:
    """
    Format card name for display without deck prefix or ID.

    By default, hides subtitles (text after comma) to reduce clutter in filter lists.
    Shows base name + experience level instead.

    Parameters
    ----------
    card : dict
        Card record from database
    set_name : str or None
        Set name to include as suffix in brackets
    include_subtitle : bool
        If True, include subtitle (e.g., ", Clan Champion"). Default False.

    Returns
    -------
    display_name : str
        Formatted name like "Daigotsu Kanpeki - Experienced 2 [Set Name]"
    """
    extended_title = card.get("extended_title")
    name = card.get("name", "")
    card_type = card.get("type", "").lower()

    if card_type == "personality" and extended_title and not include_subtitle:
        base_name = _extract_base_name(name)
        experience = _extract_experience_from_extended_title(extended_title)
        display_name = f"{base_name}{experience}"
    elif extended_title:
        display_name = extended_title
    else:
        if not include_subtitle:
            name = _extract_base_name(name)
        exp_level = _extract_experience_level(card)

        display_parts = [name]
        if exp_level:
            display_parts.append(_format_experience_level(exp_level))
        display_name = " ".join(display_parts)

    if set_name:
        display_name = f"{display_name} [{set_name}]"

    return display_name


def _extract_experience_level(card: dict) -> str | None:
    """
    Extract experience level from card data.

    Handles:
    - Inexperienced cards (_inexp)
    - Regular experienced (_exp, _exp2, _exp3, etc.)
    - Campaign experienced (_expcow, _expcw, etc.)
    """
    card_id = card.get("id", "")

    if "_inexp" in card_id:
        return "inexp"

    if "_exp" in card_id:
        parts = card_id.split("_exp")
        if len(parts) > 1:
            exp_suffix = parts[-1]

            if not exp_suffix or exp_suffix == "":
                return "exp"

            if exp_suffix.startswith("_") and exp_suffix[1:].isdigit():
                level = int(exp_suffix[1:])
                return f"exp{level}"

            if exp_suffix.isdigit():
                return f"exp{exp_suffix}"

            if "_" in exp_suffix:
                parts = exp_suffix.split("_")
                if parts[0].isdigit():
                    level_num = parts[0]
                    campaign_code = parts[1].lower()
                    return f"exp{level_num}_{campaign_code}"

                campaign_code = exp_suffix.lower()
                return f"exp_{campaign_code}"

            return "exp"

    return None


def _format_experience_level(exp_level: str) -> str:
    """
    Format experience level for display.

    Examples:
    - "inexp" -> "- Inexperienced"
    - "exp" -> "- Experienced"
    - "exp2" -> "- Experienced 2"
    - "exp_cow" -> "- Experienced (CoW)"
    - "exp2_cow" -> "- Experienced 2 (CoW)"
    """
    if not exp_level:
        return ""

    if exp_level == "inexp":
        return "- Inexperienced"

    if exp_level == "exp":
        return "- Experienced"

    if exp_level.startswith("exp") and exp_level[3:].isdigit():
        level_num = exp_level[3:]
        return f"- Experienced {level_num}"

    if "_" in exp_level:
        parts = exp_level.split("_")

        if len(parts) == 2 and parts[0] == "exp":
            campaign = parts[1].upper()
            return f"- Experienced ({campaign})"

        if len(parts) == 2 and parts[0].startswith("exp"):
            exp_part = parts[0]
            if exp_part[3:].isdigit():
                level_num = exp_part[3:]
                campaign = parts[1].upper()
                return f"- Experienced {level_num} ({campaign})"

    return f"- {exp_level}"


def load_large_image(image_path: Path, master: tk.Misc) -> ImageTk.PhotoImage | None:
    """
    Load a large preview image for the deck builder.

    Parameters
    ----------
    image_path : Path
        Path to the image file
    master : tk.Misc
        Tkinter master widget for PhotoImage

    Returns
    -------
    photo : PhotoImage or None
        Resized image at PREVIEW size, or None if loading fails
    """
    try:
        img = Image.open(str(image_path))
        resample = getattr(Image, "LANCZOS", getattr(Image, "Resampling", Image).LANCZOS)
        img = img.resize((PREVIEW_CARD_W, PREVIEW_CARD_H), resample)
        return ImageTk.PhotoImage(img, master=master)
    except Exception:
        return None


class CardPreviewController:
    """Controls card preview display with image, stats, and print navigation."""

    def __init__(
        self,
        image_label: tk.Label,
        stats_panel,
        text_widget: tk.Text,
        flavor_widget: tk.Text,
        print_selector,
        master: tk.Widget,
        repository,
    ):
        self.image_label = image_label
        self.stats_panel = stats_panel
        self.text_widget = text_widget
        self.flavor_widget = flavor_widget
        self.print_selector = print_selector
        self.master = master
        self.repository = repository

        self._current_card_id: str | None = None
        self._current_prints: list[dict] = []
        self._current_print_index: int = 0

    def load_card(self, card_id: str, preferred_print_id: int | None = None) -> None:
        """
        Load a card and its prints for preview.

        Parameters
        ----------
        card_id : str
            Card identifier
        preferred_print_id : int or None
            Specific print to show initially
        """
        self._current_card_id = card_id
        self._current_prints = self.repository.get_prints(card_id)
        self._current_print_index = 0

        if not self._current_prints:
            self.clear()
            logger.warning(f"No prints found for card {card_id}")
            return

        if preferred_print_id is not None:
            for i, p in enumerate(self._current_prints):
                if p["print_id"] == preferred_print_id:
                    self._current_print_index = i
                    break

        self.update_display()

    def prev_print(self) -> None:
        """Navigate to the previous print of the current card."""
        if not self._current_prints:
            return
        self._current_print_index = (self._current_print_index - 1) % len(self._current_prints)
        self.update_display()

    def next_print(self) -> None:
        """Navigate to the next print of the current card."""
        if not self._current_prints:
            return
        self._current_print_index = (self._current_print_index + 1) % len(self._current_prints)
        self.update_display()

    def update_display(self) -> None:
        """Update the preview to show the currently selected print."""
        if not self._current_prints or self._current_print_index >= len(self._current_prints):
            self.clear()
            return

        print_info = self._current_prints[self._current_print_index]
        logger.debug(f"Current print: {print_info}")

        card = self.repository.get_card(self._current_card_id)

        if not card:
            self.clear()
            return

        self._update_print_selector(print_info)
        self._render_image(card, print_info)
        self._render_stats(card)
        self._render_flavor(print_info)
        self._render_text(card)

    def _update_print_selector(self, print_info: dict) -> None:
        set_name = print_info.get("set_name", "Unknown")
        self.print_selector.update(set_name, self._current_print_index, len(self._current_prints))

    def _render_image(self, card: dict, print_info: dict) -> None:
        """Render card image in preview."""
        photo = self._load_card_image(card, print_info)

        if photo is not None:
            self.image_label.configure(image=photo)  # type: ignore[arg-type]
            self.image_label.image = photo  # type: ignore[attr-defined]
        else:
            self.image_label.configure(image="")
            self.image_label.image = None  # type: ignore[attr-defined]

    def _load_card_image(self, card: dict, print_info: dict) -> ImageTk.PhotoImage | None:
        """Load card image or fallback to default."""
        img_path = self._resolve_image_path(card, print_info)
        if img_path and img_path.exists():
            return load_large_image(img_path, self.master)

        return self._load_back_image(card)

    def _resolve_image_path(self, card: dict, print_info: dict) -> Path | None:
        """Resolve image path from print info or card type default."""
        img_path_str = print_info.get("image_path")
        if img_path_str and (ASSETS_DIR / img_path_str).exists():
            return ASSETS_DIR / img_path_str

        ctype = card.get("type", "").lower()
        return DEFAULT_BY_TYPE.get(ctype)

    def _load_back_image(self, card: dict) -> ImageTk.PhotoImage | None:
        """Load card back image as fallback."""
        side = str(card.get("side", "FATE")).upper()
        back_path = asset_paths.FATE_BACK if side == "FATE" else asset_paths.DYNASTY_BACK
        return load_large_image(back_path, self.master)

    def _render_stats(self, card: dict) -> None:
        """Render card statistics."""
        self.stats_panel.update_stats(card)
        self.master.update_idletasks()

    def _render_flavor(self, print_info: dict) -> None:
        """Render card flavor text from print info."""
        self.flavor_widget.configure(state="normal")
        self.flavor_widget.delete("1.0", tk.END)

        flavor = print_info.get("flavor_text") or ""
        self.flavor_widget.insert("1.0", flavor)
        self.flavor_widget.configure(state="disabled")

    def _render_text(self, card: dict) -> None:
        """Render card rules text."""
        self.text_widget.configure(state="normal")
        self.text_widget.delete("1.0", tk.END)
        body = card.get("text") or ""
        self.text_widget.insert("1.0", body)
        self.text_widget.configure(state="disabled")

    def clear(self) -> None:
        """Clear all preview elements."""
        self.image_label.configure(image="")
        self.image_label.image = None
        self.stats_panel.clear()
        self.flavor_widget.configure(state="normal")
        self.flavor_widget.delete("1.0", tk.END)
        self.flavor_widget.configure(state="disabled")
        self.text_widget.configure(state="normal")
        self.text_widget.delete("1.0", tk.END)
        self.text_widget.configure(state="disabled")
        self.print_selector.clear()

    def get_current_card_id(self) -> str | None:
        return self._current_card_id

    def get_current_print_id(self) -> int | None:
        if self._current_prints and self._current_print_index < len(self._current_prints):
            return self._current_prints[self._current_print_index]["print_id"]
        return None
