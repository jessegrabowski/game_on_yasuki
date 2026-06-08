// Example searches surfaced one-at-a-time as a clickable "try this". Each is valid against the
// query syntax and mixes a different slice of it — clans, types, numeric stats, keywords, format and
// set names/codes/ranges, text, OR, and negation.
export const SEARCH_SUGGESTIONS = [
  'clan:Crab type:personality force>=4',
  'is:shugenja is:shadowlands',
  'format:diamond is:cavalry',
  'c:Dragon t:personality f>3 chi>3',
  'set:GE type:holding',
  'gold<=2 type:holding',
  'clan:Crane OR clan:Phoenix',
  'is:unique force>=5',
  'format>celestial type:personality',
  'text:honor type:event',
  '-clan:Crab is:shugenja',
  'c:Scorpion t:personality f>=3 format:lotus',
  'set>=DE set<=CoB',
  'province>=4',
  'ph>=3 clan:Lion',
  'is:experienced clan:Unicorn',
  'rarity:rare is:unique',
  'type:stronghold clan:Crab',
  'is:naval clan:Mantis',
  'o:cavalry type:follower',
  'format:gold OR format:diamond',
  'chi>=4 type:personality',
  'gold>=6 type:personality',
  'is:samurai clan:Lion format>samurai',
  'set:"Gold Edition" is:unique',
  'clan:Phoenix is:shugenja force<=2',
  'is:courtier clan:Crane',
  'force<=1 type:personality is:shugenja',
  'format>=emperor is:cavalry',
  'type:region',
  'text:destroy type:strategy',
  'clan:Spider is:shadowlands',
  'honor_requirement>=4 type:personality',
  't:item gold<=3',
  'is:magistrate clan:Scorpion',
  'c:Naga t:personality force>=3',
  'format:celestial type:event',
  'format>=onyx',
  'is:tactician clan:Dragon',
  'gold:0 type:strategy',
  'clan:Scorpion is:shadowlands',
  'type:celestial',
  'is:monk clan:Dragon',
  'force>=5 chi>=5',
  'format<gold type:personality',
  'set:KYD',
  'ph>=4 type:personality clan:Crane',
  'is:duelist force>=4',
  'o:gold type:holding',
  'format>=lotus is:shugenja chi>=3',
];

export function randomSuggestion() {
  return SEARCH_SUGGESTIONS[Math.floor(Math.random() * SEARCH_SUGGESTIONS.length)];
}

// Show a random suggestion in `el` and, on click or Enter, drop it into `input` and submit `form`.
export function wireSuggestion(el, input, form) {
  const suggestion = randomSuggestion();
  el.textContent = suggestion;
  const go = () => {
    input.value = suggestion;
    form.requestSubmit ? form.requestSubmit() : form.submit();
  };
  el.addEventListener('click', go);
  el.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      go();
    }
  });
}
