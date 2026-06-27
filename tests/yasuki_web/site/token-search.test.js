import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from '../deck_builder/dom-shim.js';
import { openTokenSearch, tokenSide } from '../../../src/yasuki_web/static/site/token-search.js';

beforeEach(() => {
  resetDOM();
});

const flush = () => new Promise((resolve) => setTimeout(resolve));
const cardRow = (id, name, decks) => ({ card_id: id, name, image_path: `sets/${id}.jpg`, decks });

describe('tokenSide', () => {
  it('maps a card to its spawn side from its decks, defaulting to a stronghold', () => {
    assert.equal(tokenSide({ decks: ['Fate'] }), 'FATE');
    assert.equal(tokenSide({ decks: ['Dynasty'] }), 'DYNASTY');
    assert.equal(tokenSide({ decks: ['Pre-Game'] }), 'STRONGHOLD');
    assert.equal(tokenSide({}), 'STRONGHOLD');
  });
});

describe('openTokenSearch', () => {
  const open = (overrides = {}) => {
    const sent = [];
    const queries = [];
    const handle = openTokenSearch({
      imgBase: '/images',
      position: { x: 12, y: 34 },
      send: (frame) => sent.push(frame),
      searchPage: async (query, offset) => {
        queries.push({ query, offset });
        return { cards: [cardRow('c1', 'Hida Kisada', ['Dynasty']), cardRow('c2', 'Ambush', ['Fate'])], hasMore: false };
      },
      ...overrides,
    });
    return { handle, sent, queries };
  };
  const modalOf = (overlay) => overlay.children[0]; // [header, form, body]
  const formOf = (overlay) => modalOf(overlay).children[1];
  const inputOf = (overlay) => formOf(overlay).children[0];
  const bodyOf = (overlay) => modalOf(overlay).children[2]; // [list, preview]
  const listOf = (overlay) => bodyOf(overlay).children[0];
  const previewOf = (overlay) => bodyOf(overlay).children[1]; // [img, createBtn]
  const previewImgOf = (overlay) => previewOf(overlay).children[0];
  const createBtnOf = (overlay) => previewOf(overlay).children[1];

  // First, before any test edits the remembered query: a fresh dialog seeds the box with t:proxy.
  it('starts with t:proxy in the search box by default', () => {
    assert.equal(inputOf(open().handle.el).value, 't:proxy');
  });

  it('searches with include:all and auto-previews the first result', async () => {
    const { handle, queries } = open();
    inputOf(handle.el).value = 't:proxy';
    formOf(handle.el)._emit('submit', { preventDefault() {} });
    await flush();

    assert.ok(queries.at(-1).query.includes('include:all'), 'token/proxy cards are surfaced');
    assert.match(previewImgOf(handle.el).src, /sets\/c1\.jpg$/, 'the first card is previewed');
    assert.equal(createBtnOf(handle.el).disabled, false, 'Create is enabled once a card is previewed');
  });

  it('spawns the previewed card via the Create button', async () => {
    const { handle, sent } = open();
    formOf(handle.el)._emit('submit', { preventDefault() {} });
    await flush();

    listOf(handle.el).children[0]._emit('click', {}); // preview Hida Kisada, a dynasty card
    createBtnOf(handle.el)._emit('click', {});
    assert.deepEqual(sent, [
      {
        type: 'SPAWN',
        spawn: { name: 'Hida Kisada', img: 'sets/c1.jpg', side: 'DYNASTY', x: 12, y: 34 },
      },
    ]);
  });

  it('spawns a card directly on double-click', async () => {
    const { handle, sent } = open();
    formOf(handle.el)._emit('submit', { preventDefault() {} });
    await flush();

    listOf(handle.el).children[1]._emit('dblclick', {}); // Ambush, a fate card
    assert.deepEqual(sent, [
      { type: 'SPAWN', spawn: { name: 'Ambush', img: 'sets/c2.jpg', side: 'FATE', x: 12, y: 34 } },
    ]);
  });

  it('remembers the last query and reruns it on reopen', async () => {
    const first = open();
    inputOf(first.handle.el).value = 'kisada';
    formOf(first.handle.el)._emit('submit', { preventDefault() {} });

    const second = open();
    assert.equal(inputOf(second.handle.el).value, 'kisada', 'the input is pre-filled');
    await flush();
    assert.ok(second.queries.some((q) => q.query.includes('kisada')), 'and the search re-runs');
  });

  it('pages in more results when the list scrolls to the bottom', async () => {
    const pages = {
      0: { cards: [cardRow('a', 'A', ['Fate']), cardRow('b', 'B', ['Fate'])], hasMore: true },
      2: { cards: [cardRow('c', 'C', ['Fate'])], hasMore: false },
    };
    const { handle } = open({ searchPage: async (_query, offset) => pages[offset] });
    inputOf(handle.el).value = 'x';
    formOf(handle.el)._emit('submit', { preventDefault() {} });
    await flush();
    assert.equal(listOf(handle.el).children.length, 2, 'the first page');

    const list = listOf(handle.el);
    Object.assign(list, { scrollTop: 1000, clientHeight: 100, scrollHeight: 1050 });
    list._emit('scroll', {});
    await flush();
    assert.equal(listOf(handle.el).children.length, 3, 'the next page appended on scroll');
  });
});
