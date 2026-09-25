# The turn machine

A designator on a card names a window. The turn machine opens them.

## Phases, rounds and segments

A turn runs three phases: `ACTION`, `BATTLE`, `DYNASTY`. Each opens an Action Round, which is
where players take actions, and closes when every seat passes consecutively.

`RoundKind` says what kind of round is open. `PHASE` is the ordinary one a phase opens. `RESPONSE`
is the window that opens over an action just taken, and over a battle just resolved.
`BATTLE_SEGMENT` is one step of a battle.

A battle's resolution opens a Response Step of its own. {class}`~.AnnounceResolution` records the
outcome and announces `BattleResolved` once the resolution's own cascade has settled, including any
question a trigger in it asks, so the outcome sees everything the resolution did.
{class}`~.AfterResolution` is the work item that opens the step once `BattleResolved` has been
announced, and the item waits beneath the step the way a held action waits beneath its Interrupt
round. When the step closes, the item runs After Resolution, bows and sends home the survivors, and
moves the fight on. The battle
segment reads `RESOLUTION` for as long as the step is open, which is what a card reading "after a
battle's Resolution Segment" checks.

Two segment vocabularies sit below the phases. `Segment` names the Attack Phase's steps,
`DECLARATION`, `MANEUVERS` and `FIGHT`. `BattleSegment` names one battle's, `ENGAGE`, `COMBAT`,
`RESOLUTION` and `AFTER_RESOLUTION`. Which segments an arc uses, and in what order, is arc
configuration and not a property of the enum, so `Ruleset` carries the order.

## Priority

{func}`~.open_round` gives the active seat the first opportunity. {func}`~.yield_priority` hands it
to the next seat, and closes the round once every seat has passed consecutively. The active
player finishing is not what ends a round.

A seat the round permits nothing is skipped and counts as having passed. Permitted-but-idle is not:
whether to decline a window is the seat's own call, and auto-passing on its behalf is a strategy a
policy owns rather than a rule of the round. The two steps are the exception, because each opened
only because some seat held an Interrupt or a Response, so a seat holding none is skipped there too.

The Action Sequence's two windows are rounds over the round the action was taken in.
{func}`~yasuki_core.engine.rules.interrupts.open_interrupt_window` opens the Interrupt step (D)
once the action's targets are chosen and its effects held, and {func}`~.open_response_window`
opens the Response Step once they have resolved (between E and F). Each reports whether it opened
at all, since a step nobody could act in is a pass nobody needs to be asked for, and each opens on
the first seat in turn order holding something to take rather than on the active seat.

A step closes back to the suspended round once no seat holds anything to take in it: consecutive
passes where every seat holds one, and no pass at all where the only holder takes what it held.
Nobody is asked to pass a step with nothing left in it. {func}`~.close_response_window` runs
whatever waited beneath the step before handing the opportunity on, since the step closes on a
Response taken as readily as on a pass, and a battle's After Resolution waits there.

## What a designator means

`ActionTiming` names the round a card's ability may be taken in, and who acts first.

- `OPEN` and `LIMITED` belong to the Action Phase, `LIMITED` restricted to the active player
- `DYNASTY` belongs to the Dynasty phase, active player only
- `ATTACK` belongs to the Attack Phase's Declaration Segment
- `ENGAGE` and `BATTLE` belong to a battle's Engage and Combat Segments, Defender acting first
- `RESPONSE` belongs to the Response Step over another action
- `INTERRUPT` belongs to the Interrupt step, a round of its own

The Interrupt step is an `ActionRound` of kind `INTERRUPT`, pushed over the round an action was
taken in once the action's effects are held and some seat holds an Interrupt to take, the way the
Response Step is pushed after the action resolves. It permits nothing but `INTERRUPT`, opens on the
first seat holding one, and closes once no seat holds one, at which point the held action resolves:
see `rules/interrupts.py` and [Abilities and costs](abilities-and-costs.md).

## Where a card plugs in

Nowhere directly. A card names a timing and the machine decides when that timing is live. The
decision of whether a named window is open right now belongs to
[Actions and legality](actions-and-legality.md).
