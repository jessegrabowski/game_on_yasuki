from dataclasses import dataclass

from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side
from app.gui.constants import CARD_W, CARD_H
from app.gui.images import load_image, load_back_image
from app.gui.visuals.visual import Visual


@dataclass
class CardSpriteVisual(Visual):
    card: L5RCard
    x: int
    y: int
    tag: str

    @property
    def size(self) -> tuple[int, int]:
        w, h = CARD_W, CARD_H
        return (h, w) if self.card.bowed else (w, h)

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        w, h = self.size
        x0 = self.x - w // 2
        y0 = self.y - h // 2
        x1 = self.x + w // 2
        y1 = self.y + h // 2
        return x0, y0, x1, y1

    def draw(self, canvas, selected: bool = False) -> None:
        x, y = self.x, self.y
        w, h = self.size
        bowed = self.card.bowed
        inverted = self.card.inverted
        face_up = self.card.face_up

        side_outline = "#007acc" if self.card.side is Side.FATE else "#b58900"
        base_border = 4 if inverted else 1

        if face_up:
            photo = load_image(self.card.image_front, bowed, master=canvas)
            if photo is not None:
                canvas.create_image(x, y, image=photo, tags=(self.tag, "card"))
                canvas.create_rectangle(
                    x - w // 2,
                    y - h // 2,
                    x + w // 2,
                    y + h // 2,
                    outline=side_outline,
                    width=base_border,
                    tags=(self.tag, "card"),
                )
                if selected:
                    canvas.create_rectangle(
                        x - w // 2,
                        y - h // 2,
                        x + w // 2,
                        y + h // 2,
                        outline="#66ccff",
                        width=2,
                        tags=(self.tag, "card"),
                    )
                return
        else:
            photo = load_back_image(self.card.side, bowed, self.card.image_back, master=canvas)
            if photo is not None:
                canvas.create_image(x, y, image=photo, tags=(self.tag, "card"))
                canvas.create_rectangle(
                    x - w // 2,
                    y - h // 2,
                    x + w // 2,
                    y + h // 2,
                    outline=side_outline,
                    width=base_border,
                    tags=(self.tag, "card"),
                )
                if selected:
                    canvas.create_rectangle(
                        x - w // 2,
                        y - h // 2,
                        x + w // 2,
                        y + h // 2,
                        outline="#66ccff",
                        width=2,
                        tags=(self.tag, "card"),
                    )
                return

        # Fallback: rect + text
        fill = "#fafafa" if face_up else "#6b6b6b"
        border_w = base_border + (2 if selected else 0)
        canvas.create_rectangle(
            x - w // 2,
            y - h // 2,
            x + w // 2,
            y + h // 2,
            fill=fill,
            outline=side_outline,
            width=border_w,
            tags=(self.tag, "card"),
        )
        label = f"{self.card.name}\n{'Bowed' if bowed else 'Ready'}\n{'Face Up' if face_up else 'Face Down'}\n{'Inverted' if inverted else ''}"
        canvas.create_text(x, y, text=label, fill="#202020", tags=(self.tag, "card"))
