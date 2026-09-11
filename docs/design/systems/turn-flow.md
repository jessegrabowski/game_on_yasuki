# The turn machine

A designator on a card names a window. The turn machine is what opens them.

## Phases, rounds and segments

A turn runs three phases: `ACTION`, `BATTLE`, `DYNASTY`. Each opens an Action Round, which is
where players take actions, and closes when every seat passes consecutively.

`RoundKind` says what kind of round is open. `PHASE` is the ordinary one a phase opens. `RESPONSE`
is the window that opens over an action just taken. `BATTLE_SEGMENT` is one step of a battle.

Two segment vocabularies sit below the phases. `Segment` names the Attack Phase's steps,
`DECLARATION`, `MANEUVERS` and `FIGHT`. `BattleSegment` names one battle's, `ENGAGE`, `COMBAT`,
`RESOLUTION` and `AFTER_RESOLUTION`. Which segments an arc uses, and in what order, is arc
configuration and not a property of the enum, so `Ruleset` carries the order.

## Priority

{func}`~.open_round` gives the active seat the first opportunity. {func}`~.yield_priority` hands it
to the next seat, and closes the round once every seat has passed consecutively. The active
player finishing is not what ends a round.

{func}`~.open_response_window` opens the Response Step over the round an action was taken in, and
reports whether it opened at all.

## What a designator means

`ActionTiming` names the round a card's ability may be taken in, and who acts first.

- `OPEN` and `LIMITED` belong to the Action Phase, `LIMITED` restricted to the active player
- `DYNASTY` belongs to the Dynasty phase, active player only
- `ATTACK` belongs to the Attack Phase's Declaration Segment
- `ENGAGE` and `BATTLE` belong to a battle's Engage and Combat Segments, Defender acting first
- `RESPONSE` belongs to the Response Step over another action
- `INTERRUPT` belongs to nothing

`INTERRUPT` is declared and no round grants it, so an ability carrying it is never offered. The
limits list in [Adding a Card](../../contributing/adding_a_card.md) is where that claim lives, and
it is the one to update if a round ever grants it.

## Where a card plugs in

Nowhere directly. A card names a timing and the machine decides when that timing is live. The
decision of whether a named window is open right now belongs to
[Actions and legality](actions-and-legality.md).
