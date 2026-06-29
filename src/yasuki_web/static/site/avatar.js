// The player's avatar, shared by the nav widget and the in-game seat panels so one identity drives
// both: a circle showing up to two initials of the display name.

export function initials(name) {
  return (
    (name ?? '')
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0].toUpperCase())
      .join('') || '?'
  );
}
