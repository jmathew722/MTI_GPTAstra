/* Tracker (ARCH 8.3): five stages, run button, ring percent, caption, batch aggregate.
   Reads store state only; the run lifecycle is features/run.js. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var $ = function (id) { return document.getElementById(id); };
  var el = {}, clock = null, lastAnnounce = '', lastView = null;
  var SR = { pending: 'Pending', running: 'Running', succeeded: 'Done', warning: 'Done with warnings', failed: 'Failed', skipped: 'Skipped' };
  var STATES = Object.keys(SR);
  var RUN_LABEL = { idle: 'Not started', queued: 'Queued', running: 'Running', succeeded: 'Complete', succeeded_with_warnings: 'Complete with warnings', failed: 'Failed', cancelled: 'Cancelled' };

  /* The run the tracker shows: the demo run when it is the current outputs context, or the run of the selected part. */
  function effective(s) {
    var run = s.run, sl = s.parts.selected, ctx = s.outputs.ctx;
    if (!run || run.state === 'idle' || !run.track) return null;
    if (run.kind === 'demo') return (ctx && ctx.kind === 'run' && ctx.runId === run.id) || McA.selectors.isRunning(s) ? run : null;
    if (sl && run.session === sl.session && run.part === sl.part) return run;
    return null;
  }
  function ringSVG(pct, state) {
    var NS = 'http://www.w3.org/2000/svg', C = 2 * Math.PI * 15;
    var svg = el.ring; svg.replaceChildren();
    function c(cls) { var n = document.createElementNS(NS, 'circle'); n.setAttribute('cx', '18'); n.setAttribute('cy', '18'); n.setAttribute('r', '15'); n.setAttribute('class', cls); return n; }
    svg.appendChild(c('ring-bg'));
    var fg = c('ring-fg'); svg.appendChild(fg);
    if (typeof pct === 'number') { fg.setAttribute('stroke-dasharray', (C * pct / 100).toFixed(2) + ' ' + C.toFixed(2)); fg.setAttribute('transform', 'rotate(-90 18 18)'); svg.classList.remove('ring-ind'); }
    else if (state === 'running' || state === 'queued') { fg.setAttribute('stroke-dasharray', (C * 0.25).toFixed(2) + ' ' + C.toFixed(2)); svg.classList.add('ring-ind'); }
    else { fg.setAttribute('stroke-dasharray', '0 ' + C.toFixed(2)); svg.classList.remove('ring-ind'); }
  }
  function tipFor(st) {
    var h = McA.dom.h;
    var ul = h('ul', { class: 'trk-tip-list' }, st.substeps.map(function (x) {
      return h('li', { 'data-s': STATES.indexOf(x.state) >= 0 ? x.state : 'pending' }, h('span', { class: 'trk-tip-s', text: SR[x.state] || x.state }), ' ' + x.label);
    }));
    return [h('strong', { text: st.label + ': ' + (SR[st.state] || st.state) }), st.detail ? h('p', { class: 'trk-tip-d', text: st.detail }) : null,
      st.substeps.length ? ul : h('p', { class: 'trk-tip-d', text: 'No sub-steps.' })];
  }
  function render() {
    var s = McA.store.get(), run = effective(s), running = McA.selectors.isRunning(s);
    /* run button */
    var reason = McA.selectors.runDisabledReason(s), note = McA.selectors.runNote(s);
    var lbl = el.run.querySelector('.run-lbl');
    el.run.setAttribute('aria-disabled', reason ? 'true' : 'false');
    el.run.classList.toggle('is-running', running);
    lbl.textContent = running ? 'Running…' : 'Run Pipeline';
    var ic = el.run.querySelector('svg');
    if (ic) { ic.style.display = running ? 'none' : ''; }
    el.spin.hidden = !running;
    el.reason.textContent = reason || note || '';
    el.reason.classList.toggle('is-warn', !reason && !!note);
    el.cancel.hidden = !running;
    el.cancel.disabled = !!s.run.cancelPending;
    el.cancel.textContent = s.run.cancelPending ? 'Cancelling…' : 'Cancel';

    /* steps */
    var track = run ? run.track : null;
    var v = McA.stages.view(track || McA.stages.initial(s.run && s.run.kind === 'demo' ? 'demo' : 'part'));
    if (!run) v.stages.forEach(function (st) { st.state = 'pending'; st.detail = ''; st.substeps.forEach(function (x) { x.state = 'pending'; }); });
    v.stages.forEach(function (st, i) {
      var li = el.steps[i];
      li.setAttribute('data-state', st.state);
      if (run && i === v.currentIndex && st.state === 'running') li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
      li.querySelector('.trk-state').textContent = SR[st.state];
      var tip = li.querySelector('.trk-tip'); tip.replaceChildren.apply(tip, tipFor(st).filter(Boolean));
    });
    /* meta */
    var stateLabel = run ? RUN_LABEL[run.state] : 'Not started';
    var stageTxt;
    if (!run) stageTxt = (s.run.id && running && s.run.kind === 'part') ? 'Running ' + s.run.part : 'Not started';
    else if (running) stageTxt = v.currentIndex >= 0 ? 'Stage ' + v.stageNumber + ' of ' + v.stageCount : 'Starting';
    else stageTxt = stateLabel;
    el.stage.textContent = stageTxt;
    var cap = '';
    if (run) {
      if (run.cancelPending && running) cap = 'Cancelling…';
      else if (running) cap = v.currentIndex >= 0 ? (v.stages[v.currentIndex].label + (v.caption ? ' · ' + v.caption : '')) : v.caption;
      else {
        var bad = v.stages.filter(function (x) { return x.state === 'failed' && x.detail; })[0];
        cap = bad ? bad.detail : v.caption;
      }
    } else if (running && s.run.kind === 'part') cap = 'The batch or run is working on another part.';
    el.caption.textContent = cap === stageTxt ? '' : cap;
    el.demo.hidden = !(run && run.kind === 'demo');
    /* clock */
    var ms = run ? McA.selectors.runtimeMs(s) : null;
    el.clock.textContent = ms !== null ? McA.util.fmtElapsed(ms) : '';
    el.clock.hidden = ms === null;
    if (running && !clock) clock = setInterval(function () { var ss = McA.store.get(), r = effective(ss), m = r ? McA.selectors.runtimeMs(ss) : null; el.clock.textContent = m !== null ? McA.util.fmtElapsed(m) : ''; el.clock.hidden = m === null; }, 1000);
    if (!running && clock) { clearInterval(clock); clock = null; }
    /* ring */
    var pct = run ? v.percent : null, active = !!run && (typeof pct === 'number' || !running);
    el.pct.hidden = !active;
    if (active) {
      ringSVG(pct, run.state);
      var n = el.pct.querySelector('.trk-pct-n'); n.replaceChildren();
      if (typeof pct === 'number') { n.textContent = pct + '%'; el.pct.setAttribute('aria-valuenow', String(pct)); el.pct.setAttribute('aria-valuetext', pct + ' percent'); }
      else {
        el.pct.removeAttribute('aria-valuenow');
        if (running) el.pct.setAttribute('aria-valuetext', 'Starting');
        else { var ico = run.state === 'cancelled' ? 'dash' : 'x'; n.appendChild(McA.icons.get(ico, 16)); el.pct.setAttribute('aria-valuetext', RUN_LABEL[run.state] || 'Ended'); }
      }
      el.pct.classList.toggle('is-end', !running);
      el.pct.setAttribute('data-run', run.state);
    }
    /* batch aggregate and resume offer */
    var bp = McA.selectors.batchProgress(s);
    var note2 = '';
    if (bp) note2 = bp.text;
    if (bp && bp.active && s.run.part && !run && running) note2 += ' · Batch is running ' + s.run.part;
    el.batch.textContent = note2; el.batch.hidden = !note2;
    var left = bp && !s.batch.active && !running ? McA.run.batchRemaining(s.batch) : 0;
    el.resume.hidden = !left;
    if (left) el.resume.firstChild.textContent = 'Resume batch (' + left + ' part' + (left === 1 ? '' : 's') + ' left)';
    /* announcements: one per stage change */
    if (run && running) {
      var key = run.id + ':' + v.currentIndex;
      if (key !== lastAnnounce && v.currentIndex >= 0) {
        lastAnnounce = key;
        McA.toast.announce('Stage ' + v.stageNumber + ' of ' + v.stageCount + ', ' + v.stages[v.currentIndex].label + ', running', 'info');
      }
    }
    lastView = v;
  }

  McA.tracker = {
    init: function () {
      var h = McA.dom.h;
      el.run = $('run-btn'); el.cancel = $('cancel-btn'); el.reason = $('run-reason'); el.stage = $('trk-stage'); el.caption = $('trk-caption');
      el.batch = $('trk-batch'); el.pct = $('trk-pct'); el.ring = el.pct.querySelector('svg');
      el.steps = Array.prototype.slice.call(document.querySelectorAll('.trk-step'));
      el.spin = h('span', { class: 'spin', 'aria-hidden': 'true' }); el.spin.hidden = true;
      el.run.insertBefore(el.spin, el.run.querySelector('.run-lbl'));
      el.demo = h('span', { class: 'badge-c', text: 'Demo' }); el.demo.hidden = true;
      el.clock = h('span', { class: 'trk-clock mono', 'aria-hidden': 'true' }); el.clock.hidden = true;
      el.stage.parentNode.insertBefore(el.demo, el.stage.nextSibling);
      el.caption.parentNode.insertBefore(el.clock, el.caption.nextSibling);
      el.resume = h('div', { class: 'trk-resume' }, h('button', { type: 'button', class: 'linkbtn', text: 'Resume batch', onclick: function () { McA.dom.dispatch('batch/resume'); } }),
        h('button', { type: 'button', class: 'linkbtn', text: 'Dismiss', onclick: function () { McA.dom.dispatch('batch/dismiss'); } }));
      el.resume.hidden = true;
      el.batch.parentNode.appendChild(el.resume);
      el.steps.forEach(function (li, i) {
        var id = 'trk-tip-' + i;
        li.setAttribute('tabindex', '0'); li.setAttribute('aria-describedby', id);
        li.appendChild(h('div', { class: 'trk-tip', role: 'tooltip', id: id }));
      });
      el.run.setAttribute('aria-describedby', 'run-reason');
      el.cancel.addEventListener('click', function () { McA.dom.dispatch('run/cancel'); });
      ['run', 'server', 'intake', 'batch', 'outputs'].forEach(function (k) { McA.store.subscribe(function (s) { return s[k]; }, render); });
      McA.store.subscribe(function (s) { return s.parts; }, render);
      render();
    },
    render: render
  };
})();
