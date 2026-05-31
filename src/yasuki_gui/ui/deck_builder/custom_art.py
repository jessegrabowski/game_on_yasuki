from pathlib import Path

from PIL import Image

from yasuki_core.card_art import CustomPrint, art_rect, classify, cover_crop, custom_print_id
from yasuki_core.paths import resolve_set_image_path


def _box(image: Image.Image, rect: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    w, h = image.size
    left, top, right, bottom = rect
    return (round(left * w), round(top * h), round(right * w), round(bottom * h))


def composite_art(
    recipient_path: Path,
    donor_path: Path,
    recipient_key: tuple[str, str],
    donor_key: tuple[str, str],
) -> Image.Image:
    """Crop the donor's art (its layout's cut rect) into the recipient's art window.

    The donor crop is reduced to the window's aspect ratio before scaling, so the art fills the
    window edge-to-edge without distortion (a thin strip of the donor's outer edge is trimmed)."""
    recipient = Image.open(recipient_path).convert("RGB")
    donor = Image.open(donor_path).convert("RGB")
    window = _box(recipient, art_rect(recipient_key))
    target_w, target_h = window[2] - window[0], window[3] - window[1]
    source = cover_crop(_box(donor, art_rect(donor_key)), target_w, target_h)
    art = donor.crop(source).resize((target_w, target_h), Image.LANCZOS)
    out = recipient.copy()
    out.paste(art, (window[0], window[1]))
    return out


def custom_print_record(recipe: CustomPrint, repository) -> dict:
    """A synthetic print dict for a recipe, shaped like a DB print so it flows through the UI."""
    donor = repository.get_card(recipe.donor_card_id) or {}
    donor_name = donor.get("extended_title") or donor.get("name") or recipe.donor_card_id
    return {
        "print_id": custom_print_id(recipe),
        "card_id": recipe.recipient_card_id,
        "set_name": f"Custom · {donor_name}",
        "image_path": None,
        "back_image_path": None,
        "flavor_text": "",
        "is_custom": True,
        "recipe": recipe,
    }


def render_custom_image(recipe: CustomPrint, repository) -> Image.Image | None:
    """Recompose a recipe's art from its recipient and donor printings, or None if either is missing."""
    recipient_card = repository.get_card(recipe.recipient_card_id)
    donor_card = repository.get_card(recipe.donor_card_id)
    if not recipient_card or not donor_card:
        return None

    recipient_print = _find_print(repository, recipe.recipient_card_id, recipe.recipient_print_id)
    donor_print = _find_print(repository, recipe.donor_card_id, recipe.donor_print_id)
    if not recipient_print or not donor_print:
        return None

    recipient_path = resolve_set_image_path(recipient_print.get("image_path") or "")
    donor_path = resolve_set_image_path(donor_print.get("image_path") or "")
    if not (recipient_path and recipient_path.exists() and donor_path and donor_path.exists()):
        return None

    recipient_key = classify(recipient_card, recipient_print.get("set_name", ""))
    donor_key = classify(donor_card, donor_print.get("set_name", ""))
    return composite_art(recipient_path, donor_path, recipient_key, donor_key)


def _find_print(repository, card_id: str, print_id: int) -> dict | None:
    return next((p for p in repository.get_prints(card_id) if p["print_id"] == print_id), None)
