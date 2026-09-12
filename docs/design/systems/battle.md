# Battle

Battle adds vocabulary nothing else uses. Three of the eight action timings belong to it, a card may
carry designators that lift rules the rest of the game takes as written, and the three attacks are
effects with a comparison instead of a fixed outcome.
[The turn machine](turn-flow.md) is where the windows come from.

## Three windows

`ActionTiming.ATTACK` opens in the Battle Phase and belongs to the active player alone.
`ActionTiming.ENGAGE` and `ActionTiming.BATTLE` open in a battle's Engage and Combat Segments, and
both seats get them:

```python
Phase.BATTLE: RoundTimings(active=frozenset({ActionTiming.ATTACK}), others=frozenset()),
```

An ability printed `Battle:` is an ordinary `register_ability` call carrying
`ActionTiming.BATTLE`. Nothing else about it is special.

## Designators

{class}`~.BattleDesignator` qualifies how a battle action escapes two rules:

```text
ABSENT
    Playable without presence at the current battlefield.
HOME
    Usable from a card at home rather than at the current battlefield. It does not lift the
    Rule of Presence, which the datasheet says in as many words: the two are independent, and a
    card needs ``ABSENT`` as well to be used by a seat with no presence.
REMOTE
    Usable from a card at home or at another battlefield — a wider ``HOME``.
```

`ABSENT` is the only one any implemented card carries. {card}`Refugees`, {card}`Man the Walls!`
and {card}`Outer Walls` are the cards that do. `HOME` and `REMOTE` are declared and no card carries
either, so their behavior rests on nothing a test exercises.

`targets_any_location` sits beside them and does a different job: it lifts the Rules of Location
off what an ability may be pointed at, without lifting them off the card the ability is taken from.
`located_at`, which decides where the card itself must stand, matters here too, and
[Cards that act from outside play](../../contributing/cards_outside_play.md) works through it.

What a card's own `targets` function returns is narrowed centrally before the ability is offered.
[Actions and legality](actions-and-legality.md) has that.

## The three attacks

{class}`~.RangedAttack`, {class}`~.MeleeAttack` and {class}`~.Fear` are effects taking a strength,
a target and a cause. The whole comparison is on the shared base:

```python
def perform(self, game: GameState) -> list[GameEvent]:
    # Imported where it is used: reading an attack's strength walks the board for the cards
    # adjusting it, and that module imports this one for the attack types.
    from yasuki_core.engine.rules.attack_effects import effective_strength

    card = game.table.cards_by_id.get(self.target_id)
    if card is None or effective_stat(game, card, self.compared) > effective_strength(
        game, self
    ):
        return []
    return self._outcome().perform(game)
```

Both sides are effective values. The target's stat is read with its modifiers, and the strength is
read with whatever the board has done to it. An attack that reaches nothing returns no events, so
nothing downstream can react to a miss.

The three kinds differ in one method:

```python
@dataclass(frozen=True, slots=True)
class RangedAttack(AttackEffect):
    ...
    name: ClassVar[str] = "ranged"

    def _outcome(self) -> Effect:
        return Destroy(self.target_id, self.cause)


@dataclass(frozen=True, slots=True)
class MeleeAttack(AttackEffect):
    ...
    name: ClassVar[str] = "melee"

    def _outcome(self) -> Effect:
        return Destroy(self.target_id, self.cause)


@dataclass(frozen=True, slots=True)
class Fear(AttackEffect):
    ...
    name: ClassVar[str] = "fear"

    def _outcome(self) -> Effect:
        return Bow(self.target_id)
```

Ranged and Melee produce the same effect and are deliberately not the same type, because a card can
name one and not the other. `compared` defaults to `Stat.FORCE` and is what a card changes when it
weighs an attack against Chi instead.

## What an attack may be pointed at

{func}`~.attack_targets` is the predicate for the phrase every attack card prints:

```python
attack = game.attack
if attack is None or attack.current is None:
    return []
enemy = attack.defender if source.owner is attack.attacker else attack.attacker
```

The rule reaches the enemy *army* rather than the seat, so it holds only what stands at the battle
being fought. A Personality is spared by a Follower alone, and an Item or Spell attached to him does
not protect him. Outside a battle it returns nothing, which is what keeps an attack ability off the
menu when there is nothing to hit.

## Strength is a running total, and it has no floor

Every card in play is asked about every attack, and the handlers sum:

```python
def effective_strength(game: GameState, attack: AttackEffect) -> int:
    """``attack``'s strength once every card in play has had its say.

    Not floored: a card that takes more strength off an attack than it had leaves it reaching
    nothing, which is what "have -2 strength" buys. The zero floor the CR puts on a stat
    (Calculating Stats) is about stats, and an attack's strength is not one.
    """
```

Because every card is asked, a handler has to state its own reach. Being asked is not a signal that
the attack is one this card's text covers.

## Where a card plugs in

Through `ActionTiming.BATTLE` and the attack effects for an ability, and through
`@attack_strength_against` for a card that changes an attack's strength.
[Cards that act in a battle](../../contributing/battle_cards.md) is the same ground from a card
author's side.
