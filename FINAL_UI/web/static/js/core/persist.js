/* McA.persist: the only module that touches localStorage. Every read goes
   through get(key, fallback) with try/catch and a schema check; invalid or
   unreadable values fall back. No secrets and no file contents are stored.
   Values are stored as JSON text. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(root);
  else (root.McA = root.McA || {}).persist = factory(root);
})(typeof self !== 'undefined' ? self : (typeof globalThis !== 'undefined' ? globalThis : this), function (root) {
  'use strict';

  var KEYS = {
    session: 'mca.session',
    activeRun: 'mca.activeRun',
    batch: 'mca.batch',
    selected: 'mca.selected',
    sidebar: 'mca.ui.sidebar',
    inspector: 'mca.ui.inspector',
    drawer: 'mca.ui.drawer',
    split: 'mca.ui.split',
    results: 'mca.ui.results'
  };
  var CORR_PREFIX = 'mca.corr.';
  var UI_PREFIX = 'mca.ui.';

  var storage = null;           // injected in tests, else window.localStorage
  var injected = false;
  function store() {
    if (injected) return storage;
    try { return root.localStorage || null; } catch (e) { return null; }   // access can throw
  }
  /** Tests: pass an object with getItem/setItem/removeItem/key/length, or null. */
  function useStorage(s) { storage = s; injected = true; }

  function isStr(v) { return typeof v === 'string' && v.length > 0; }
  function isBool(v) { return typeof v === 'boolean'; }
  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  function isObj(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }

  var SCHEMA = {};
  SCHEMA[KEYS.session] = isStr;
  SCHEMA[KEYS.activeRun] = function (v) {
    return isObj(v) && isStr(v.id) && (v.kind === 'part' || v.kind === 'demo') && isNum(v.startedAt) &&
      (v.kind === 'demo' || (isStr(v.session) && isStr(v.part)));
  };
  SCHEMA[KEYS.batch] = function (v) {
    return isObj(v) && Array.isArray(v.queue) && isNum(v.index) && isObj(v.results);
  };
  SCHEMA[KEYS.selected] = function (v) { return isObj(v) && isStr(v.session) && isStr(v.part); };
  SCHEMA[KEYS.sidebar] = function (v) { return v === 'expanded' || v === 'collapsed'; };
  SCHEMA[KEYS.inspector] = function (v) {
    return isObj(v) && isBool(v.collapsed) && isObj(v.open) &&
      ['setup', 'actions', 'corrections', 'export'].every(function (k) { return isBool(v.open[k]); });
  };
  SCHEMA[KEYS.drawer] = function (v) {
    return isObj(v) && isBool(v.open) && isNum(v.height) && v.height >= 120 && v.height <= 4000 && typeof v.section === 'string';
  };
  SCHEMA[KEYS.split] = function (v) { return isNum(v) && v >= 0.2 && v <= 0.8; };
  SCHEMA[KEYS.results] = isStr;

  function get(key, fallback) {
    var s = store();
    if (!s) return fallback;
    var raw;
    try { raw = s.getItem(key); } catch (e) { return fallback; }
    if (raw === null || raw === undefined) return fallback;
    var v;
    try { v = JSON.parse(raw); } catch (e) { return fallback; }
    var check = SCHEMA[key] || (key.indexOf(CORR_PREFIX) === 0 ? function (x) { return typeof x === 'string'; } : null);
    if (check && !check(v)) return fallback;
    return v;
  }
  /** Returns true when written. Quota or disabled storage returns false, never throws. */
  function set(key, value) {
    var s = store();
    if (!s) return false;
    try { s.setItem(key, JSON.stringify(value)); return true; } catch (e) { return false; }
  }
  function remove(key) {
    var s = store();
    if (!s) return;
    try { s.removeItem(key); } catch (e) { /* ignore */ }
  }
  function allKeys() {
    var s = store(), out = [];
    if (!s) return out;
    try { for (var i = 0; i < s.length; i++) out.push(s.key(i)); } catch (e) { /* ignore */ }
    return out;
  }

  /** Per-part correction draft. */
  function corrKey(session, part) { return CORR_PREFIX + session + '.' + part; }
  var corr = {
    get: function (session, part) { return get(corrKey(session, part), ''); },
    set: function (session, part, text) {
      if (!text) remove(corrKey(session, part)); else set(corrKey(session, part), String(text));
    },
    clear: function (session, part) { remove(corrKey(session, part)); }
  };

  /** Defaults for the persisted slice of state.ui (fresh objects each call). */
  function uiDefaults() {
    return {
      sidebarCollapsed: false,
      inspectorCollapsed: false,
      inspectorOpen: { setup: true, actions: true, corrections: true, export: true },
      drawerOpen: false,
      drawerHeight: 320,
      drawerSection: 'overview',
      splitRatio: 0.5,
      resultsSection: 'overview'
    };
  }
  function loadUi() {
    var d = uiDefaults();
    d.sidebarCollapsed = get(KEYS.sidebar, 'expanded') === 'collapsed';
    var ins = get(KEYS.inspector, null);
    if (ins) { d.inspectorCollapsed = ins.collapsed; d.inspectorOpen = ins.open; }
    var dr = get(KEYS.drawer, null);
    if (dr) { d.drawerOpen = dr.open; d.drawerHeight = dr.height; d.drawerSection = dr.section; }
    d.splitRatio = get(KEYS.split, d.splitRatio);
    d.resultsSection = get(KEYS.results, d.resultsSection);
    return d;
  }
  /** Write the persisted slice of a ui object. Unknown fields are ignored. */
  function saveUi(ui) {
    if (!ui) return;
    set(KEYS.sidebar, ui.sidebarCollapsed ? 'collapsed' : 'expanded');
    set(KEYS.inspector, { collapsed: !!ui.inspectorCollapsed, open: ui.inspectorOpen });
    set(KEYS.drawer, { open: !!ui.drawerOpen, height: ui.drawerHeight, section: ui.drawerSection || '' });
    set(KEYS.split, ui.splitRatio);
    set(KEYS.results, ui.resultsSection);
  }
  /** Settings "Reset layout": clears every mca.ui.* key. */
  function resetUi() {
    allKeys().filter(function (k) { return k && k.indexOf(UI_PREFIX) === 0; }).forEach(remove);
  }

  return { KEYS: KEYS, get: get, set: set, remove: remove, useStorage: useStorage,
           corr: corr, uiDefaults: uiDefaults, loadUi: loadUi, saveUi: saveUi, resetUi: resetUi };
});
