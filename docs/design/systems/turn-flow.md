# The turn machine

A designator on a card names a window. The turn machine opens them.

## Phases, rounds and segments

A turn runs three phases: `ACTION`, `BATTLE`, `DYNASTY`. Each opens an Action Round, which is
where players take actions, and closes when every seat passes consecutively.

`RoundKind` says what kind of round is open. `PHASE` is the ordinary one a phase opens. `RESPONSE`
is the window that opens over an action just taken, and over a battle just resolved.
`BATTLE_SEGMENT` is one step of a battle. `DUEL_WINDOW` is the window a duel opens at each of its
own time points. `STEP_ROUNDS` names the three that are a step inside an action still resolving: an
action taken in one answers the action the step was opened over, never becoming the action the table
is resolving, and none of them opens a step of its own.

Closing the Combat Segment opens the Resolution Segment and announces `BattleResolving` before
either army's Force is read. {class}`~.ResolveBattle` waits beneath the announcement, so a trait
reading "before battle resolution" resolves first and resolution reads the board it leaves.

A battle's resolution opens a Response Step of its own. {class}`~.AnnounceResolution` records the
outcome and announces `BattleResolved` once the resolution's own cascade has settled, including any
question a trigger in it asks, so the outcome sees everything the resolution did.
{class}`~.AfterResolution` is the work item that opens the step once `BattleResolved` has been
announced, and the item waits beneath the step the way a held action waits beneath its Interrupt
round. When the step closes, the item runs After Resolution, bows and sends home the survivors,
and announces `BattleEnded` at the end of the battle before moving the fight on. `BattleEnded`
carries the seats that took a printed action while the battle was fought, the step included. The battle
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
policy owns rather than a rule of the round. A step is the exception, because each one opened only
because some seat held an Interrupt or a Response, so a seat holding none is skipped there too.

An {class}`~.AdditionalAction` keeps the opportunity with its seat once the action now resolving is
done, and the pass count starts again (CR, Additional Action). One limited to some follow-ups, as
"take an additional Battle from your target Ring" is, sets the round's `follow_ups`, and
{func}`~.legal_actions` then offers only those and a pass. The limit is dropped as the opportunity
passes on.

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

A duel opens a third kind of window. Every time point its procedure announces is a point a card may
react at, so each of the duel's steps is queued behind an {class}`~.OpenDuelWindow`, and
{func}`~.open_duel_window` opens a round of kind `DUEL_WINDOW` there for a seat that holds a
Response. The duel's remaining steps wait beneath it, which is how Concede Defeat's "after a strike
is declared, but before focused cards are revealed" has a place to be played from.

`ROUNDS_OVER_HELD_WORK` names the two kinds whose closing resumes the work held beneath them, and
{func}`~.close_step_over_held_work` closes both: the Interrupt step holds the
action it was opened over, and a duel window holds the duel's remaining steps. Neither action has
finished resolving, so each hands the opportunity on through {func}`~.yield_after_action` from the
round it suspended. That round is read before the held work runs, because a duel step opens the next
window as it goes, and handing on from the window just opened would take the opportunity straight
back off the seat it named.

A duel that ends while one of its windows is open drains that window: the duel has no step left for
a Response to answer, so no seat holds anything the window exists to offer and it closes on the
first poll. That is the one case where a seat holding a Response is not asked.

## What a designator means

`ActionTiming` names the round a card's ability may be taken in, and who acts first.

- `OPEN` and `LIMITED` belong to the Action Phase, `LIMITED` restricted to the active player
- `DYNASTY` belongs to the Dynasty phase, active player only
- `ATTACK` belongs to the Attack Phase's Declaration Segment
- `ENGAGE` and `BATTLE` belong to a battle's Engage and Combat Segments, Defender acting first
- `RESPONSE` belongs to the Response Step over another action, and to a duel window
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
