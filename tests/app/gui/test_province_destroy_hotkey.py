from types import SimpleNamespace

from app.gui.field import GameField
from app.gui.config import Hotkeys
from app.engine.zones import ProvinceZone, DynastyDiscardZone
from app.game_pieces.dynasty import DynastyCard
from app.game_pieces.constants import Side


def test_hover_province_press_c_destroys_and_moves_to_discard(root, monkeypatch):
    field = GameField(root, width=600, height=400)
    field.pack()
    root.update_idletasks()
    root.update()

    # Two provinces and a dynasty discard zone
    prov1 = ProvinceZone()
    prov2 = ProvinceZone()
    prov1_tag = field.add_zone(prov1, x=150, y=200, w=120, h=160)
    _ = field.add_zone(prov2, x=300, y=200, w=120, h=160)

    discard = DynastyDiscardZone()
    field.add_zone(discard, x=500, y=200, w=120, h=160)

    # Put a dynasty card in prov1
    c = DynastyCard(id="dzz", name="DZ", side=Side.DYNASTY)
    prov1.add(c)

    # Hover the province and press destroy (default 'c')
    monkeypatch.setattr(field, "_resolve_tag_at", lambda e: prov1_tag)
    field._on_move(SimpleNamespace(x=150, y=200))
    assert field._hover_zone_tag == prov1_tag

    hk = Hotkeys()
    field._on_key(SimpleNamespace(keysym=hk.destroy))

    # Province zone removed
    assert prov1_tag not in field._zones
    # Card moved to dynasty discard face up
    assert len(discard) == 1
    assert discard.cards[-1].face_up is True
