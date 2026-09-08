import pytest

from yasuki_core.engine.rules.gold.discounts import RECRUIT_DISCOUNTS, recruit_discount


def test_a_second_recruit_discount_for_one_card_is_refused():
    @recruit_discount("guard_probe")
    def _first(card, game_, seat):
        return 0

    try:
        with pytest.raises(ValueError, match="guard_probe already has a recruit discount"):

            @recruit_discount("guard_probe")
            def _second(card, game_, seat):
                return 1
    finally:
        RECRUIT_DISCOUNTS.pop("guard_probe", None)
