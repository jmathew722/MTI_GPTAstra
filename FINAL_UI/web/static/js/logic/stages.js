/* McA.stages: PURE stage-tracker logic (ARCH 6). No DOM, no fetch.
   initial(kind) / reduce(track, line) / finalize(track, facts) / percent(track) / view(track). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).stages = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /* Sub-steps (the real work units), in emission order. Match by longest prefix. */
  var MARKERS = [
    { k: 0,  prefix: 'Overview analysis',               label: 'Overview analysis' },
    { k: 1,  prefix: 'Extracting',                      label: 'Extracting views' },
    { k: 2,  prefix: 'Spec reconciliation',             label: 'Spec reconciliation' },
    { k: 3,  prefix: 'Resolving',                       label: 'Resolving ambiguities' },
    { k: 4,  prefix: 'Verifying',                       label: 'Verifying extracted data' },
    { k: 5,  prefix: 'Building macros',                 label: 'Building macros' },
    { k: 6,  prefix: 'Pre-validating (CadQuery)',       label: 'Pre-validating (CadQuery)' },
    { k: 7,  prefix: 'Building .sldprt',                label: 'Building .sldprt' },
    { k: 8,  prefix: 'Verifying must-meet constraints', label: 'Verifying must-meet constraints' },
    { k: 9,  prefix: 'Final checks',                    label: 'Final checks' },
    { k: 10, prefix: 'Exporting',                       label: 'Exporting' },
    { k: 11, prefix: 'Done',                            label: 'Done' }
  ];
  var BY_LENGTH = MARKERS.slice().sort(function (a, b) { return b.prefix.length - a.prefix.length; });
  var LAST_PART_UNIT = 11;     // percent denominator for part runs

  /* Presentation stages. ks = sub-steps owned; work = sub-steps that prove the stage ran
     (Exporting, k=10, is always printed, so it does not prove Verification ran). */
  var PART_STAGES = [
    { id: 'extraction',   label: 'Extraction',   ks: [0, 1],      work: [0, 1] },
    { id: 'resolution',   label: 'Resolution',   ks: [2, 3],      work: [2, 3] },
    { id: 'build_plan',   label: 'Build Plan',   ks: [4, 5],      work: [4, 5] },
    { id: 'generation',   label: 'Generation',   ks: [6, 7],      work: [6, 7] },
    { id: 'verification', label: 'Verification', ks: [8, 9, 10],  work: [8, 9] }
  ];
  var DEMO_SKIP_DETAIL = 'Demo runs stop after the macro package';
  var DEMO_STEPS = [
    { k: 0, re: /^\s*\[1-2\/4\]/,   label: 'Loaded saved extraction' },
    { k: 1, re: /^\s*\[2\.5\/4\]/,  label: 'Resolving ambiguities' },
    { k: 2, re: /^\s*\[3\/4\]/,     label: 'Verifying extracted data' },
    { k: 3, re: /^\s*\[4\/4\]/,     label: 'Generating macro package' }
  ];
  var DEMO_STAGES = [
    { id: 'extraction',   label: 'Extraction',   ks: [0],    work: [0] },
    { id: 'resolution',   label: 'Resolution',   ks: [1],    work: [1] },
    { id: 'build_plan',   label: 'Build Plan',   ks: [2, 3], work: [2, 3] },
    { id: 'generation',   label: 'Generation',   ks: [],     work: [] },
    { id: 'verification', label: 'Verification', ks: [],     work: [] }
  ];

  function stagesFor(kind) { return kind === 'demo' ? DEMO_STAGES : PART_STAGES; }
  function unitsFor(kind) { return kind === 'demo' ? DEMO_STEPS.length : LAST_PART_UNIT; }

  function initial(kind) {
    return { kind: kind === 'demo' ? 'demo' : 'part', k: -1, seen: new Set(),
             signals: { extractFailed: false, processFailed: false, resolveWarn: false, extractWarn: false },
             done: false, final: null };
  }

  /** "[STAGE] Extracting 117C" -> {k:1, marker, rest:'117C'}; null if not a marker. */
  function parseMarker(line) {
    var m = /^\s*\[STAGE\]\s+(.*?)\s*$/.exec(String(line));
    if (!m) return null;
    var text = m[1];
    for (var i = 0; i < BY_LENGTH.length; i++) {
      var p = BY_LENGTH[i].prefix;
      if (text.indexOf(p) === 0 && (text.length === p.length || /^[\s:(\-]/.test(text.charAt(p.length)))) {
        return { k: BY_LENGTH[i].k, marker: p, rest: text.slice(p.length).trim() };
      }
    }
    return null;
  }

  function reduce(track, line) {
    var s = String(line === null || line === undefined ? '' : line);
    var k = track.k, seen = track.seen, sig = track.signals, changed = false;
    var idx = -1;
    if (track.kind === 'demo') {
      for (var i = 0; i < DEMO_STEPS.length; i++) if (DEMO_STEPS[i].re.test(s)) { idx = DEMO_STEPS[i].k; break; }
    } else {
      var mk = parseMarker(s);
      if (mk) idx = mk.k;
    }
    if (idx > k) { k = idx; seen = new Set(seen); seen.add(idx); changed = true; }

    var next = sig;
    function flag(name) { if (!next[name]) { if (next === sig) next = Object.assign({}, sig); next[name] = true; changed = true; } }
    if (/Extraction failed\b/.test(s)) flag('extractFailed');
    if (/Processing failed:/.test(s)) flag('processFailed');
    if (/^\[SPEC\] (CRITICAL|HIGH):/.test(s)) flag('resolveWarn');
    if (/Overview analysis unavailable|Could not classify view|No FRONT view found/.test(s)) flag('extractWarn');
    if (/^\[(launch|reader) error\]/.test(s)) flag('processFailed');

    if (!changed) return track;
    return { kind: track.kind, k: k, seen: seen, signals: next, done: track.done, final: track.final };
  }

  function stageIndexOfK(kind, k) {
    var st = stagesFor(kind);
    for (var i = 0; i < st.length; i++) if (st[i].ks.indexOf(k) !== -1) return i;
    return -1;
  }
  function anySeen(track, ks) { for (var i = 0; i < ks.length; i++) if (track.seen.has(ks[i])) return true; return false; }
  /** Highest real work marker seen (excludes Exporting and Done). */
  function lastWorkK(track) {
    var best = -1;
    track.seen.forEach(function (v) { if (v <= 9 && v > best) best = v; });
    return best;
  }

  /* Live (not finalized) state of every stage. */
  function liveStates(track) {
    var st = stagesFor(track.kind), k = track.k, out = [];
    var sig = track.signals;
    var procIdx = sig.processFailed ? stageIndexOfK(track.kind, Math.max(lastWorkK(track), 0)) : -1;
    for (var i = 0; i < st.length; i++) {
      var S = st[i], min = S.ks.length ? Math.min.apply(null, S.ks) : null, max = S.ks.length ? Math.max.apply(null, S.ks) : null;
      var r;
      if (track.kind === 'demo' && !S.ks.length) r = { state: 'skipped', detail: DEMO_SKIP_DETAIL };
      else if (S.id === 'extraction' && sig.extractFailed) r = { state: 'failed', detail: 'Extraction failed' };
      else if (i === procIdx) r = { state: 'failed', detail: 'Processing failed' };
      else if (k < min) r = { state: 'pending', detail: '' };
      else if (S.ks.indexOf(k) !== -1) {
        // Exporting (k=10) with no verification work seen means verification never ran.
        if (S.id === 'verification' && k === 10 && !anySeen(track, S.work)) r = { state: 'skipped', detail: 'Not reached' };
        else r = { state: 'running', detail: '' };
      } else {                                              // k > max
        if (!anySeen(track, S.work)) r = { state: 'skipped', detail: '' };
        else {
          var warn = (S.id === 'extraction' && sig.extractWarn) || (S.id === 'resolution' && sig.resolveWarn);
          r = { state: warn ? 'warning' : 'succeeded', detail: warn ? 'Warnings in the console' : '' };
        }
      }
      out.push(r);
    }
    return out;
  }

  function num(v) { var n = Number(v); return isFinite(n) ? n : 0; }
  function isFresh(payload, startedAt) {
    return !!(payload && typeof payload.stl_mtime === 'number' && payload.stl_mtime > 0 &&
              typeof startedAt === 'number' && payload.stl_mtime >= Math.floor(startedAt));
  }

  /** facts: {exit, cancelled, summary, payload, startedAt (epoch seconds)}. Returns a new track. */
  function finalize(track, facts) {
    var f = facts || {}, st = stagesFor(track.kind), states = liveStates(track);
    var exit = f.exit, summary = f.summary || null, payload = f.payload || null;
    var cats = (payload && payload.categories) || {};
    var status = summary && summary.status ? String(summary.status).toUpperCase() : null;
    var i, runningIdx = -1;
    for (i = 0; i < states.length; i++) if (states[i].state === 'running') runningIdx = i;

    function setAfter(from, state, detail) {
      for (var j = from; j < states.length; j++) if (states[j].state === 'pending') states[j] = { state: state, detail: detail };
    }
    var decided = false;

    if (f.cancelled) {                                                   // rule 1
      decided = true;
      if (runningIdx >= 0) { states[runningIdx] = { state: 'skipped', detail: 'Cancelled' }; setAfter(runningIdx + 1, 'skipped', 'Not reached'); }
      else setAfter(0, 'skipped', 'Cancelled');
      for (i = 0; i < states.length; i++) if (states[i].state === 'running') states[i] = { state: 'skipped', detail: 'Cancelled' };
    } else if (exit !== 0 && exit !== 8 && exit !== null && exit !== undefined) {   // rule 2
      var firstPending = -1;
      for (i = 0; i < states.length; i++) if (states[i].state === 'pending') { firstPending = i; break; }
      var failIdx = runningIdx >= 0 ? runningIdx : (track.k < 0 ? 0 : (firstPending >= 0 && track.k < 11 ? firstPending : -1));
      if (track.kind === 'demo' && failIdx >= 0 && states[failIdx].state === 'skipped') failIdx = -1;
      if (failIdx >= 0) {
        decided = true;
        states[failIdx] = { state: 'failed', detail: 'Exited with code ' + exit };
        setAfter(failIdx + 1, 'skipped', 'Not reached');
      }
    }

    if (!decided) {
      // Anything still running or pending after the process ended resolved without a marker.
      for (i = 0; i < states.length; i++) {
        if (states[i].state === 'running') states[i] = { state: 'succeeded', detail: '' };
      }
      if (track.kind === 'demo') {
        setAfter(0, 'skipped', 'Not reached');
      } else {
        var wk = lastWorkK(track);
        var detailOf = summary && summary.detail ? String(summary.detail) : '';
        // rule 3: extraction
        if (track.signals.extractFailed || (status === 'ERROR' && wk <= 1)) {
          states[0] = { state: 'failed', detail: detailOf || 'Extraction failed' };
        } else if (status === 'ERROR') {                              // rule 4 (generalised): the stage that was working
          var ei = stageIndexOfK('part', wk);
          if (ei >= 0) states[ei] = { state: 'failed', detail: detailOf || 'Processing failed' };
        }
        // rule 4: build plan
        if (states[2].state !== 'failed' && track.seen.has(4)) {
          if (status === 'BLOCKED') states[2] = { state: 'failed', detail: detailOf || 'Blocked by the verification gate' };
          else if (states[2].state !== 'failed' && summary && (num(summary.n_needs_review) > 0 || num(summary.n_skipped) > 0)) {
            states[2] = { state: 'warning', detail: num(summary.n_needs_review) + ' need review, ' + num(summary.n_skipped) + ' skipped' };
          }
        }
        // rule 5: generation
        var fresh = isFresh(payload, f.startedAt);
        var src = payload ? payload.stl_source : null;
        if (states[3].state !== 'failed') {
          if (track.seen.has(7)) {
            if (!payload) states[3] = { state: 'warning', detail: 'Output files could not be checked' };
            else if (src === 'solidworks' && fresh) states[3] = { state: 'succeeded', detail: '' };
            else states[3] = { state: 'failed', detail: /sldprt build failed/.test(detailOf) ? detailOf : 'SolidWorks produced no new model' };
          } else if (src === 'prevalidation' && fresh) {
            states[3] = { state: 'warning', detail: 'SolidWorks not available on this machine; CadQuery pre-validation model only' };
          } else if (states[3].state !== 'skipped') {
            states[3] = { state: 'skipped', detail: '' };
          }
        }
        // rule 6: verification
        if (states[4].state !== 'failed') {
          if (!track.seen.has(9)) states[4] = { state: 'skipped', detail: 'Not reached' };
          else {
            var mm = cats.must_meet;
            if (mm && mm.stage === 'post_build' && mm.ok === false) {
              states[4] = { state: 'failed', detail: (mm.failed && mm.failed.length ? mm.failed[0] : 'Must-meet constraints failed') };
            } else if (status === 'NOT READY') states[4] = { state: 'warning', detail: detailOf || 'Review flags' };
            else if (status === 'READY') states[4] = { state: 'succeeded', detail: '' };
            else states[4] = { state: 'warning', detail: 'Result summary not available' };
          }
        }
      }
    }
    // rule 7: stages after a failed stage that never ran
    var failedAt = -1;
    for (i = 0; i < states.length; i++) if (states[i].state === 'failed') { failedAt = i; break; }
    if (failedAt >= 0) {
      for (i = failedAt + 1; i < states.length; i++) {
        if (states[i].state === 'skipped' && !states[i].detail) states[i] = { state: 'skipped', detail: 'Not reached' };
        else if (states[i].state === 'pending') states[i] = { state: 'skipped', detail: 'Not reached' };
      }
    }
    for (i = 0; i < states.length; i++) if (states[i].state === 'pending') states[i] = { state: 'skipped', detail: 'Not reached' };

    return { kind: track.kind, k: track.k, seen: track.seen, signals: track.signals, done: true,
             final: { exit: exit === undefined ? null : exit, cancelled: !!f.cancelled, stages: states } };
  }

  /** Integer 0-100, or null (indeterminate / removed on failure and cancel). */
  function percent(track) {
    if (track.final) {
      if (track.final.cancelled) return null;
      return track.final.exit === 0 || track.final.exit === 8 ? 100 : null;
    }
    if (track.k < 0) return null;
    return Math.min(99, Math.floor(100 * track.k / unitsFor(track.kind)));
  }

  function subLabels(kind) {
    return kind === 'demo' ? DEMO_STEPS.map(function (d) { return { k: d.k, label: d.label }; })
      : MARKERS.filter(function (m) { return m.k <= 10; }).map(function (m) { return { k: m.k, label: m.label }; });
  }

  /** {stages:[{id,label,state,detail,substeps:[{k,label,state}]}] x5, currentIndex, caption, stageNumber, stageCount, percent}. */
  function view(track) {
    track = track || initial('part');
    var st = stagesFor(track.kind), states = track.final ? track.final.stages : liveStates(track);
    var labels = subLabels(track.kind), stages = [], i;
    var currentIndex = -1, running = -1, lastActive = -1;
    for (i = 0; i < st.length; i++) {
      var S = st[i];
      var subs = labels.filter(function (l) { return S.ks.indexOf(l.k) !== -1; }).map(function (l) {
        var sstate;
        if (track.seen.has(l.k)) sstate = (!track.final && l.k === track.k) ? 'running' : 'succeeded';
        else sstate = (track.k > l.k || track.final) ? 'skipped' : 'pending';
        if (track.final && sstate === 'succeeded' && states[st.indexOf(S)].state === 'failed' && l.k === lastWorkK(track)) sstate = 'failed';
        return { k: l.k, label: l.label, state: sstate };
      });
      stages.push({ id: S.id, label: S.label, state: states[i].state, detail: states[i].detail, substeps: subs });
      if (states[i].state === 'running') running = i;
      if (states[i].state !== 'pending' && states[i].state !== 'skipped') lastActive = i;
    }
    currentIndex = running >= 0 ? running : lastActive;
    var caption = '';
    if (track.final) {
      caption = track.final.cancelled ? 'Cancelled' : (stages.some(function (s) { return s.state === 'failed'; }) ? 'Failed' : 'Complete');
    } else if (track.k < 0) caption = 'Starting…';
    else {
      var cur = labels.filter(function (l) { return l.k === track.k; })[0];
      caption = cur ? cur.label + '…' : (track.k >= unitsFor(track.kind) ? 'Finishing…' : '');
    }
    return { stages: stages, currentIndex: currentIndex, caption: caption,
             stageNumber: currentIndex >= 0 ? currentIndex + 1 : 0, stageCount: st.length, percent: percent(track) };
  }

  return { MARKERS: MARKERS, PART_STAGES: PART_STAGES, DEMO_STAGES: DEMO_STAGES, parseMarker: parseMarker,
           initial: initial, reduce: reduce, finalize: finalize, percent: percent, view: view };
});
