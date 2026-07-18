// Hypergeometric P(at least one copy) when revealing `draws` cards off the top of a `population`-card
// deck that holds `copies` of the wanted card, without replacement. Computed through the complement —
// a running product of the per-draw "miss" chance — so it stays exact and overflow-free for
// deck-sized inputs instead of building large binomials. Returns NaN for nonsensical inputs (empty
// deck, no draws, more copies than cards) so callers can render a blank rather than a bogus number.
export function chanceOfAtLeastOne(population, copies, draws) {
  if (![population, copies, draws].every(Number.isFinite)) return NaN;
  if (population <= 0 || copies < 0 || draws <= 0 || copies > population) return NaN;
  if (copies === 0) return 0;

  const picks = Math.min(draws, population);
  let chanceOfNone = 1;
  for (let i = 0; i < picks; i++) {
    const nonCopiesLeft = population - copies - i;
    if (nonCopiesLeft <= 0) return 1; // no misses remain to draw → a copy is guaranteed
    chanceOfNone *= nonCopiesLeft / (population - i);
  }
  return 1 - chanceOfNone;
}
