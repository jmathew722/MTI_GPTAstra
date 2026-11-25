/* McA.run: launch, SSE monitor, outputs poll, finalize, cancel, reconnect, batch, demo,
   outputs loader, Pipeline Actions / Corrections / Export cards (ARCH 6.6, 8.5, 12).
   Side effects live here; state transitions are the store reducers. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var store, api, sel, persist, csv, runstate, logparse, registry, util;
  var $ = function (id) { return document.getElementById(id); };
  var finalized = {};          // run ids already finalized (once per id)
  var waiters = {};            // run id -> resolve fn (batch loop awaits finalize)
  var cur = null;              // active monitor {id, sse, timer, received, sseDone, doneAt, polling}
  var launching = false;
  var batchBusy = false;

  function errText(e) { return (e && (e.detail || e.message)) || String(e || 'error'); }
  function toast(t, k, o) { if (McA.toast) McA.toast.show(t, k, o); }

  /* ── Outputs loader (single owner) ─────────────────────────────────────── */
  function loadOutputs(ctx) {
    ctx = ctx || store.get().outputs.ctx;
    if (!ctx) return Promise.resolve();
    store.dispatch('outputs/loading', { ctx: ctx });
    var p = ctx.kind === 'part' ? api.partOutputs(ctx.session, ctx.part) : api.runOutputs(ctx.runId);
    return p.then(function (payload) { store.dispatch('outputs/loaded', { ctx: ctx, payload: payload }); },
      function (e) { store.dispatch('outputs/error', { ctx: ctx, error: errText(e) }); });
  }
  function reloadHistory() { return McA.boot && McA.boot.refreshHistory ? McA.boot.refreshHistory() : Promise.resolve(); }
  function reloadParts() { return McA.boot && McA.boot.refreshParts ? McA.boot.refreshParts() : Promise.resolve(); }

  /* ── Monitor ───────────────────────────────────────────────────────────── */
  function stopMonitor(m) {
    m = m || cur; if (!m) return;
    if (m.timer) clearInterval(m.timer); m.timer = null;
    if (m.sse) { try { m.sse.close(); } catch (e) { /* ignore */ } m.sse = null; }
    if (cur === m) cur = null;
  }
  function runCtxMatchesOutputs(run, ctx) {
    if (!ctx) return false;
    if (run.kind === 'demo') return ctx.kind === 'run' && ctx.runId === run.id;
    return ctx.kind === 'part' && ctx.session === run.session && ctx.part === run.part;
  }
  function payloadSig(d) {
    var c = d.categories || {};
    function len(x) { return x && x.text ? x.text.length : 0; }
    return [d.done, d.exit, d.stl_mtime, d.stl_source, c.console && len(c.console), c.extraction && len(c.extraction), c.resolved && len(c.resolved),
      c.build_plan && len(c.build_plan), c.verification && len(c.verification), c.model_check && len(c.model_check),
      c.review && c.review.items && c.review.items.length, c.review && len(c.review), c.usage && c.usage.rows && c.usage.rows.length,
      c.macros && c.macros.files && c.macros.files.length, c.files && c.files.list && c.files.list.length,
      c.overview_analysis && c.overview_analysis.present, c.must_meet && c.must_meet.results && c.must_meet.results.length,
      c.must_meet && c.must_meet.ok, c.sldprt && c.sldprt.present, c.stl && c.stl.present].join('|');
  }
  function pushOutputs(m, d) {
    var s = store.get();
    if (!runCtxMatchesOutputs(s.run, s.outputs.ctx)) return;
    var sig = payloadSig(d);
    if (m.sig === sig && s.outputs.payload) return;
    m.sig = sig;
    store.dispatch('outputs/loaded', { ctx: s.outputs.ctx, payload: d });
  }
  function poll(m) {
    if (cur !== m || m.polling || finalized[m.id]) return;
    m.polling = true;
    api.runOutputs(m.id).then(function (d) {
      m.polling = false;
      if (cur !== m || finalized[m.id]) return;
      var s = store.get();
      if (s.run.id !== m.id) return;
      pushOutputs(m, d);
      if (d.done) {
        if (!m.doneAt) m.doneAt = Date.now();
        if (!m.sseDone && Date.now() - m.doneAt < 4000) return;   // let the log replay finish first
        finalizeRun(m.id, d);
      }
    }, function (e) {
      m.polling = false;
      if (cur !== m) return;
      if (e && e.status === 404) {
        stopMonitor(m);
        persist.remove(persist.KEYS.activeRun);
        toast('The run is no longer tracked by the server (it restarted). Results on disk are shown if any.', 'warn');
        store.dispatch('run/reset');
        resolveWaiter(m.id);
        loadOutputs();
      }
      /* other errors: transient, try again on the next tick */
    });
  }
  function monitor(id) {
    stopMonitor();
    var m = { id: id, received: 0, sseDone: false, doneAt: 0, timer: null, sse: null, polling: false, sig: '' };
    cur = m;
    try {
      m.sse = api.openLog(id, {
        onLine: function (text) {
          if (cur !== m) return;
          m.received++;
          var run = store.get().run;
          if (run.id !== id || m.received <= run.lines.length) return;   // replay after reconnect
          store.dispatch('run/line', { id: id, line: text });
        },
        onDone: function () { m.sseDone = true; },
        onError: function () { m.received = 0; }
      });
    } catch (e) { m.sseDone = true; toast('Live log is unavailable: ' + errText(e), 'warn'); }
    m.timer = setInterval(function () { poll(m); }, 1200);
    poll(m);
  }
  function resolveWaiter(id) { var w = waiters[id]; if (w) { delete waiters[id]; w(); } }
  function waitFinal(id) { return new Promise(function (res) { if (finalized[id]) res(); else waiters[id] = res; }); }

  /* ── Finalize ──────────────────────────────────────────────────────────── */
  function fetchSummary(run) {
    if (run.kind !== 'part') return Promise.resolve(null);
    var url = api.partFileURL(run.session, run.part, 'multiview_summary.csv');
    return fetch(url).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
      .then(function (t) { return csv.summaryRow(t, run.part); })
      .catch(function () { return null; })
      .then(function (row) { return row || runstate.summaryFromConsole(store.get().run.lines); });
  }
  var STATE_TOAST = {
    succeeded: ['ok', 'Pipeline finished'], succeeded_with_warnings: ['warn', 'Pipeline completed with review flags'],
    failed: ['err', 'Pipeline failed'], cancelled: ['info', 'Pipeline cancelled']
  };
  function finalizeRun(id, d) {
    if (finalized[id]) return;
    finalized[id] = true;
    stopMonitor();
    var run0 = store.get().run;
    if (run0.id !== id) { resolveWaiter(id); return; }
    fetchSummary(run0).then(function (summary) {
      var run = store.get().run;
      if (run.id !== id) { resolveWaiter(id); return; }
      store.dispatch('run/finalized', { id: id, exit: d.exit, cancelled: !!d.cancelled, summary: summary, payload: d, finishedAt: Date.now() });
      persist.remove(persist.KEYS.activeRun);
      var after = store.get().run;
      var t = STATE_TOAST[after.state] || ['info', 'Pipeline finished'];
      var label = after.kind === 'demo' ? 'Demo' : (after.part || 'Part');
      var msg = t[1] + ' for ' + label + (after.state === 'failed' && typeof after.exit === 'number' ? ' (exit ' + after.exit + ')' : '') + '.';
      toast(msg, t[0], { ms: t[0] === 'err' ? 12000 : 7000 });
      /* refresh what the finished run changed */
      var jobs = [];
      if (after.kind === 'part') {
        jobs.push(reloadParts(), reloadHistory());
        var ctx = store.get().outputs.ctx;
        if (runCtxMatchesOutputs(after, ctx)) jobs.push(api.partOutputs(after.session, after.part).then(function (payload) {
          store.dispatch('outputs/loaded', { ctx: ctx, payload: payload });
        }, function () { /* keep the run payload */ }));
      }
      return Promise.all(jobs);
    }).then(function () { resolveWaiter(id); }, function () { resolveWaiter(id); });
  }

  /* ── Launch ────────────────────────────────────────────────────────────── */
  /** o: {kind:'part'|'demo', session, part, feedback, no_cache, record, sample}. Resolves {id} or null. */
  function launch(o) {
    var s = store.get();
    if (launching || sel.isRunning(s)) return Promise.resolve(null);
    launching = true;
    var kind = o.kind === 'demo' ? 'demo' : 'part';
    store.dispatch('run/queued', { kind: kind, session: o.session, part: o.part });
    var req = kind === 'demo' ? api.demo(o.sample) : api.runPart({ session: o.session, part: o.part, feedback: o.feedback, no_cache: o.no_cache, record: o.record });
    return req.then(function (res) {
      launching = false;
      if (!res || !res.id) throw new Error('The server did not return a run id.');
      var startedAt = Date.now();
      store.dispatch('run/started', { id: res.id, startedAt: startedAt });
      persist.set(persist.KEYS.activeRun, { id: res.id, kind: kind, session: o.session || null, part: o.part || null, startedAt: startedAt });
      if (kind === 'demo') store.dispatch('outputs/ctx', { ctx: { kind: 'run', runId: res.id } });
      monitor(res.id);
      return { id: res.id };
    }).catch(function (e) {
      launching = false;
      var msg = errText(e);
      store.dispatch('run/error', { error: msg });
      toast((kind === 'demo' ? 'Demo failed to start: ' : 'Run failed to start: ') + msg, 'err');
      return null;
    });
  }
  function runSelected() {
    var s = store.get(), sl = s.parts.selected;
    if (sel.runDisabledReason(s) || !sl) return Promise.resolve(null);
    var nc = $('no-cache');
    return launch({ kind: 'part', session: sl.session, part: sl.part, no_cache: !!(nc && nc.checked), record: wantRecord() });
  }
  /* "Record Pipeline Run": ticked AND recording is available on this machine (McA.recordingview.shouldRecord). */
  var recordCap = null;
  function wantRecord() {
    var rc = $('record-run');
    return !!(rc && McA.recordingview && McA.recordingview.shouldRecord(rc.checked, recordCap));
  }
  function loadRecordingCapability() {
    if (!api.recordingCapability) return;
    api.recordingCapability().then(function (c) { recordCap = c; renderActions(); },
      function () { recordCap = { available: false, reason: 'Could not check whether recording is available.' }; renderActions(); });
  }
  function cancelRun() {
    var s = store.get(), run = s.run;
    if (!run.id || !sel.isRunning(s) || run.cancelPending) return;
    store.dispatch('run/cancelPending');
    api.cancel(run.id).then(null, function (e) {
      store.update('run.cancelPending', function () { return false; });
      toast('Cancel failed: ' + errText(e), 'err');
    });
  }

  /* ── Reconnect on boot (ARCH 6.6) ──────────────────────────────────────── */
  function reconnect() {
    var rec = persist.get(persist.KEYS.activeRun, null);
    if (!rec) return;
    api.runOutputs(rec.id).then(function (d) {
      var started = typeof d.started === 'number' ? Math.round(d.started * 1000) : rec.startedAt;
      store.dispatch('run/restore', { id: rec.id, kind: rec.kind, session: rec.session, part: rec.part, startedAt: started });
      if (rec.kind === 'demo') store.dispatch('outputs/ctx', { ctx: { kind: 'run', runId: rec.id } });
      else {
        var cs = store.get().parts.selected;
        if (!cs || cs.session !== rec.session || cs.part !== rec.part) store.dispatch('parts/select', { session: rec.session, part: rec.part });
      }
      monitor(rec.id);      // done or not, the log is replayed once and the poll finalizes
      toast(d.done ? 'Reattached to a run that finished while the page was closed.' : 'Reattached to the running pipeline.', 'info');
    }, function (e) {
      if (e && e.status === 404) {
        persist.remove(persist.KEYS.activeRun);
        toast('The previous run is no longer tracked by the server (it restarted). Results on disk are shown if any.', 'warn', { ms: 9000 });
      }
      /* network error: keep the record and try again at the next boot */
    });
  }

  /* ── Batch (ARCH 12) ───────────────────────────────────────────────────── */
  function savePersistBatch(b) { persist.set(persist.KEYS.batch, { queue: b.queue, index: b.index, results: b.results }); }
  function batchRemaining(b) { return b && b.queue ? Math.max(0, b.queue.length - (b.active ? b.index + 1 : b.index)) : 0; }
  /* Any saved part is runnable: a drawing is the only input the pipeline needs. */
  function batchNames() {
    return store.get().parts.list.map(function (p) { return p.name; });
  }
  function batchReason(s) {
    if (!s.server.reachable) return 'Server unreachable.';
    if (sel.isRunning(s) || s.batch.active) return 'A run is in progress.';
    if (!s.server.live) return (s.server.keyName || 'The extraction API key') + ' is not set on the server. Run All Parts makes paid API calls.';
    if (!batchNames().length) return 'No saved parts.';
    return null;
  }
  /** Preflight for a batch: every filename with its page count, the supported-file count, and the estimated batch time and cost
      (from the same backend estimate as the Workspace). Best effort: if the estimate cannot load, the list still shows. */
  function preflightInfo(names) {
    var sid = store.get().session.id;
    if (!sid || !McA.api.estimate) return Promise.resolve(null);
    return McA.api.estimate(sid, names).catch(function () { return null; });
  }
  function confirmList(names, title, okLabel, est) {
    var h = McA.dom.h, V = McA.estimateview;
    var pages = {}; ((est && est.parts) || []).forEach(function (p) { pages[p.part] = p; });
    var d = V && est ? V.describe(est) : null;
    var bad = names.filter(function (n) { return pages[n] && pages[n].error; });
    var body = h('div', null,
      h('p', { text: names.length + ' supported input' + (names.length === 1 ? '' : 's') + '. Each part makes paid API calls and runs one at a time. A failed part does not stop the rest; a cancel or a launch failure stops the queue.' }),
      d ? h('p', { class: 'dlg-est' }, h('strong', { text: d.time }), ' \u00b7 ', h('strong', { text: d.cost }), h('br'), h('span', { class: 'reason', text: d.detail })) : null,
      bad.length ? h('p', { class: 'reason is-warn', text: bad.length + ' input' + (bad.length === 1 ? ' has' : 's have') + ' a problem and will probably fail: ' + bad.map(function (n) { return n + ' (' + pages[n].error + ')'; }).join('; ') }) : null,
      h('ul', { class: 'dlg-list' }, names.map(function (n) {
        var p = pages[n], pg = p && p.pages ? ' \u00b7 ' + p.pages + ' page' + (p.pages === 1 ? '' : 's') + (p.pages > 1 ? ' (page 1 is read; the PDF is kept whole)' : '') : '';
        return h('li', { class: 'mono' + (p && p.error ? ' is-bad' : ''), text: n + pg });
      })));
    return McA.dialog.open({ title: title, body: body, actions: [{ id: 'cancel', label: 'Cancel' }, { id: 'ok', label: okLabel, kind: 'primary', disabled: !names.length }] })
      .then(function (r) { return r === 'ok'; });
  }
  function requestBatch() {
    var s = store.get(), why = batchReason(s);
    if (why) { toast(why, 'warn'); return Promise.resolve(); }
    var names = batchNames();
    return preflightInfo(names).then(function (est) {
      return confirmList(names, 'Run ' + names.length + ' part' + (names.length === 1 ? '' : 's') + '?', 'Run ' + names.length + ' part' + (names.length === 1 ? '' : 's'), est);
    }).then(function (ok) { if (ok) return runBatch(names, 0, {}); });
  }
  /** Re-run ONLY the failed parts of the last batch; parts that succeeded keep their results and are not run again. */
  function retryFailed() {
    var s = store.get(), why = batchReason(s);
    if (why) { toast(why, 'warn'); return Promise.resolve(); }
    var results = s.batch.results || {};
    var failed = Object.keys(results).filter(function (k) { return results[k].state === 'failed'; });
    if (!failed.length) { toast('No failed parts to retry.', 'info'); return Promise.resolve(); }
    var kept = {}; Object.keys(results).forEach(function (k) { if (failed.indexOf(k) < 0) kept[k] = results[k]; });
    return preflightInfo(failed).then(function (est) {
      return confirmList(failed, 'Retry ' + failed.length + ' failed part' + (failed.length === 1 ? '' : 's') + '?', 'Retry ' + failed.length, est);
    }).then(function (ok) { if (ok) return runBatch(failed, 0, kept); });
  }
  function resumeBatch() {
    var s = store.get(), b = s.batch, why = batchReason(s);
    if (why) { toast(why, 'warn'); return Promise.resolve(); }
    var left = b.queue.slice(b.index);
    if (!left.length) return Promise.resolve();
    return confirmList(left, 'Resume batch (' + left.length + ' part' + (left.length === 1 ? '' : 's') + ' left)?', 'Resume')
      .then(function (ok) { if (ok) return runBatch(b.queue, b.index, b.results); });
  }
  function dismissBatch() {
    persist.remove(persist.KEYS.batch);
    store.set({ batch: { active: false, queue: [], index: 0, results: {} } });
  }
  function runBatch(queue, start, results0) {
    if (batchBusy) return Promise.resolve();
    batchBusy = true;
    var results = Object.assign({}, results0);
    store.set({ batch: { active: true, queue: queue.slice(), index: start, results: results } });
    var sid = store.get().session.id;
    var i = start, stoppedEarly = false;
    function step() {
      if (i >= queue.length) return Promise.resolve();
      var name = queue[i];
      store.set({ batch: Object.assign({}, store.get().batch, { index: i }) });
      savePersistBatch({ queue: queue, index: i + 1, results: results });
      store.dispatch('parts/select', { session: sid, part: name });
      var nc = $('no-cache');
      return launch({ kind: 'part', session: sid, part: name, no_cache: !!(nc && nc.checked), record: wantRecord() }).then(function (r) {
        if (!r) { stoppedEarly = true; results[name] = { state: 'failed', exit: null, error: store.get().run.error || 'Launch failed' }; return; }
        return waitFinal(r.id).then(function () {
          var run = store.get().run;
          results[name] = { state: run.state, exit: run.exit, error: null };
          store.dispatch('batch/result', { part: name, result: results[name] });
          if (run.cancelled) { stoppedEarly = true; }
        });
      }).then(function () { i++; if (!stoppedEarly) return step(); });
    }
    return step().then(function () {
      var done = !stoppedEarly && i >= queue.length;
      var nextIdx = stoppedEarly ? Math.min(queue.length, i + 1) : queue.length;
      store.set({ batch: { active: false, queue: queue.slice(), index: nextIdx, results: results } });
      if (done || nextIdx >= queue.length) persist.remove(persist.KEYS.batch); else savePersistBatch({ queue: queue, index: nextIdx, results: results });
      var okN = queue.filter(function (k) { return results[k] && (results[k].state === 'succeeded' || results[k].state === 'succeeded_with_warnings'); }).length;
      toast(done ? 'Batch finished: ' + okN + ' of ' + queue.length + ' parts completed.' : 'Batch stopped after ' + Object.keys(results).length + ' of ' + queue.length + ' parts.',
        done ? 'ok' : 'warn', { ms: 9000 });
    }).then(function () { batchBusy = false; }, function (e) { batchBusy = false; toast('Batch error: ' + errText(e), 'err'); });
  }
  function restoreBatch() {
    var b = persist.get(persist.KEYS.batch, null);
    if (!b || !b.queue.length || b.index >= b.queue.length) { persist.remove(persist.KEYS.batch); return; }
    store.set({ batch: { active: false, queue: b.queue, index: b.index, results: b.results } });
  }

  /* ── Pipeline Actions card ─────────────────────────────────────────────── */
  function setAria(btn, reason) {
    btn.removeAttribute('disabled');
    btn.setAttribute('aria-disabled', reason ? 'true' : 'false');
  }
  function renderActions() {
    var s = store.get(), running = sel.isRunning(s) || s.batch.active;
    var runAll = $('run-all-btn'), nc = $('no-cache'), why = $('runall-why'), mirror = $('cancel-mirror-btn');
    if (!runAll) return;
    var ra = batchReason(s);
    setAria(runAll, ra);
    nc.disabled = !s.server.reachable || running;
    if (McA.recording) McA.recording.applyCheckbox(recordCap, { reachable: s.server.reachable, running: running });
    why.textContent = ra || 'Run All Parts makes paid API calls, one part at a time.';
    if (mirror) mirror.hidden = !sel.isRunning(s);
    if (mirror) { mirror.disabled = !!s.run.cancelPending; mirror.textContent = s.run.cancelPending ? 'Cancelling…' : 'Cancel run'; }
  }

  /* ── Corrections card ──────────────────────────────────────────────────── */
  var corrKeyNow = null;
  function corrReason(s) {
    var sl = s.parts.selected, ta = $('feedback-text');
    if (!s.server.reachable) return 'Server unreachable.';
    if (sel.isRunning(s)) return 'A run is in progress.';
    if (!sl) return 'Select a part first.';
    if (!s.server.live) return (s.server.keyName || 'The extraction API key') + ' is not set on the server. A correction needs a live extraction.';
    var part = sel.selectedPart(s), p = s.outputs.payload;
    var hasOut = (part && part.has_output) || (p && p.has_any && s.outputs.ctx && s.outputs.ctx.kind === 'part');
    if (!hasOut) return 'This part has no output yet. Run it once, then correct it.';
    if (!ta.value.trim()) return 'Describe what to correct first.';
    return null;
  }
  function renderCorr() {
    var s = store.get(), ta = $('feedback-text');
    if (!ta) return;
    var sl = s.parts.selected, key = sl ? sl.session + '.' + sl.part : null;
    if (key !== corrKeyNow) {                       // part changed: load its draft
      corrKeyNow = key;
      ta.value = sl ? persist.corr.get(sl.session, sl.part) : '';
    }
    ta.disabled = !sl || sel.isRunning(s);
    var why = corrReason(s);
    var b = $('rerun-feedback-btn'), ed = $('open-editor-btn');
    setAria(b, why); setAria(ed, !sl ? 'x' : null);
    ed.disabled = !sl;
    $('corr-why').textContent = why || 'Re-running replaces this part\'s saved output. The current model stays visible, labeled Previous run, until the new one loads. Your text is kept if the launch fails.';
  }
  function rerunWithCorrection() {
    var s = store.get(), sl = s.parts.selected, ta = $('feedback-text');
    if (corrReason(s) || !sl) return;
    var text = ta.value.trim();
    McA.dialog.confirm('Re-run with correction?', 'This makes new API calls and replaces the saved output for "' + sl.part + '". The current outputs are kept on screen as the previous run until the new run produces its own.', 'Re-run').then(function (ok) {
      if (!ok) return;
      launch({ kind: 'part', session: sl.session, part: sl.part, feedback: text, no_cache: true, record: wantRecord() }).then(function (r) {
        if (r) { persist.corr.clear(sl.session, sl.part); ta.value = ''; renderCorr(); }
        else { persist.corr.set(sl.session, sl.part, text); }   // draft survives a failed launch
      });
    });
  }
  function openEditor() {
    var s = store.get(), sl = s.parts.selected, ta = $('feedback-text'), h = McA.dom.h;
    if (!sl) return;
    var big = h('textarea', { class: 'input-c corr-big', rows: '10', id: 'corr-big', 'aria-label': 'Correction text' });
    big.value = ta.value;
    var body = h('div', null, h('p', { class: 'hint', text: 'Describe what the model got wrong, with the value you expect (for example: "hole diameter is 3.880 mm, not 3.800 mm"). It becomes a must-meet correction line on the next run.' }), big);
    McA.dialog.open({ title: 'Correction for ' + sl.part, body: body, initial: '#corr-big', actions: [{ id: 'cancel', label: 'Discard changes' }, { id: 'save', label: 'Keep text', kind: 'primary' }] }).then(function (r) {
      if (r === 'save') { ta.value = big.value; persist.corr.set(sl.session, sl.part, ta.value); renderCorr(); }
      ta.focus();
    });
  }

  /* ── Export card ───────────────────────────────────────────────────────── */
  function exportCtx() { return store.get().outputs.ctx; }
  function fileURL(ctx, rel) { return ctx.kind === 'part' ? api.partFileURL(ctx.session, ctx.part, rel) : api.runDownloadURL(ctx.runId, rel); }
  function exportItems() {
    var s = store.get(), ctx = s.outputs.ctx, p = s.outputs.payload, out = { sldprt: [], stl: [], vba: [] };
    if (!ctx || !p) return out;
    var c = p.categories || {};
    registry.filesWithExt(p, '.sldprt').forEach(function (f) { out.sldprt.push({ name: f.name, url: fileURL(ctx, f.name) }); });
    if (c.stl && c.stl.present && c.stl.source === 'solidworks') {
      var f = registry.resolveFile(p, c.stl.name);
      if (f) out.stl.push({ name: f.name, url: fileURL(ctx, f.name) });
      else if (ctx.kind === 'part') out.stl.push({ name: (ctx.part || 'model') + '.stl', url: api.partStlURL(ctx.session, ctx.part, p.stl_mtime) });
      else out.stl.push({ name: 'model.stl', url: api.runStlURL(ctx.runId, p.stl_mtime) });
    }
    registry.filesWithExt(p, '.vba').forEach(function (f) { out.vba.push({ name: f.name, url: fileURL(ctx, f.name) }); });
    return out;
  }
  function zipAvailable(s) {
    var run = s.run, ctx = s.outputs.ctx;
    return !!(run.id && !sel.isRunning(s) && run.state !== 'idle' && runCtxMatchesOutputs(run, ctx));
  }
  function renderExport() {
    var s = store.get(), items = exportItems(), p = s.outputs.payload, ctx = s.outputs.ctx;
    if (!$('exp-sldprt')) return;
    var map = { sldprt: $('exp-sldprt'), stl: $('exp-stl'), vba: $('exp-vba') };
    var any = false;
    Object.keys(map).forEach(function (k) {
      var has = items[k].length > 0;
      map[k].disabled = !has;
      if (!has) map[k].checked = false; else any = true;
      var lbl = map[k].parentNode.querySelector('span');
      var base = { sldprt: 'SLDPRT', stl: 'STL', vba: 'VBA' }[k];
      lbl.textContent = base + (has ? (items[k].length > 1 ? ' (' + items[k].length + ' files)' : '') : ' (not produced)');
    });
    var why;
    var stlC = p && p.categories && p.categories.stl;
    if (!ctx) why = 'Select a part first.';
    else if (!p || !p.has_any && !any) why = 'Nothing to export yet.';
    else if (!any) why = 'No deliverable files are present for this output.';
    else why = 'Exports download the real files from the server.';
    if (stlC && stlC.present && stlC.source !== 'solidworks') why += ' The STL is a CadQuery pre-validation model, not a SolidWorks build, so it is not offered.';
    var checked = Object.keys(map).some(function (k) { return map[k].checked; });
    var exp = $('export-btn');
    setAria(exp, !any || !checked);
    var zipOk = zipAvailable(s), zip = $('zip-btn');
    setAria(zip, !zipOk);
    var parts = [why];
    if (any && !checked) parts.push('Tick at least one deliverable.');
    if (!zipOk) parts.push('Download all (.zip) is available only for a run started in this server session.');
    $('exp-why').textContent = parts.join(' ');
    var box = $('delivered');
    box.replaceChildren();
    if (p && (p.delivered || p.delivered_downloads)) {
      var h = McA.dom.h;
      [['Output folder', p.delivered], ['Downloads folder', p.delivered_downloads]].forEach(function (r) {
        if (!r[1]) return;
        box.append(h('div', { class: 'deliv-row' }, h('span', { class: 'cap-c', text: r[0] }),
          h('code', { class: 'mono deliv-path', text: r[1] }),
          h('button', { type: 'button', class: 'btn ghost sm', text: 'Copy path', 'aria-label': 'Copy ' + r[0] + ' path',
            onclick: function () { util.copyText(r[1]).then(function (ok) { if (McA.toast) McA.toast.announce(ok ? 'Path copied' : 'Copy failed', ok ? 'info' : 'err'); }); } })));
      });
    }
  }
  function exportSelected() {
    var items = exportItems(), list = [];
    [['sldprt', 'exp-sldprt'], ['stl', 'exp-stl'], ['vba', 'exp-vba']].forEach(function (k) {
      if ($(k[1]).checked && !$(k[1]).disabled) list = list.concat(items[k[0]]);
    });
    if (!list.length) return;
    list.forEach(function (f, i) {
      setTimeout(function () { util.downloadURL(f.url, f.name.split('/').pop()); }, i * 300);
    });
    toast('Downloading ' + list.length + ' file' + (list.length === 1 ? '' : 's') + '.', 'info');
  }

  /* ── init ──────────────────────────────────────────────────────────────── */
  function init() {
    store = McA.store; api = McA.api; sel = McA.selectors; persist = McA.persist; csv = McA.csv;
    runstate = McA.runstate; logparse = McA.logparse; registry = McA.registry; util = McA.util;

    store.register('run/launch', function (s, p) { (p && p.kind === 'demo' ? launch(p) : (p && p.part ? launch(p) : runSelected())); return null; });
    store.register('run/demo', function (s, p) { launch({ kind: 'demo', sample: p && p.sample }); return null; });
    store.register('run/cancel', function () { cancelRun(); return null; });
    store.register('batch/request', function () { requestBatch(); return null; });
    store.register('batch/retry', function () { retryFailed(); return null; });
    store.register('batch/resume', function () { resumeBatch(); return null; });
    store.register('batch/dismiss', function () { dismissBatch(); return null; });
    store.register('outputs/load', function (s, p) { loadOutputs(p && p.ctx); return null; });
    store.register('history/load', function () { reloadHistory(); return null; });

    store.subscribe(function (s) { return s.outputs.ctx; }, function (ctx) { if (ctx) loadOutputs(ctx); });

    /* Run Pipeline button + Pipeline Actions */
    var rb = $('run-btn');
    if (rb) rb.addEventListener('click', function () {
      if (rb.getAttribute('aria-disabled') === 'true') {
        var why = sel.runDisabledReason(store.get());
        if (why && McA.toast) McA.toast.announce(why, 'info');
        return;
      }
      runSelected();
    });
    var cb = $('cancel-btn'); if (cb) cb.addEventListener('click', cancelRun);
    var mirror = $('cancel-mirror-btn'); if (mirror) mirror.addEventListener('click', cancelRun);
    $('run-all-btn').addEventListener('click', function () { if (this.getAttribute('aria-disabled') !== 'true') requestBatch(); else toast(batchReason(store.get()) || '', 'warn'); });
    ['server', 'parts', 'run', 'batch'].forEach(function (k) { store.subscribe(function (s) { return s[k]; }, renderActions); });
    renderActions();
    loadRecordingCapability();

    /* Corrections: the fields themselves (#feedback-text etc.) no longer exist in static
       HTML -- they moved into Pipeline Results (ui/results.js R.corrections), which creates
       fresh elements and wires focus/click directly to McA.run.openEditor/rerunWithCorrection
       every time that tab renders. Only the store subscriptions survive here, so renderCorr()
       (guarded: it no-ops via "if (!ta) return" when the tab isn't mounted) still keeps the
       section in sync with server/parts/run/outputs changes while it IS open. */
    ['server', 'parts', 'run'].forEach(function (k) { store.subscribe(function (s) { return s[k]; }, renderCorr); });
    store.subscribe(function (s) { return s.outputs.payload; }, renderCorr);
    renderCorr();

    /* Export */
    ['exp-sldprt', 'exp-stl', 'exp-vba'].forEach(function (id) { $(id).addEventListener('change', renderExport); });
    $('export-btn').addEventListener('click', function () { if (this.getAttribute('aria-disabled') !== 'true') exportSelected(); });
    $('zip-btn').addEventListener('click', function () {
      var s = store.get();
      if (this.getAttribute('aria-disabled') === 'true' || !zipAvailable(s)) return;
      util.downloadURL(api.runZipURL(s.run.id), (s.run.part || 'demo') + '.zip');
    });
    store.subscribe(function (s) { return s.outputs; }, renderExport);
    store.subscribe(function (s) { return s.run; }, renderExport);
    renderExport();

    restoreBatch();
    reconnect();
  }

  McA.run = { init: init, launch: launch, runSelected: runSelected, cancel: cancelRun, loadOutputs: loadOutputs,
    requestBatch: requestBatch, retryFailed: retryFailed, resumeBatch: resumeBatch, dismissBatch: dismissBatch, batchRemaining: batchRemaining,
    exportItems: exportItems, zipAvailable: zipAvailable, fileURL: fileURL,
    /* Corrections now renders inside Pipeline Results (Build & Verification), not the right
       inspector. These are the same functions the old inspector card used -- same launch()
       call, same draft persistence, same confirm dialog -- exported so results.js can attach
       them to the fresh DOM it creates each time the Corrections section is shown. */
    renderCorr: renderCorr, rerunWithCorrection: rerunWithCorrection, openEditor: openEditor, corrReason: corrReason };
})();
