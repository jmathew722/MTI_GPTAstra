'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const U = require('./_helpers').core('util.js');

test('esc neutralizes script tags and attribute breaks', () => {
  assert.equal(U.esc('<script>alert(1)</script>'), '&lt;script&gt;alert(1)&lt;/script&gt;');
  assert.equal(U.esc('" onmouseover="x"'), '&quot; onmouseover=&quot;x&quot;');
  assert.equal(U.esc("' onclick='y'"), '&#39; onclick=&#39;y&#39;');
  assert.equal(U.esc('a & b'), 'a &amp; b');
  assert.equal(U.esc('&lt;'), '&amp;lt;');           // no double-decoding
  assert.equal(U.esc(null), ''); assert.equal(U.esc(undefined), ''); assert.equal(U.esc(0), '0');
  assert.ok(!/[<>"']/.test(U.esc('<img src=x onerror="a(\'b\')">')));
});

test('whitelist guards class names', () => {
  assert.equal(U.whitelist('critical', ['critical', 'high'], 'x'), 'critical');
  assert.equal(U.whitelist('bad" onclick="', ['critical'], 'low'), 'low');
  assert.equal(U.whitelist('bad', ['a']), '');
});

test('fmtBytes', () => {
  assert.equal(U.fmtBytes(0), '0 B'); assert.equal(U.fmtBytes(512), '512 B'); assert.equal(U.fmtBytes(1023), '1023 B');
  assert.equal(U.fmtBytes(1024), '1.0 KB'); assert.equal(U.fmtBytes(1536), '1.5 KB');
  assert.equal(U.fmtBytes(2 * 1024 * 1024), '2.0 MB'); assert.equal(U.fmtBytes(5 * 1024 ** 3), '5.00 GB');
  assert.equal(U.fmtBytes(-1), ''); assert.equal(U.fmtBytes(NaN), ''); assert.equal(U.fmtBytes('x'), '');
});

test('fmtElapsed takes milliseconds', () => {
  assert.equal(U.fmtElapsed(0), '0:00'); assert.equal(U.fmtElapsed(999), '0:00'); assert.equal(U.fmtElapsed(5000), '0:05');
  assert.equal(U.fmtElapsed(65000), '1:05'); assert.equal(U.fmtElapsed(3599000), '59:59');
  assert.equal(U.fmtElapsed(3600000), '1:00:00'); assert.equal(U.fmtElapsed(3725000), '1:02:05');
  assert.equal(U.fmtElapsed(-5), '0:00'); assert.equal(U.fmtElapsed(null), '0:00');
});

test('debounce coalesces calls, supports cancel and flush', async () => {
  let calls = [];
  const d = U.debounce((x) => calls.push(x), 10);
  d(1); d(2); d(3);
  await new Promise((r) => setTimeout(r, 30));
  assert.deepEqual(calls, [3]);
  d(4); d.cancel();
  await new Promise((r) => setTimeout(r, 30));
  assert.deepEqual(calls, [3]);
  d(5); d.flush();
  assert.deepEqual(calls, [3, 5]);
});

test('copyText resolves false when neither the clipboard API nor a document exists (node)', async () => {
  assert.equal(await U.copyText('x'), false);
});

function fakeDoc() {
  const mk = (tag) => ({ tag, children: [], attrs: {}, dataset: {}, listeners: {}, props: {}, textContent: '', className: '',
    style: { setProperty(k, v) { this[k] = v; } },
    setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(t, f) { this.listeners[t] = f; },
    appendChild(c) { this.children.push(c); return c; } });
  return { createElement: mk, createTextNode: (text) => ({ text }), body: mk('body') };
}

test('el builds nodes: text via textContent, strings as text nodes, listeners, booleans', () => {
  global.document = fakeDoc();
  try {
    let clicked = 0;
    const n = U.el('button', { class: 'btn', text: '<b>x</b>', disabled: true, hidden: false, 'aria-label': 'Go', dataset: { k: 'v' },
      style: { '--x': '1' }, onClick: () => { clicked++; } }, 'plain <i>', [null, U.el('span')], false);
    assert.equal(n.className, 'btn'); assert.equal(n.textContent, '<b>x</b>');
    assert.equal(n.attrs.disabled, ''); assert.equal('hidden' in n.attrs, false); assert.equal(n.attrs['aria-label'], 'Go');
    assert.equal(n.dataset.k, 'v');
    n.listeners.click(); assert.equal(clicked, 1);
    assert.equal(n.children.length, 2);
    assert.deepEqual(n.children[0], { text: 'plain <i>' });          // a text node, not markup
    assert.equal(n.children[1].tag, 'span');
  } finally { delete global.document; }
});

test('downloadURL clicks a hidden anchor and removes it', () => {
  const doc = fakeDoc(); let clicked = false, removed = false;
  doc.createElement = (tag) => ({ tag, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, click() { clicked = true; } });
  doc.body.appendChild = (c) => c; doc.body.removeChild = () => { removed = true; };
  global.document = doc;
  try { U.downloadURL('/api/x', 'f.stl'); } finally { delete global.document; }
  assert.ok(clicked && removed);
});

test('copyText uses the async clipboard when present', async () => {
  let got = null;
  Object.defineProperty(global, 'navigator', { value: { clipboard: { writeText: async (t) => { got = t; } } }, configurable: true });
  try { assert.equal(await U.copyText('abc'), true); assert.equal(got, 'abc'); }
  finally { delete global.navigator; }
});
