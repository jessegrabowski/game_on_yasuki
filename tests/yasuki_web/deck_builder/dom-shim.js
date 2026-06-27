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
    parentNode: null,
    className: '',
    id: '',
    _textContent: '',
    // Mirror the DOM: reading textContent concatenates descendant text; setting it replaces children.
    get textContent() {
      return children.length ? children.map((c) => c.textContent ?? '').join('') : this._textContent;
    },
    set textContent(value) {
      this._textContent = value;
      children.length = 0;
    },
    innerHTML: '',
    disabled: false,
    dataset: {},
    style: {},
    classList: makeClassList(),
    appendChild(child) { child.parentNode = el; children.push(child); return child; },
    append(...nodes) { for (const child of nodes) { child.parentNode = el; children.push(child); } },
    insertBefore(child, ref) {
      const from = child.parentNode?.children;
      if (from) { const i = from.indexOf(child); if (i >= 0) from.splice(i, 1); }
      child.parentNode = el;
      const at = ref ? children.indexOf(ref) : children.length;
      children.splice(at < 0 ? children.length : at, 0, child);
      return child;
    },
    replaceChildren(...nodes) { children.length = 0; children.push(...nodes); },
    remove() {
      const siblings = el.parentNode?.children;
      if (siblings) {
        const i = siblings.indexOf(el);
        if (i >= 0) siblings.splice(i, 1);
      }
      el.parentNode = null;
    },
    addEventListener(evt, fn) {
      if (!listeners[evt]) listeners[evt] = [];
      listeners[evt].push(fn);
    },
    _listeners: listeners,
    _emit(evt, event) { (listeners[evt] || []).forEach((fn) => fn(event)); },
    setPointerCapture() {},
    removeAttribute(name) { delete el[name]; },
    querySelector(sel) { return null; },
    querySelectorAll(sel) { return []; },
    scrollIntoView() {},
    getBoundingClientRect() {
      return { width: 200, height: 200, top: 0, left: 0, right: 200, bottom: 200 };
    },
    offsetWidth: 200,
    offsetHeight: 200,
    get value() { return this._value || ''; },
    set value(v) { this._value = v; },
  };
  return el;
}

const _elements = {};
const _docListeners = {};

globalThis.document = {
  getElementById(id) {
    if (!_elements[id]) _elements[id] = makeElement('div');
    return _elements[id];
  },
  querySelector(sel) {
    if (!_elements[sel]) _elements[sel] = makeElement('div');
    return _elements[sel];
  },
  createElement(tag) { return makeElement(tag); },
  querySelectorAll() { return []; },
  addEventListener(evt, fn) { (_docListeners[evt] ||= []).push(fn); },
  removeEventListener(evt, fn) {
    _docListeners[evt] = (_docListeners[evt] || []).filter((f) => f !== fn);
  },
  _emit(evt, event) { (_docListeners[evt] || []).forEach((fn) => fn(event)); },
  get activeElement() { return null; },
  get body() { return makeElement('body'); },
};

globalThis.CSS ??= { escape: (s) => String(s) };

globalThis.IntersectionObserver = class {
  constructor() {}
  observe() {}
  disconnect() {}
};

export function resetDOM() {
  for (const key of Object.keys(_elements)) delete _elements[key];
  for (const evt of Object.keys(_docListeners)) delete _docListeners[evt];
}
