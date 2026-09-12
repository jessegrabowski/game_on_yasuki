# The Favor and the court

```{card-image} Manjodh
:printing: chaos_reigns_part_i
:width: 220px
```

Most cards that touch the Imperial Favor are one registration. This page is the three registries
and the card that explains why a printed timing is sometimes not the one to implement.
[The Imperial Favor](../design/systems/the-imperial-favor.md) is the system.

## Paying somebody's Favor cost

A Favor cost is normally paid by discarding the Favor, and a card can offer to pay it instead.
`@favor_payer` is keyed by printed id and returns the price, or None when the card cannot pay right
now:

```python
@favor_payer("manjodh")
def _manjodh_favor_payer(game: GameState, card: L5RCard) -> list[Effect] | None:
    if card.bowed or has_wind(game, card.owner):
        return None
    return [Bow(card.id)]
```

Returning None is how a payer declines. Bowed, or its controller has a Wind, and Manjodh is simply
not among the options offered.

## When the printed timing is wrong

{card}`Manjodh` prints an Interrupt. He is implemented as a payer, and the handler says why:

```python
@favor_payer("manjodh")
def _manjodh_favor_payer(game: GameState, card: L5RCard) -> list[Effect] | None:
    """ "Political Interrupt, :bow:: If you have no Wind, pay the action's :favor: cost."

    Implemented as a payer priced at bowing rather than as the Interrupt it prints. Costs are paid
    at step B of the Action Sequence and Interrupts are played at D, so the printed window opens
    two steps after the cost it names — a contradiction in the card that no correct Interrupt round
    would resolve. Offering him where every other payer is offered delivers what the card is for.
    """
```

Copy the habit, not the shortcut. The designator was not implementable as printed, the reason is a
rules citation, and the justification is longer than the code it explains. A handler that departs
from the printed text without saying why is indistinguishable from one that got it wrong.

## Lobby

Lobby shares the Favor's payment machinery and is a separate rule. Three registries cover almost
every card that touches it.

The two that look alike stop different things. `@lobby_bar` stops a whole player from taking the
action. `register_may_not_lobby` stops one Personality from being bowed to pay for it.

A bar is a function, because the card decides which seats it stops. {card}`Wasp Sensei` is asked
about each seat in turn:

```python
@lobby_bar("wasp_sensei")
def _wasp_sensei_lobby_bar(game: GameState, card: L5RCard, seat: PlayerId) -> bool:
```

A flag is one line, because the card states the restriction flatly and admits no condition:

```python
register_may_not_lobby("moto_chen")
```

{func}`~.lobby_candidates` skips a flagged Personality when it collects what a seat could bow.

The third registry, `@lobby_bonus_grant`, adds to what a seat's Lobby is worth.

## Where the rest lives

[Writing an ability](an_ability.md) is the four parts, and
[Asking the player a question](asking_a_question.md) covers the choice a Favor payment raises when
more than one card offers to pay.
