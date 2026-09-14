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

That intersection is why `INTERRUPT` never fires. No round lists it, so the set is always empty for
an ability carrying it.

## Targets

{func}`~.legal_targets` is the central narrowing. A card's `targets` function says what the card's
text allows, and this narrows that by the Rules of Location before the ability is offered.

The narrowing is central so that one implementation of the Rules of Location serves every card. A
handler carrying its own copy drifts from it silently, since nothing compares the two.

{func}`~.has_presence`, {func}`~.location_permits` and {func}`~.has_absent_ability` are the pieces
it reads, and they are what the Absent, Home and Remote designators on an ability adjust.

## Rulebook actions

Several rulebook actions carry their own legality, and `legality.py` holds the predicates rather
than the actions: {func}`~.is_kharmic_card` and {func}`~.kharmic_in_hand` for Kharmic,
{func}`~.cycle_candidates` for Cycle, {func}`~.legacy_search_pool` and
{func}`~.legacy_candidates` for Legacy, {func}`~.can_proclaim` for Proclaim, and
{func}`~.recruit_cost` for what a Recruit will cost this seat.

{func}`~.activatable` is the ability version: whether a card's ability can be announced at all,
cost included.

## Where a card plugs in

A card does not register legality. It names a timing and returns a target list, and everything
here reads those. [Abilities and costs](abilities-and-costs.md) covers what a card declares, and
[The turn machine](turn-flow.md) covers when each window opens.
