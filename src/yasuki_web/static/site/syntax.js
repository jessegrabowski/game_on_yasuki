// Point each example box at the card search with its query properly encoded, so clicking (or
// middle-clicking / opening in a new tab) runs it. The query text lives in the element, so the
// markup stays readable and there is no chance of a hand-encoded href drifting from what it shows.
for (const el of document.querySelectorAll('.example')) {
  el.href = '/card-search?q=' + encodeURIComponent(el.textContent.trim());
}
