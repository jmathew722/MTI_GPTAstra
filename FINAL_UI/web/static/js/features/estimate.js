/* Run Pipeline estimate area (Workspace > Pipeline Actions, directly under the run controls).
   Before a run: estimated time and cost from GET /api/estimate (one backend source of truth, seconds + USD).
   During a run: elapsed time, remaining time when the history is reliable, cost measured so far.
   After a run: the ACTUAL elapsed time and measured cost, kept visibly separate from the estimate and persisted
   by the server (GET /api/parts/.../last-run), so a refresh or reconnect never resets or double-counts them.
   Unknown stays unknown: no history shows "insufficient history", no price shows "unavailable", never $0.00.
   Stale asynchronous responses are dropped by a sequence number. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var $ = function (id) { return document.getElementById(id); };
  var V, seq = 0, lastRunSeq = 0, timer = null;
  var single = null, batch = null, err = '', last = null, lastKey = '';

  function S() { return McA.store.get(); }
  function running(s) { return s.run && (s.run.state === 'running' || s.run.state === 'queued'); }
  function batchNames(s) { return (s.parts.list || []).map(function (p) { return p.name; }); }
  function selected(s) { var sl = s.parts.selected; return sl && sl.part ? sl : null; }

  /* ── data ─────────────────────────────────────────────────────────────── */
  function refresh() {
    var s = S(), sl = selected(s), sid = s.session && s.session.id;
    var my = ++seq;
    if (!sid || !s.server.reachable) { single = batch = null; err = s.server.reachable === false ? 'Server unreachable.' : ''; render(); return; }
    var names = batchNames(s);
    var jobs = [McA.api.estimate(sid, sl ? [sl.part] : [])];
    if (names.length > 1) jobs.push(McA.api.estimate(sid, names));
    Promise.all(jobs).then(function (r) {
      if (my !== seq) return;                       // a newer selection/config superseded this answer
      single = r[0]; batch = r[1] || null; err = ''; render();
    }, function (e) {
      if (my !== seq) return;
      single = batch = null; err = (e && (e.detail || e.message)) || 'The estimate could not be loaded.'; render();
    });
    render();
  }
  function refreshLast() {
    var s = S(), sl = selected(s), sid = s.session && s.session.id;
    var key = sl && sid ? sid + '|' + sl.part : '';
    var my = ++lastRunSeq;
    if (!key) { last = null; lastKey = ''; render(); return; }
    McA.api.lastRun(sid, sl.part).then(function (r) { if (my === lastRunSeq) { last = r; lastKey = key; render(); } },
      function () { if (my === lastRunSeq) { last = null; lastKey = key; render(); } });
  }

  /* ── render ───────────────────────────────────────────────────────────── */
  function set(id, text, hide) { var e = $(id); if (!e) return; e.textContent = text || ''; if (hide !== undefined) e.hidden = !!hide; }
  function render() {
    var box = $('run-estimate'); if (!box || !V) return;
    var s = S(), sl = selected(s), isRun = running(s);
    var d = V.describe(sl ? single : (single && single.inputs ? single : { inputs: 0 }), err);
    box.setAttribute('data-state', d.state);
    set('est-time', d.time);
    set('est-cost', d.cost);
    var detail = d.detail;
    if (batch && batch.inputs > 1) {
      var bd = V.describe(batch);
      var bt = bd.time.replace('Estimated time: ', ''), bc = bd.cost.replace('Estimated cost: ', '');
      detail += (detail ? ' · ' : '') + 'Run All Parts (' + batch.inputs + '): ' + bt + ' · ' + bc + ', one part at a time';
    }
    var rc = $('record-run');
    if (rc && rc.checked) detail += (detail ? ' · ' : '') + 'Recording adds a short pause after each feature.';
    set('est-detail', detail);
    var live = $('est-live'), a = V.actual(s.run, lastKey === (sl ? s.session.id + '|' + sl.part : '') ? last : null, Date.now());
    if (isRun && a && a.kind === 'live') {
      var rem = V.remaining(single, Date.now() - s.run.startedAt);
      var ck = McA.selectors && McA.selectors.costKey ? McA.selectors.costKey(s) : null;
      var cost = ck && ck.runText ? ck.runText : '';
      var txt = 'Running: ' + a.elapsed + ' elapsed' + (rem ? ' · ' + rem.text : '') + ' · cost so far ' + (cost || 'unavailable');
      if (s.batch && s.batch.active) txt += ' · part ' + (s.batch.index + 1) + ' of ' + s.batch.queue.length;
      set('est-live', txt, false); live.setAttribute('data-kind', 'live');
    } else if (a && (a.kind === 'final' || a.kind === 'unknown') && a.elapsed) {
      var ck2 = McA.selectors && McA.selectors.costKey ? McA.selectors.costKey(s) : null;
      var costTxt = a.cost || (a.kind === 'final' && ck2 && ck2.state !== 'empty' && ck2.status !== 'unpriced' && ck2.runText ? ck2.runText : '');
      var costPart = costTxt ? 'cost ' + costTxt + ' (measured)' : (a.costStatus === 'none' ? 'cost not recorded' : 'cost unavailable');
      set('est-live', 'Last run' + (a.state ? ' (' + String(a.state).replace(/_/g, ' ') + ')' : '') + ': actual ' + a.elapsed + ' · ' + costPart, false);
      live.setAttribute('data-kind', 'final');
    } else set('est-live', '', true);
    if (isRun) startTimer(); else stopTimer();
  }
  function startTimer() { if (!timer) timer = setInterval(render, 1000); }
  function stopTimer() { if (timer) { clearInterval(timer); timer = null; } }

  McA.estimate = {
    refresh: refresh,
    init: function () {
      V = McA.estimateview;
      if (!$('run-estimate') || !V) return;
      var st = McA.store;
      st.subscribe(function (s) { return s.parts.selected; }, function () { refresh(); refreshLast(); });
      st.subscribe(function (s) { return s.parts.list; }, refresh);
      st.subscribe(function (s) { return s.session && s.session.id; }, function () { refresh(); refreshLast(); });
      st.subscribe(function (s) { return s.server.reachable; }, refresh);
      st.subscribe(function (s) { return s.server.model; }, refresh);                 // a model change can change cost
      st.subscribe(function (s) { return s.run.state; }, function (state) {
        render();
        if (state === 'succeeded' || state === 'succeeded_with_warnings' || state === 'failed' || state === 'cancelled') {
          setTimeout(function () { refreshLast(); refresh(); }, 1200);                // let the server flush the run's final events/ledger
        }
      });
      st.subscribe(function (s) { return s.outputs; }, render);                        // measured cost arrives with the outputs payload
      ['no-cache', 'record-run'].forEach(function (id) { var e = $(id); if (e) e.addEventListener('change', function () { refresh(); }); });
      refresh(); refreshLast();
    },
  };
})();
