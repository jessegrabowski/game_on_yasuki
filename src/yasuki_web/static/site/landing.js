import { wireSuggestion } from './suggestions.js';

const el = document.getElementById('suggestion');
const form = document.querySelector('.search-form');
const input = form?.querySelector('input[name="q"]');
if (el && form && input) wireSuggestion(el, input, form);
