# Actions and legality

The turn machine opens a window. `legality.py` decides what a seat may do while it is open.

## The question a client asks

{func}`~.legal_actions` answers what a seat may take right now, and it is the only thing a client
needs. A menu is built from its output, so an action missing from it is an action no player can
reach, and one present in it must be completable.

{func}`~.is_legal` answers the same question for one action, which is what `perform` checks before
dispatching.

## Timings

{func}`~.timings_of` gives the designators an action could be taken under.
{func}`~.permitted_timings` gives the ones the current round allows, and {func}`~.permits` asks
about one. An ability is offered when those two sets intersect.

An Interrupt round lists `INTERRUPT` and nothing else, so inside one the intersection offers only
{class}`~.PlayInterrupt`, which `rules/interrupts.py` computes against the forecast of the action
held beneath the round, and a `Pass`. An Interrupt printed on a
card is not an {class}`~yasuki_core.engine.rules.abilities.model.Ability` and never reaches
{func}`~.activatable`.

## Targets

{func}`~.legal_targets` is the central narrowing. A card's `targets` function says what the card's
text allows, and this narrows that by the Rules of Location before the ability is offered.

The narrowing is central so that one implementation of the Rules of Location serves every card. A
handler carrying its own copy drifts from it silently, since nothing compares the two.

{func}`~.has_presence`, {func}`~.location_permits` and {func}`~.has_absent_ability` are the pieces
it reads, and they are what the Absent, Home and Remote designators on an ability adjust.

## Rulebook actions

Several rulebook actions carry their own legality, and `legality.py` holds the predicates rather
than the actions: {func}`~.legacy_search_pool` and {func}`~.legacy_candidates` for Legacy,
{func}`~.can_proclaim` for Proclaim, and {func}`~.recruit_cost` for what a Recruit will cost this
seat.

The Honor Requirement gate sits with the Recruit instead, in `rulebook/recruit.py`.
{func}`~.recruitable` withholds a Personality whose Honor Requirement its controller's Family Honor
does not reach, and ``_waives_honor_requirement`` answers whether anything lets the seat ignore it
anyway. Two things do, and they differ in scope. A seat that has lost Honor to anything but its own
cards ignores the requirement of its own Clan Alignment's Personalities for the rest of the game
(CR, Honor Requirement); `SeatInfo.lost_honor_from_elsewhere` records that loss, because a loss
leaves no trace on the board to read. A card in play may waive every requirement whatever clan it
names, which is the `HONOR_REQUIREMENT_WAIVERS` registry, read off the board for as long as the
card is there.

{func}`~.activatable` is the ability version: whether a card's ability can be announced at all,
cost included. {func}`~.playable` applies the same tests to a card played out of hand, which is
the one place the two part: a card's own hand ability is played, while one a keyword confers is
activated where the card sits.

Unique, Singular and a card's own "Will not join" are rules on every route into play rather than
actions of their own. {func}`~.may_join` asks all three: {func}`~.copy_may_enter` refuses a Unique
card while its seat controls a Unique card with the same title (CR, Unique), and a Singular card
while a card with the same title is in play under any seat (ShE datasheet, Singular), and a card
registered with `register_join_restriction` says which players it will not come under the control of
(CR, Join). It is asked by the Recruit and Equip offers, by the entry abilities
{func}`~.register_entry` and {func}`~.register_event_entry` build, and by the `PutIntoPlay` and
`AttachCard` effects and {func}`~.recruit_card`, so a card effect cannot bring in a duplicate, or a
card that will not join, either. A card also joins a player by changing controller, and no effect
changes a card's controller yet. The CR's Experienced exception to Unique is overlaying, which is
not modeled, so an Experienced version entering normally is refused like any other copy.

A card with Discipline is played out of its owner's Fate discard pile for one of its actions, the
action it would take from the hand, with the Discipline's Gold added to the card's Gold Cost (CR,
Discipline). {func}`~.discipline_cost` reads it off the card's own text, registered with
`register_discipline`, and off the cards granting it, as Way of the Spider gives it to Dark Virtues.
{func}`~.reach` decides how each ability or Interrupt is taken from where its card sits: activated,
played, or played under Discipline. The choice travels on the action, as the `disciplined` flag of
`PlayStrategy` and `PlayInterrupt`, and on the `Purchase`, whose `discipline` is the Gold the card's
cost carries, so nothing reads where the card is to recover it. Once the action ends the card is
removed from the game rather than discarded. One that put itself into play is recorded in
`GameState.banished_on_leaving_play` and removed from the game the next time it leaves play,
wherever it was sent.

A card's title is the one it prints, without its subtitle (CR, Card Subtitles), so Akodo Kano,
Clan Champion and Akodo Kano, the Lion's Fang share one. {func}`~.titles` also counts the title an
"Experienced [#] Name" keyword names, so The Sorrow, which prints "Experienced Bayushi Tenzan", is a
copy of Bayushi Tenzan for Unique and Singular.

## Where a card plugs in

A card does not register legality. It names a timing and returns a target list, and everything
here reads those. [Abilities and costs](abilities-and-costs.md) covers what a card declares, and
[The turn machine](turn-flow.md) covers when each window opens.
