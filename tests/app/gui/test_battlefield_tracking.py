from app.gui.field import GameField
from app.engine.zones import BattlefieldZone
from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side


def test_battlefield_tracks_added_cards(root):
    field = GameField(root, width=400, height=300)
    field.pack()
    root.update_idletasks()
    root.update()
    bf = BattlefieldZone()
    field.set_battlefield_zone(bf)

    c1 = L5RCard(id="b1", name="Battle1", side=Side.FATE)
    c2 = L5RCard(id="b2", name="Battle2", side=Side.DYNASTY)

    field.add_card(c1, x=100, y=100)
    field.add_card(c2, x=200, y=120)

    assert len(bf) == 2
    assert bf.cards[-2].id == "b1"
    assert bf.cards[-1].id == "b2"
