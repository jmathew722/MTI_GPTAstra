/* McA.stages: PURE stage-tracker logic (ARCH 6). No DOM, no fetch.
   initial(kind) / reduce(track, line) / finalize(track, facts) / percent(track) / view(track).

   Markers match THIS pipeline's actual log output (pipeline/ir_pipeline.py run_part, which
   logs "[stage] <name>: <message>" at each real phase boundary, through utils.logger -- so a
   captured line looks like "[09:22:51] INFO     [stage] extraction: reading 1 image(s) for X",
   never column 0). Per-feature SolidWorks progress ("  F001: SW volume ... (ok, attempt 1)",
   from pipeline/ir/compile_solidworks.py) is matched separately as mid-Generation progress. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).stages = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /* Sub-steps (the real work units the IR path reports), in emission order. */
  var MARKERS = [
    { k: 0, label: 'Reading the drawing' },
    { k: 1, label: 'Resolving ambiguous references' },
    { k: 2, label: 'Planning the build' },
    { k: 3, label: 'Gate 1 check' },
    { k: 4, label: 'Building the CadQuery reference' },
    { k: 5, label: 'Reference built' },
    { k: 6, label: 'Building SolidWorks features' },
    { k: 7, label: 'Verification' }
  ];
  var LAST_PART_UNIT = 7;     // percent denominator for part runs

  /* Presentation stages. ks = sub-steps owned; work = sub-steps that prove the stage ran
     (k=6, per-feature progress, is optional even on success -- a part with zero features
     besides the base prism still succeeds without ever emitting it). */
  var PART_STAGES = [
    { id: 'extraction',   label: 'Extraction',   ks: [0],       work: [0] },
    { id: 'resolution',   label: 'Resolution',   ks: [1],       work: [1] },
    { id: 'build_plan',   label: 'Build Plan',   ks: [2, 3],    work: [2, 3] },
    { id: 'generation',   label: 'Generation',   ks: [4, 5, 6], work: [4, 5] },
    { id: 'verification', label: 'Verification', ks: [7],       work: [7] }
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

  /* ---- Structured telemetry (pipeline/run_events.py). The backend owns the percentage; this file
     only folds events in (idempotent by seq, stale runs ignored, never backward) and reports what
     it was told. Legacy runs (no events) keep the marker count and are labeled "legacy_markers". */
  var EVENT_PREFIX = '[gptastra-event] ';
  var MAX_TEXT = 300;
  var PROGRESS_KEYS = ['phase', 'operation', 'label', 'completed_units', 'total_units', 'unit',
    'phase_completed_units', 'phase_total_units', 'overall_completed_weight', 'overall_total_weight',
    'percent', 'indeterminate', 'terminal'];
  var COST_KEYS = ['currency', 'run_cost_usd', 'part_total_cost_usd', 'session_total_cost_usd', 'input_tokens',
    'cached_input_tokens', 'output_tokens', 'api_calls', 'unpriced_calls', 'pricing_status',
    'part_pricing_status', 'session_pricing_status', 'pricing_source', 'legacy_rows', 'as_of'];
  var TERMINAL = { 'run.completed': 'completed', 'run.failed': 'failed', 'run.cancelled': 'cancelled' };

  function pick(src, keys) {
    var out = {};
    if (!src || typeof src !== 'object') return out;
    keys.forEach(function (k) {
      if (!Object.prototype.hasOwnProperty.call(src, k)) return;
      var v = src[k];
      if (typeof v === 'string') out[k] = v.slice(0, MAX_TEXT);
      else if (v === null || typeof v === 'number' || typeof v === 'boolean') out[k] = v;
    });
    return out;
  }
  function parseEvent(line) {
    var s = String(line === null || line === undefined ? '' : line);
    var i = s.indexOf(EVENT_PREFIX);
    if (i < 0) return null;
    var o;
    try { o = JSON.parse(s.slice(i + EVENT_PREFIX.length)); } catch (e) { return null; }
    if (!o || typeof o !== 'object' || Array.isArray(o)) return null;
    if (typeof o.run_id !== 'string' || typeof o.seq !== 'number' || typeof o.attempt !== 'number' ||
        typeof o.kind !== 'string' || !o.payload || typeof o.payload !== 'object') return null;
    return o;
  }
  /** New tel (or the same object when the event changes nothing). */
  function applyEvent(tel, ev) {
    var kind = ev.kind;
    if (!tel || tel.run_id !== ev.run_id) {
      var takes = !tel || (kind === 'run.started' && ev.attempt > tel.attempt);
      if (!takes) return tel;                               // stale run: never overwrites the active attempt
      tel = { run_id: ev.run_id, attempt: ev.attempt, last_seq: 0, progress: null, cost: null, terminal: null };
    }
    if (ev.seq <= tel.last_seq) return tel;                 // duplicate or late
    var next = Object.assign({}, tel, { last_seq: ev.seq });
    if (kind === 'progress.updated') {
      var snap = pick(ev.payload, PROGRESS_KEYS);
      var oldP = tel.progress ? tel.progress.percent : null;
      if (typeof snap.percent === 'number' && typeof oldP === 'number' && snap.percent < oldP) return tel;   // never backward
      next.progress = snap;
    } else if (kind === 'cost.updated') next.cost = pick(ev.payload, COST_KEYS);
    else if (TERMINAL[kind]) next.terminal = TERMINAL[kind];
    return next;
  }
  /** Adopt a server snapshot (reconnect after refresh). Legacy or older snapshots change nothing. */
  function applyTelemetry(track, snap) {
    if (!snap || snap.source !== 'structured' || typeof snap.run_id !== 'string') return track;
    var cur = track.tel;
    var newer = !cur || (snap.run_id !== cur.run_id ? snap.attempt > cur.attempt : snap.last_seq > cur.last_seq);
    if (!newer) return track;
    var tel = { run_id: snap.run_id, attempt: snap.attempt, last_seq: snap.last_seq || 0,
                progress: snap.progress ? pick(snap.progress, PROGRESS_KEYS) : null,
                cost: snap.cost ? pick(snap.cost, COST_KEYS) : null, terminal: snap.terminal || null };
    return Object.assign({}, track, { tel: tel });
  }
  function telPercent(tel) {
    var p = tel.progress ? tel.progress.percent : null;
    if (tel.terminal === 'completed' || (tel.progress && tel.progress.terminal === 'completed')) return 100;
    if (typeof p !== 'number') return null;
    return Math.min(99, Math.floor(p));                    // 100 only from the backend's completed event
  }

  function stagesFor(kind) { return kind === 'demo' ? DEMO_STAGES : PART_STAGES; }
  function unitsFor(kind) { return kind === 'demo' ? DEMO_STEPS.length : LAST_PART_UNIT; }

  function initial(kind) {
    return { kind: kind === 'demo' ? 'demo' : 'part', k: -1, seen: new Set(),
             signals: { extractFailed: false, processFailed: false, resolveWarn: false, extractWarn: false },
             done: false, final: null, tel: null };
  }

  /* "[stage] build_plan_gate1: gate1=OK planned=7 questions=0" -> {k:3, marker, rest}.
     No "^" anchor: the real line always carries a logger timestamp/level before the tag.
     Each tag NAME alone determines k -- never the trailing %s-interpolated text, which the
     console wraps at a fixed width and can split across a continuation line (verified against
     a real captured run: free-text arguments get cut mid-word, the tag itself never does).
     null if the line is not one of this pipeline's markers. */
  var TAG_K = { extraction: 0, resolution: 1, build_plan_start: 2, build_plan_gate1: 3,
                generation_start: 4, generation_reference: 5, verification: 7 };
  function parseMarker(line) {
    var s = String(line === null || line === undefined ? '' : line);
    // No trailing end-anchor: the real transcript is CRLF, and the regex dot does not
    // match a bare carriage return, so an end-anchored pattern fails on every real line
    // (verified against a captured run). Matching without the anchor is simpler and correct.
    var m = /\[stage\]\s+([a-z0-9_]+)\s*:\s*(.*)/i.exec(s);
    if (m) {
      var name = m[1].toLowerCase();
      if (Object.prototype.hasOwnProperty.call(TAG_K, name)) return { k: TAG_K[name], marker: name, rest: m[2] };
      return null;
    }
    if (/F\d+:\s*SW volume/.test(s)) return { k: 6, marker: 'sw_feature', rest: '' };
    return null;
  }

  function reduce(track, line) {
    var s = String(line === null || line === undefined ? '' : line);
    if (s.indexOf(EVENT_PREFIX) >= 0) {                      // a structured event: never a log marker
      var ev = parseEvent(s);
      if (!ev) return track;
      var tel2 = applyEvent(track.tel, ev);
      return tel2 === track.tel ? track : Object.assign({}, track, { tel: tel2 });
    }
    var k = track.k, seen = track.seen, sig = track.signals, changed = false;
    var idx = -1;
    if (track.kind === 'demo') {
      for (var i = 0; i < DEMO_STEPS.length; i++) if (DEMO_STEPS[i].re.test(s)) { idx = DEMO_STEPS[i].k; break; }
    } else {
      var mk = parseMarker(s);
      if (mk) idx = mk.k;
    }
    if (idx > k) { k = idx; seen = new Set(seen); seen.add(idx); changed = true; }
    else if (idx >= 0 && !seen.has(idx)) { seen = new Set(seen); seen.add(idx); changed = true; }   // e.g. repeated k=6 lines

    var next = sig;
    function flag(name) { if (!next[name]) { if (next === sig) next = Object.assign({}, sig); next[name] = true; changed = true; } }
    if (/Extraction failed\b/.test(s)) flag('extractFailed');
    if (/Processing failed:/.test(s)) flag('processFailed');
    if (/^\[SPEC\] (CRITICAL|HIGH):/.test(s)) flag('resolveWarn');
    if (/Overview analysis unavailable|Could not classify view|No FRONT view found/.test(s)) flag('extractWarn');
    if (/^\[(launch|reader) error\]/.test(s)) flag('processFailed');

    if (!changed) return track;
    return { kind: track.kind, k: k, seen: seen, signals: next, done: track.done, final: track.final, tel: track.tel };
  }

  function stageIndexOfK(kind, k) {
    var st = stagesFor(kind);
    for (var i = 0; i < st.length; i++) if (st[i].ks.indexOf(k) !== -1) return i;
    return -1;
  }
  function anySeen(track, ks) { for (var i = 0; i < ks.length; i++) if (track.seen.has(ks[i])) return true; return false; }
  /** Highest marker seen. Every k 0-7 is a genuine work unit in this scheme (no trailing
      "Exporting"/"Done" markers to exclude, unlike the v1 CLI). */
  function lastWorkK(track) {
    var best = -1;
    track.seen.forEach(function (v) { if (v > best) best = v; });
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
      else if (S.ks.indexOf(k) !== -1) r = { state: 'running', detail: '' };
      else {                                              // k > max
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

  /** facts: {exit, cancelled, summary, payload, startedAt (epoch seconds)}. Returns a new track.
      payload.categories.ir_report (present/gate1/sw_ok/questions/error -- see server/app.py
      _categorize_output) is this pipeline's own ground truth for Build Plan and Verification;
      it is used in preference to the v1-only "summary" (multiview_summary.csv), which the IR
      path never writes. */
  function finalize(track, facts) {
    var f = facts || {}, st = stagesFor(track.kind), states = liveStates(track);
    var exit = f.exit, summary = f.summary || null, payload = f.payload || null;
    var cats = (payload && payload.categories) || {};
    var ir = cats.ir_report && cats.ir_report.present ? cats.ir_report : null;
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
      var failIdx = runningIdx >= 0 ? runningIdx : (track.k < 0 ? 0 : (firstPending >= 0 && track.k < unitsFor(track.kind) ? firstPending : -1));
      if (track.kind === 'demo' && failIdx >= 0 && states[failIdx].state === 'skipped') failIdx = -1;
      // The IR report, when present, names which stage actually failed (gate1 vs. the native
      // build), which is more precise than "whichever stage was still running at exit".
      var irFailDetail = null;
      if (track.kind !== 'demo' && ir) {
        if (ir.error || ir.gate1 === 'REJECT' || ir.gate1 === 'NO PLAN') {
          failIdx = stageIndexOfK('part', 3);
          irFailDetail = ir.error || ('Gate 1: ' + ir.gate1);
        } else if (ir.sw_ok === false) {
          failIdx = stageIndexOfK('part', 7);
          irFailDetail = 'SolidWorks did not verify the build (bounding box or volume mismatch)';
        }
      }
      if (failIdx >= 0) {
        decided = true;
        states[failIdx] = { state: 'failed', detail: irFailDetail || ('Exited with code ' + exit) };
        setAfter(failIdx + 1, 'skipped', 'Not reached');
      }
    }

    if (!decided) {
      for (i = 0; i < states.length; i++) {
        if (states[i].state === 'running') states[i] = { state: 'succeeded', detail: '' };
      }
      if (track.kind === 'demo') {
        setAfter(0, 'skipped', 'Not reached');
      } else if (ir) {
        // This pipeline's own report is ground truth: gate1 for Build Plan, sw_ok/bbox/volume
        // for Verification, and unresolved features surfaced as a warning rather than a
        // failure (CLAUDE.md: never guessed -- a question is not a defect).
        var flagged = !!(ir.questions && ir.questions.length);
        if (states[2].state !== 'failed') {
          states[2] = flagged ? { state: 'warning', detail: ir.questions.length + ' open question' + (ir.questions.length === 1 ? '' : 's') }
                               : { state: 'succeeded', detail: '' };
        }
        var fresh = isFresh(payload, f.startedAt);
        var src = payload ? payload.stl_source : null;
        if (states[3].state !== 'failed') {
          if (track.seen.has(5)) {
            states[3] = { state: 'succeeded', detail: '' };
          } else if (states[3].state !== 'skipped') {
            states[3] = { state: 'skipped', detail: '' };
          }
        }
        if (states[4].state !== 'failed') {
          if (ir.sw_ok === true) states[4] = { state: 'succeeded', detail: '' };
          else if (ir.sw_ok === false) states[4] = { state: 'failed', detail: 'SolidWorks did not verify the build' };
          else if (src === 'prevalidation' && fresh) {
            states[4] = { state: 'warning', detail: 'SolidWorks was not used for this run; CadQuery pre-validation model only' };
          } else {
            states[4] = { state: 'skipped', detail: 'Not reached' };
          }
        }
      } else {
        // No ir_report at all: this was not an IR run (or it crashed before one was written).
        // Fall back to whatever the process reported directly.
        var wk = lastWorkK(track);
        var detailOf = summary && summary.detail ? String(summary.detail) : '';
        if (track.signals.extractFailed || (status === 'ERROR' && wk <= 1)) {
          states[0] = { state: 'failed', detail: detailOf || 'Extraction failed' };
        } else if (status === 'ERROR') {
          var ei = stageIndexOfK('part', wk);
          if (ei >= 0) states[ei] = { state: 'failed', detail: detailOf || 'Processing failed' };
        }
        if (states[2].state !== 'failed' && track.seen.has(3)) {
          if (status === 'BLOCKED') states[2] = { state: 'failed', detail: detailOf || 'Blocked by the verification gate' };
          else if (states[2].state !== 'failed' && summary && (num(summary.n_needs_review) > 0 || num(summary.n_skipped) > 0)) {
            states[2] = { state: 'warning', detail: num(summary.n_needs_review) + ' need review, ' + num(summary.n_skipped) + ' skipped' };
          }
        }
        var fresh2 = isFresh(payload, f.startedAt);
        var src2 = payload ? payload.stl_source : null;
        if (states[3].state !== 'failed') {
          if (track.seen.has(5)) {
            if (!payload) states[3] = { state: 'warning', detail: 'Output files could not be checked' };
            else if (src2 === 'solidworks' && fresh2) states[3] = { state: 'succeeded', detail: '' };
            else states[3] = { state: 'failed', detail: /sldprt build failed/.test(detailOf) ? detailOf : 'SolidWorks produced no new model' };
          } else if (src2 === 'prevalidation' && fresh2) {
            states[3] = { state: 'warning', detail: 'SolidWorks not available on this machine; CadQuery pre-validation model only' };
          } else if (states[3].state !== 'skipped') {
            states[3] = { state: 'skipped', detail: '' };
          }
        }
        if (states[4].state !== 'failed') {
          if (!track.seen.has(7)) states[4] = { state: 'skipped', detail: 'Not reached' };
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

    return { kind: track.kind, k: track.k, seen: track.seen, signals: track.signals, done: true, tel: track.tel,
             final: { exit: exit === undefined ? null : exit, cancelled: !!f.cancelled, stages: states } };
  }

  /** Integer 0-100, or null (indeterminate / removed on failure and cancel). */
  function percent(track) {
    if (track.tel) return telPercent(track.tel);         // backend-owned; failed/cancelled keep the last truthful value
    if (track.final) {
      if (track.final.cancelled) return null;
      return track.final.exit === 0 || track.final.exit === 8 ? 100 : null;
    }
    if (track.k < 0) return null;
    return Math.min(99, Math.floor(100 * track.k / unitsFor(track.kind)));
  }

  function subLabels(kind) {
    return kind === 'demo' ? DEMO_STEPS.map(function (d) { return { k: d.k, label: d.label }; })
      : MARKERS.map(function (m) { return { k: m.k, label: m.label }; });
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
    var pct = percent(track), tel = track.tel, pp = tel && tel.progress ? tel.progress : null;
    var progress = tel
      ? { source: 'structured', percent: pp && typeof pp.percent === 'number' ? (pct === 100 ? 100 : pp.percent) : null,
          indeterminate: !(pp && typeof pp.percent === 'number'), phase: pp ? pp.phase || null : null,
          operation: pp ? pp.operation || null : null, label: pp ? pp.label || '' : '',
          completed: pp && typeof pp.completed_units === 'number' ? pp.completed_units : null,
          total: pp && typeof pp.total_units === 'number' ? pp.total_units : null,
          unit: pp ? pp.unit || null : null, terminal: tel.terminal || null, run_id: tel.run_id, attempt: tel.attempt }
      : { source: 'legacy_markers', percent: pct, indeterminate: pct === null && !track.final, phase: null,
          operation: null, label: '', completed: null, total: null, unit: null, terminal: null, run_id: null, attempt: null };
    return { stages: stages, currentIndex: currentIndex, caption: caption, progress: progress,
             stageNumber: currentIndex >= 0 ? currentIndex + 1 : 0, stageCount: st.length, percent: pct };
  }

  return { MARKERS: MARKERS, PART_STAGES: PART_STAGES, DEMO_STAGES: DEMO_STAGES, parseMarker: parseMarker,
           initial: initial, reduce: reduce, finalize: finalize, applyTelemetry: applyTelemetry, parseEvent: parseEvent, percent: percent, view: view };
});
