function makeClassList() {
  const set = new Set();
  return {
    add(c) { set.add(c); },
    remove(c) { set.delete(c); },
    toggle(c, force) {
      if (force === undefined) { set.has(c) ? set.delete(c) : set.add(c); }
      else if (force) { set.add(c); }
      else { set.delete(c); }
    },
    contains(c) { return set.has(c); },
    get value() { return [...set].join(' '); },
  };
}

function makeElement(tag) {
  const children = [];
  const listeners = {};
  const el = {
    tagName: tag.toUpperCase(),
    children,
    childNodes: children,
    className: '',
    id: '',
    textContent: '',
    innerHTML: '',
    disabled: false,
    dataset: {},
    style: {},
    classList: makeClassList(),
    appendChild(child) { children.push(child); return child; },
    replaceChildren(...nodes) { children.length = 0; children.push(...nodes); },
    addEventListener(evt, fn) {
      if (!listeners[evt]) listeners[evt] = [];
      listeners[evt].push(fn);
    },
    _listeners: listeners,
    querySelector(sel) { return null; },
    querySelectorAll(sel) { return []; },
    scrollIntoView() {},
    getBoundingClientRect() { return { width: 200, height: 200, top: 0, left: 0 }; },
    get value() { return this._value || ''; },
    set value(v) { this._value = v; },
  };
  return el;
}

const _elements = {};

globalThis.document = {
  getElementById(id) {
    if (!_elements[id]) _elements[id] = makeElement('div');
    return _elements[id];
  },
  createElement(tag) { return makeElement(tag); },
  querySelectorAll() { return []; },
  addEventListener() {},
  get activeElement() { return null; },
  get body() { return makeElement('body'); },
};

globalThis.IntersectionObserver = class {
  constructor() {}
  observe() {}
  disconnect() {}
};

export function resetDOM() {
  for (const key of Object.keys(_elements)) delete _elements[key];
}
