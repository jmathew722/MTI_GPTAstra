/* McA.scorecache: the latest Extraction-to-Model Fidelity score of every part, shared by Projects, the Workspace header and Pipeline Results.
   One fetch of GET /api/scoring, refreshed when a run ends or the Scoring tab evaluates. Every badge is coloured by McA.grade from the ACTUAL
   number (fixed thresholds, never rounded up); a part with no score shows a neutral grey badge, never red. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var map = {}, listeners = [], seq = 0;
  var h = function () { return McA.dom.h.apply(null, arguments); };

  function emit() { listeners.forEach(function (fn) { try { fn(); } catch (e) { if (window.console) console.error(e); } }); }
  function load() {
    var my = ++seq;
    return McA.api.scoringOverview().then(function (o) {
      if (my !== seq) return;
      map = {}; (o.parts || []).forEach(function (r) { map[r.part] = r; });
      emit();
    }, function () { if (my === seq) emit(); });
  }
  function get(part) { return map[part] || null; }

  /** A graded badge for one part row: glyph + number (+ word in the title); neutral grey when there is no score. */
  function badge(row, opts) {
    opts = opts || {};
    var G = McA.grade, SV = McA.scoringview;
    var scored = row && row.state === 'scored' && G.valid(row.score);
    var g = scored ? G.gradeOf(row.score) : G.NONE;
    var st = SV.statusOf(row || { state: 'no_output' });
    var label = scored ? g.label : st.label;
    var el = h('span', { class: 'grade-badge grade-' + g.id, 'data-grade': g.id, 'data-score': scored ? String(row.score) : '', title: 'Fidelity score: ' + (scored ? G.formatFull(row.score) + ' (' + g.label + ')' : label) },
      h('span', { class: 'bp-g', 'aria-hidden': 'true', text: g.glyph }), h('span', { text: scored ? G.format(row.score) : (opts.short ? G.DASH : label) }));
    el.setAttribute('aria-label', 'Fidelity score ' + (scored ? G.format(row.score) + ' of 100, ' + g.label : label));
    return el;
  }

  /* The Workspace header chip follows the selected part. */
  function renderChip() {
    var chip = document.getElementById('hdr-score'), val = document.getElementById('hdr-score-v');
    if (!chip || !val) return;
    var sel = McA.store.get().parts.selected, row = sel ? get(sel.part) : null, G = McA.grade;
    var scored = row && row.state === 'scored' && G.valid(row.score), g = scored ? G.gradeOf(row.score) : G.NONE;
    chip.setAttribute('data-grade', g.id);
    chip.className = 'chip grade-' + g.id;
    val.replaceChildren();
    if (scored) val.append(h('span', { class: 'grade-num', text: G.format(row.score) }), h('span', { class: 'chip-g', text: ' ' + g.label }));
    else val.textContent = !sel ? G.DASH : (row ? McA.scoringview.statusOf(row).label : 'Not scored');
    chip.title = scored ? 'Fidelity score ' + G.formatFull(row.score) + ' (' + g.label + '). Open the Scoring tab for the breakdown.' : 'No fidelity score for this part yet.';
    chip.removeAttribute('aria-label');      // a link's name is its visible text (axe: label-content-name-mismatch)
  }

  McA.scorecache = {
    load: load, get: get, badge: badge, onChange: function (fn) { listeners.push(fn); },
    init: function () {
      listeners.push(renderChip);
      McA.store.subscribe(function (s) { return s.parts.selected; }, renderChip);
      McA.store.subscribe(function (s) { return s.run.state; }, function (state) { if (/^(succeeded|failed|cancelled)/.test(state)) setTimeout(load, 2500); });
      var chip = document.getElementById('hdr-score');
      if (chip) { chip.setAttribute('tabindex', '0'); chip.setAttribute('role', 'link'); chip.style.cursor = 'pointer'; chip.addEventListener('click', function () { McA.router.go('scoring'); }); chip.addEventListener('keydown', function (e) { if (e.key === 'Enter') McA.router.go('scoring'); }); }
      renderChip(); load();
    },
  };
})();
