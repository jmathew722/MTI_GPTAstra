/* McA.registry: PURE results registry (ARCH 11). The single ordered list used by the Results page, the
   drawer and the tests. Entries hold data only: id, group, label, emptyText, tools, keys, source(), status().
   Rendering functions are added by ui/results.js (entry.render). Every `categories` key from
   GET .../outputs maps to exactly one section; coverage() proves it. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(root);
  else (root.McA = root.McA || {}).registry = factory(root);
})(typeof self !== 'undefined' ? self : this, function (root) {
  'use strict';

  function logparse() {
    if (typeof module === 'object' && module.exports) { try { return require('./logparse.js'); } catch (e) { return null; } }
    return (root.McA || {}).logparse || null;
  }

  /* Every key of payload.categories as produced by app.py _categorize_output (14 keys). */
  var CATEGORY_KEYS = ['extraction', 'resolved', 'build_plan', 'verification', 'model_check', 'review', 'usage',
                       'macros', 'sldprt', 'stl', 'must_meet', 'overview_analysis', 'console', 'files', 'telemetry'];

  var GROUPS = [
    { id: 'overview', label: 'Overview' },
    { id: 'extraction', label: 'Extraction' },
    { id: 'build', label: 'Build & Verification' },
    { id: 'files', label: 'Automation & Files' },
    { id: 'diagnostics', label: 'Diagnostics' },
    { id: 'scoring', label: 'Scoring Rubric' }
  ];

  function cats(payload) { return (payload && payload.categories) || {}; }
  function cat(payload, key) { return cats(payload)[key] || {}; }
  function present(key) { return function (p) { return !!cat(p, key).present; }; }
  function srcKey(key) { return function (p) { return cat(p, key); }; }
  function lines(extra) { return (extra && extra.lines) || []; }

  /* extra: optional {lines: run.lines, runState, verdict, summary}. */
  var SECTIONS = [
    { id: 'overview', group: 'overview', label: 'Overview', keys: [],
      emptyText: 'Run the pipeline to see a summary.', tools: [],
      source: function (p, extra) {
        var c = cats(p), flags = (c.review && c.review.items) || [];
        var oa = (c.overview_analysis && c.overview_analysis.data) || null;
        return {
          runState: extra && extra.runState || null, verdict: extra && extra.verdict || null,
          summary: extra && extra.summary || null,
          built: { sldprt: !!(c.sldprt && c.sldprt.present), stl: c.stl || { present: false },
                   macros: (c.macros && c.macros.files) ? c.macros.files.length : 0 },
          mustMeet: c.must_meet || { present: false },
          attention: flags.filter(function (f) { return f && (f.severity === 'CRITICAL' || f.severity === 'HIGH'); }),
          conflicts: (oa && oa.cross_view_conflicts) || []
        };
      },
      status: function (p, extra) {
        var c = cats(p);
        return (p && (p.has_any || (c.stl && c.stl.present) || (c.sldprt && c.sldprt.present))) ||
               (extra && extra.runState && extra.runState !== 'idle') ? 'present' : 'absent';
      } },
    { id: 'extraction', group: 'extraction', label: 'Extraction', keys: ['extraction'],
      emptyText: 'No extraction yet.', tools: ['search', 'treeRaw', 'copy', 'download'],
      source: srcKey('extraction'), status: function (p) { return present('extraction')(p) ? 'present' : 'absent'; } },
    { id: 'resolved', group: 'extraction', label: 'Resolved extraction', keys: ['resolved'],
      emptyText: 'No resolved extraction. Resolution did not run or the part was not run.',
      tools: ['search', 'treeRaw', 'copy', 'download'],
      source: srcKey('resolved'), status: function (p) { return present('resolved')(p) ? 'present' : 'absent'; } },
    { id: 'overview_analysis', group: 'extraction', label: 'Overview analysis', keys: ['overview_analysis'],
      emptyText: 'No overview analysis for this run.', tools: ['raw', 'copy'],
      source: srcKey('overview_analysis'), status: function (p) { return present('overview_analysis')(p) ? 'present' : 'absent'; } },
    { id: 'build_plan', group: 'build', label: 'Build plan', keys: ['build_plan'],
      emptyText: 'No build plan. The part was blocked before planning or has not run.',
      tools: ['search', 'listRaw', 'copy', 'download'],
      source: srcKey('build_plan'), status: function (p) { return present('build_plan')(p) ? 'present' : 'absent'; } },
    { id: 'verification', group: 'build', label: 'Verification', keys: ['verification'],
      emptyText: 'No verification report yet.', tools: ['copy', 'download'],
      source: function (p) { return { report: cat(p, 'verification') }; },
      status: function (p) { return present('verification')(p) ? 'present' : 'absent'; } },
    { id: 'flags', group: 'build', label: 'Engineering flags', keys: ['review'],
      emptyText: 'No engineering review yet.',
      emptyTextFor: function (p) {
        var r = cat(p, 'review');
        return r.present ? 'No assumptions or manual steps were recorded.' : 'No engineering review yet.';
      },
      tools: ['filter', 'raw', 'copy'],
      source: srcKey('review'),
      status: function (p) { var r = cat(p, 'review'); return r.items && r.items.length ? 'present' : 'absent'; } },
    { id: 'model_check', group: 'build', label: 'Model check', keys: ['model_check'],
      emptyText: 'Model check requires Windows and SolidWorks; it was not produced for this run.',
      tools: ['copy', 'download'],
      source: srcKey('model_check'), status: function (p) { return present('model_check')(p) ? 'present' : 'absent'; } },
    { id: 'must_meet', group: 'build', label: 'Must-Meet Specs', keys: ['must_meet'],
      emptyText: 'No must-meet specification saved for this part yet.',
      tools: [],
      source: srcKey('must_meet'), status: function (p) { return present('must_meet')(p) ? 'present' : 'absent'; } },
    { id: 'corrections', group: 'build', label: 'Corrections', keys: [],
      emptyText: 'Select a part to describe a correction.',
      tools: [],
      source: function () { return {}; }, status: function () { return 'present'; } },
    { id: 'macros', group: 'files', label: 'Macros', keys: ['macros'],
      emptyText: 'No macros generated yet.', tools: ['copy', 'download'],
      source: srcKey('macros'), status: function (p) { return present('macros')(p) ? 'present' : 'absent'; } },
    { id: 'files', group: 'files', label: 'Files', keys: ['files', 'sldprt', 'stl'],
      emptyText: 'No output files yet.', tools: ['download', 'zip'],
      source: function (p) {
        var c = cats(p);
        return { list: (c.files && c.files.list) || [], sldprt: !!(c.sldprt && c.sldprt.present), stl: c.stl || { present: false },
                 macroCount: (c.macros && c.macros.files) ? c.macros.files.length : 0,
                 delivered: p ? p.delivered || null : null, deliveredDownloads: p ? p.delivered_downloads || null : null };
      },
      status: function (p) {
        var c = cats(p);
        return (c.files && c.files.list && c.files.list.length) || (c.sldprt && c.sldprt.present) || (c.stl && c.stl.present) ? 'present' : 'absent';
      } },
    { id: 'cost', group: 'diagnostics', label: 'Cost', keys: ['usage', 'telemetry'],
      emptyText: 'No token usage recorded. Demo runs make no API calls.', tools: ['raw', 'copy'],
      source: srcKey('usage'), status: function (p) { return present('usage')(p) ? 'present' : 'absent'; } },
    { id: 'console', group: 'diagnostics', label: 'Console', keys: ['console'],
      emptyText: 'No console output for this run.', tools: ['filter', 'search', 'copy', 'autoscroll', 'download'],
      source: function (p, extra) {
        var live = lines(extra);
        if (live.length) return { source: 'live', lines: live, text: null };
        var c = cat(p, 'console');
        return { source: c.present ? 'file' : 'none', lines: null, text: c.text === undefined ? null : c.text, name: c.name || null,
                 tooLarge: !!(c.present && c.text === null) };
      },
      status: function (p, extra) { return lines(extra).length || present('console')(p) ? 'present' : 'absent'; } },
    { id: 'events', group: 'diagnostics', label: 'Events', keys: [],
      emptyText: 'No events for this run.', tools: ['filter', 'copy'],
      source: function (p, extra) {
        var lp = logparse(), ls = lines(extra);
        if (!ls.length) {
          var c = cat(p, 'console');
          if (c.present && typeof c.text === 'string') ls = c.text.split('\n');
        }
        return { events: lp ? lp.events(ls, { exit: extra && typeof extra.exit === 'number' ? extra.exit : undefined }) : [] };
      },
      status: function (p, extra) {
        var s = SECTIONS_BY_ID.events.source(p, extra);
        return s.events.length ? 'present' : 'absent';
      } },
    /* Fetched separately (GET .../scoring), not part of the outputs payload: a geometry score
       needs a signed answer key (bench.score; only exists for official benchmark parts) and
       the MTI practices checklist is derived from ir_report.json's real mti_review findings.
       keys:[] because no payload.categories key backs it -- see server/app.py part_scoring. */
    { id: 'scoring_rubric', group: 'scoring', label: 'Scoring Rubric', keys: [],
      emptyText: 'Not scored.', tools: [],
      source: function () { return {}; }, status: function () { return 'present'; } }
  ];
  var SECTIONS_BY_ID = {};
  SECTIONS.forEach(function (s) { SECTIONS_BY_ID[s.id] = s; });

  function get(id) { return SECTIONS_BY_ID[id] || null; }
  function inGroup(groupId) { return SECTIONS.filter(function (s) { return s.group === groupId; }); }
  function emptyText(id, payload) {
    var s = SECTIONS_BY_ID[id];
    if (!s) return '';
    return s.emptyTextFor ? s.emptyTextFor(payload) : s.emptyText;
  }

  /** Which section owns each `categories` key. {map:{key:sectionId}, unmapped:[], duplicated:[]} */
  function coverage(keys) {
    var all = keys || CATEGORY_KEYS, map = {}, dup = [];
    SECTIONS.forEach(function (s) {
      s.keys.forEach(function (k) { if (k in map) dup.push(k); else map[k] = s.id; });
    });
    return { map: map, unmapped: all.filter(function (k) { return !(k in map); }),
             duplicated: dup, unknown: Object.keys(map).filter(function (k) { return all.indexOf(k) === -1; }) };
  }

  /** categories.<key>.text === null means the file exceeded the inline cap (400 KB). */
  function isTooLarge(category) { return !!(category && category.present && category.text === null); }

  /** Find the entry of payload.categories.files.list for a basename (or a relative path).
      Exact match first, then any entry whose path ends with it (nested folders), shortest path wins.
      Returns {name,size} or null. */
  function resolveFile(payload, basename) {
    var list = (cats(payload).files || {}).list || [];
    if (!basename) return null;
    var want = String(basename).replace(/\\/g, '/'), hits = [];
    for (var i = 0; i < list.length; i++) {
      var nm = String(list[i].name).replace(/\\/g, '/');
      if (nm === want) return list[i];
      if (nm.length > want.length && nm.slice(-(want.length + 1)) === '/' + want) hits.push(list[i]);
    }
    hits.sort(function (a, b) { return a.name.length - b.name.length; });
    return hits[0] || null;
  }

  /** Relative path to download for a section's file (null when none). */
  function downloadRel(payload, id) {
    var key = { extraction: 'extraction', resolved: 'resolved', build_plan: 'build_plan',
                verification: 'verification', model_check: 'model_check', console: 'console' }[id];
    if (!key) return null;
    var c = cat(payload, key);
    var f = c.present && c.name ? resolveFile(payload, c.name) : null;
    return f ? f.name : null;
  }

  /** Files of a given extension from the files list (e.g. '.vba', '.sldprt'). */
  function filesWithExt(payload, ext) {
    var e = String(ext).toLowerCase();
    return (((cats(payload).files || {}).list) || []).filter(function (f) { return String(f.name).toLowerCase().slice(-e.length) === e; });
  }

  return { CATEGORY_KEYS: CATEGORY_KEYS, GROUPS: GROUPS, sections: SECTIONS, get: get, inGroup: inGroup,
           emptyText: emptyText, coverage: coverage, isTooLarge: isTooLarge, resolveFile: resolveFile,
           downloadRel: downloadRel, filesWithExt: filesWithExt };
});
