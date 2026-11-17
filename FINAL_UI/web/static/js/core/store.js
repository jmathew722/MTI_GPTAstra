/* McA.store: single state store. get / set / update / subscribe / dispatch.
   Notifications are batched with a microtask. Features mutate state only through
   dispatch(type, payload); modules add reducers with store.register(type, fn).
   A reducer is fn(state, payload, store) and returns a top-level PATCH object
   (merged shallowly into state) or null/undefined for "no change". */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(root);
  else (root.McA = root.McA || {}).store = factory(root);
})(typeof self !== 'undefined' ? self : (typeof globalThis !== 'undefined' ? globalThis : this), function (root) {
  'use strict';

  /* Lazy access to sibling modules, so load order and node require both work. */
  function sib(name, file) {
    if (typeof module === 'object' && module.exports) {
      try { return require(file); } catch (e) { return null; }
    }
    return (root.McA || {})[name] || null;
  }
  function persistMod() { return sib('persist', './persist.js'); }
  function stagesMod() { return sib('stages', '../logic/stages.js'); }
  function runstateMod() { return sib('runstate', '../logic/runstate.js'); }

  function idleRun() {
    return { id: null, kind: null, session: null, part: null, state: 'idle', verdict: null,
             startedAt: null, finishedAt: null, exit: null, cancelled: false, cancelPending: false,
             lines: [], track: null, summary: null, error: null };
  }
  function emptyOutputs() { return { ctx: null, payload: null, loading: false, error: null, fetchedAt: null }; }
  function emptyIntake() {
    return { items: [], source: null, originalFile: null, stem: 'drawing', format: '',
             nameDraft: '', notesDraft: '', previewOverride: false, pendingCad: null, expectEcho: false };
  }

  /** Initial state (ARCH 4.2). ui starts from persisted values. */
  function initialState() {
    var p = persistMod();
    var ui = p ? p.loadUi() : { sidebarCollapsed: false, inspectorCollapsed: false,
      inspectorOpen: { setup: true, actions: true, corrections: true, export: true },
      drawerOpen: false, drawerHeight: 320, drawerSection: 'overview', splitRatio: 0.5, resultsSection: 'overview' };
    ui.drawerMode = 'results';
    ui.maximized = null;
    ui.narrowTab = '2d';
    ui.focusMode = null;
    ui.raw = {};
    ui.flagsFilter = [];
    ui.consoleFilter = 'all';
    ui.corrDraft = {};
    return {
      route: { page: 'home', params: {} },
      server: { loaded: false, reachable: false, live: false, samples: [], model: null, provider: null, keyName: null, outputs: null },
      session: { id: null },
      parts: { list: [], selected: null, loading: false, error: null },
      intake: emptyIntake(),
      markup: { regionsByKey: {}, originByKey: {}, datumsByKey: {}, dirty: [], tool: 'draw',
                color: null, role: null, datumKind: null, saveState: 'idle' },
      run: idleRun(),
      batch: { active: false, queue: [], index: 0, results: {} },
      history: { runs: [], loaded: false, error: null },
      outputs: emptyOutputs(),
      viewer3d: { status: 'empty', url: null, source: null, previousRun: null, error: null },
      ui: ui
    };
  }

  var enqueue = typeof queueMicrotask === 'function' ? queueMicrotask
    : function (fn) { Promise.resolve().then(fn); };

  function splitPath(path) { return Array.isArray(path) ? path : String(path).split('.'); }
  function getIn(obj, path) {
    var p = splitPath(path);
    for (var i = 0; i < p.length; i++) { if (obj === null || obj === undefined) return undefined; obj = obj[p[i]]; }
    return obj;
  }
  function setIn(obj, path, value) {
    var p = splitPath(path);
    if (!p.length) return value;
    var copy = Array.isArray(obj) ? obj.slice() : Object.assign({}, obj);
    copy[p[0]] = p.length === 1 ? value : setIn(obj ? obj[p[0]] : undefined, p.slice(1), value);
    return copy;
  }
  function ctxEqual(a, b) {
    if (!a || !b) return a === b;
    if (a.kind !== b.kind) return false;
    return a.kind === 'part' ? (a.session === b.session && a.part === b.part) : a.runId === b.runId;
  }

  function createStore(initial) {
    var state = initial;
    var reducers = Object.create(null);
    var subs = [];
    var scheduled = false;

    function flush() {
      scheduled = false;
      var list = subs.slice();
      for (var i = 0; i < list.length; i++) {
        var s = list[i];
        if (s.dead) continue;
        var next = s.sel(state);
        if (next !== s.last) {
          var prev = s.last; s.last = next;
          try { s.cb(next, prev); } catch (e) { if (root.console) root.console.error(e); }
        }
      }
    }
    function schedule() { if (!scheduled) { scheduled = true; enqueue(flush); } }

    var api = {
      get: function () { return state; },
      set: function (patch) { state = Object.assign({}, state, patch); schedule(); return state; },
      update: function (path, fn) {
        state = setIn(state, path, fn(getIn(state, path)));
        schedule(); return state;
      },
      subscribe: function (selector, cb) {
        var sel = typeof selector === 'function' ? selector : function (s) { return getIn(s, selector); };
        var sub = { sel: sel, cb: cb, last: sel(state), dead: false };
        subs.push(sub);
        return function unsubscribe() { sub.dead = true; subs = subs.filter(function (x) { return x !== sub; }); };
      },
      register: function (type, fn) { reducers[type] = fn; return api; },
      has: function (type) { return !!reducers[type]; },
      dispatch: function (type, payload) {
        var fn = reducers[type];
        if (!fn) throw new Error('McA.store: no reducer registered for "' + type + '"');
        var patch = fn(state, payload, api);
        if (patch) api.set(patch);
        return state;
      },
      /** Run pending notifications now (tests, and code that needs them synchronously). */
      flush: flush,
      /** Replace everything (tests, "reset"). */
      reset: function (next) { state = next || initialState(); schedule(); return state; },
      createStore: createStore,
      initialState: initialState,
      idleRun: idleRun
    };
    registerBuiltins(api);
    return api;
  }

  /* ── Built-in reducers: pure state transitions only. Side effects (fetch, SSE,
        timers) live in features/*. ───────────────────────────────────────────── */
  var seq = 0;
  function nextId() { return 'it' + (++seq); }

  function registerBuiltins(store) {
    function R(type, fn) { store.register(type, fn); }

    R('route/set', function (s, p) { return { route: { page: p.page, params: p.params || {} } }; });
    R('session/set', function (s, p) { return { session: { id: p.id } }; });

    R('server/status', function (s, p) {
      return { server: Object.assign({}, s.server, {
        loaded: true, reachable: true, live: !!p.live,
        samples: Array.isArray(p.samples) ? p.samples : [],
        model: p.model || null, provider: p.provider || null,
        keyName: p.keyName || null, outputs: p.outputs || null }) };
    });
    R('server/unreachable', function (s) {
      return { server: Object.assign({}, s.server, { loaded: true, reachable: false }) };
    });

    R('parts/loading', function (s) { return { parts: Object.assign({}, s.parts, { loading: true, error: null }) }; });
    R('parts/loaded', function (s, p) {
      return { parts: Object.assign({}, s.parts, { list: p.list || [], loading: false, error: null }) };
    });
    R('parts/error', function (s, p) {
      return { parts: Object.assign({}, s.parts, { loading: false, error: p.error || 'error' }) };
    });
    R('parts/select', function (s, p) {
      var sel = p && p.part ? { session: p.session, part: p.part } : null;
      if (ctxEqual(sel && { kind: 'part', session: sel.session, part: sel.part },
                   s.outputs.ctx) && s.parts.selected) return null;
      return {
        parts: Object.assign({}, s.parts, { selected: sel }),
        outputs: Object.assign(emptyOutputs(), { ctx: sel ? { kind: 'part', session: sel.session, part: sel.part } : null })
      };
    });

    R('intake/add', function (s, p) {
      var add = (Array.isArray(p) ? p : (p.items || [p])).map(function (it) {
        return Object.assign({ orientation: '', label: '' }, it, { id: it.id || nextId() });
      });
      return { intake: Object.assign({}, s.intake, { items: s.intake.items.concat(add) }) };
    });
    R('intake/update', function (s, p) {
      if (p.id) {
        return { intake: Object.assign({}, s.intake, { items: s.intake.items.map(function (it) {
          return it.id === p.id ? Object.assign({}, it, p.patch) : it; }) }) };
      }
      return { intake: Object.assign({}, s.intake, p.patch || p) };
    });
    R('intake/remove', function (s, p) {
      return { intake: Object.assign({}, s.intake, { items: s.intake.items.filter(function (it) { return it.id !== p.id; }) }) };
    });
    R('intake/reset', function () { return { intake: emptyIntake() }; });

    R('markup/set', function (s, p) { return { markup: Object.assign({}, s.markup, p) }; });
    R('viewer3d/set', function (s, p) { return { viewer3d: Object.assign({}, s.viewer3d, p) }; });
    R('ui/set', function (s, p) { return { ui: Object.assign({}, s.ui, p) }; });
    R('ui/inspectorSection', function (s, p) {
      var open = Object.assign({}, s.ui.inspectorOpen);
      open[p.id] = p.open === undefined ? !open[p.id] : !!p.open;
      return { ui: Object.assign({}, s.ui, { inspectorOpen: open }) };
    });

    /* Run lifecycle. */
    R('run/queued', function (s, p) {
      var st = stagesMod();
      return { run: Object.assign(idleRun(), { kind: p.kind, session: p.session || null, part: p.part || null,
        state: 'queued', track: st ? st.initial(p.kind) : null }) };
    });
    R('run/started', function (s, p) {
      return { run: Object.assign({}, s.run, { id: p.id, state: 'running', startedAt: p.startedAt || Date.now(), error: null }) };
    });
    R('run/line', function (s, p) {
      if (s.run.id !== p.id) return null;              // stale SSE message
      var st = stagesMod();
      return { run: Object.assign({}, s.run, { lines: s.run.lines.concat([p.line]),
        track: st ? st.reduce(s.run.track || st.initial(s.run.kind), p.line) : s.run.track }) };
    });
    R('run/lines', function (s, p) {                    // bulk replay (reconnect)
      if (s.run.id !== p.id) return null;
      var st = stagesMod(), track = s.run.track || (st && st.initial(s.run.kind));
      if (st) p.lines.forEach(function (l) { track = st.reduce(track, l); });
      return { run: Object.assign({}, s.run, { lines: s.run.lines.concat(p.lines), track: track }) };
    });
    R('run/cancelPending', function (s) { return { run: Object.assign({}, s.run, { cancelPending: true }) }; });
    R('run/error', function (s, p) {                    // launch failed before an id existed
      return { run: Object.assign(idleRun(), { error: p.error || 'error' }) };
    });
    R('run/reset', function () { return { run: idleRun() }; });
    R('run/restore', function (s, p) {
      var st = stagesMod();
      return { run: Object.assign(idleRun(), { id: p.id, kind: p.kind, session: p.session || null, part: p.part || null,
        state: 'running', startedAt: p.startedAt, track: st ? st.initial(p.kind) : null }) };
    });
    /* Payload: {id, exit, cancelled?, summary, payload (runOutputs response), finishedAt?}.
       Computes track, run state and verdict in one place so every view agrees. */
    R('run/finalized', function (s, p) {
      if (s.run.id !== p.id) return null;
      var st = stagesMod(), rs = runstateMod();
      var payload = p.payload || null;
      var cancelled = !!(p.cancelled || s.run.cancelled || (payload && payload.cancelled));
      var startedSec = payload && typeof payload.started === 'number' ? payload.started
        : (s.run.startedAt ? s.run.startedAt / 1000 : null);
      var summary = p.summary || null;
      var track = st.finalize(s.run.track || st.initial(s.run.kind),
        { exit: p.exit, cancelled: cancelled, summary: summary, payload: payload, startedAt: startedSec });
      var cats = (payload && payload.categories) || {};
      var runState = rs.deriveRunState({ hasId: true, done: true, exit: p.exit, cancelled: cancelled, summary: summary, irReport: cats.ir_report });
      var verdict = rs.deriveVerdict({ summary: summary, mustMeet: cats.must_meet || null, irReport: cats.ir_report,
        stlSource: payload ? payload.stl_source : null, stlFresh: rs.stlFresh(payload, startedSec),
        kind: s.run.kind, exit: p.exit, cancelled: cancelled });
      return { run: Object.assign({}, s.run, { state: runState, verdict: verdict, exit: p.exit, cancelled: cancelled,
        cancelPending: false, finishedAt: p.finishedAt || Date.now(), summary: summary, track: track }) };
    });

    /* Batch. */
    R('batch/start', function (s, p) { return { batch: { active: true, queue: p.queue.slice(), index: 0, results: {} } }; });
    R('batch/next', function (s) { return { batch: Object.assign({}, s.batch, { index: s.batch.index + 1 }) }; });
    R('batch/result', function (s, p) {
      var r = Object.assign({}, s.batch.results); r[p.part] = p.result;
      return { batch: Object.assign({}, s.batch, { results: r }) };
    });
    R('batch/stop', function (s) { return { batch: Object.assign({}, s.batch, { active: false }) }; });

    /* Outputs and history: stale-response rule, results for a ctx that is no longer current are dropped. */
    R('outputs/ctx', function (s, p) { return { outputs: Object.assign(emptyOutputs(), { ctx: p.ctx || null }) }; });
    R('outputs/loading', function (s, p) {
      if (!ctxEqual(p.ctx, s.outputs.ctx)) return null;
      return { outputs: Object.assign({}, s.outputs, { loading: true, error: null }) };
    });
    R('outputs/loaded', function (s, p) {
      if (!ctxEqual(p.ctx, s.outputs.ctx)) return null;
      return { outputs: Object.assign({}, s.outputs, { payload: p.payload, loading: false, error: null,
        fetchedAt: p.fetchedAt || Date.now() }) };
    });
    R('outputs/error', function (s, p) {
      if (!ctxEqual(p.ctx, s.outputs.ctx)) return null;
      return { outputs: Object.assign({}, s.outputs, { loading: false, error: p.error || 'error' }) };
    });
    R('history/loaded', function (s, p) { return { history: { runs: p.runs || [], loaded: true, error: null } }; });
    R('history/error', function (s, p) { return { history: Object.assign({}, s.history, { loaded: true, error: p.error || 'error' }) }; });
  }

  var instance = createStore(initialState());
  instance.ctxEqual = ctxEqual;

  /* Browser only: persist the layout slice of ui (debounced). */
  var p = persistMod();
  if (p && root.localStorage && root.document) {
    var timer = null;
    instance.subscribe(function (s) { return s.ui; }, function (ui) {
      if (timer !== null) clearTimeout(timer);
      timer = setTimeout(function () { timer = null; p.saveUi(ui); }, 150);
    });
  }
  return instance;
});
