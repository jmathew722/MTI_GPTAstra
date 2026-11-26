/* McA.reverseview: PURE presentation rules for the 3D -> 2D page (no DOM, no network).
   The server (GET /api/reverse/*) is the single source of truth. This module only turns its payloads into words, an icon name and a tone,
   so every state has a label AND an icon (never colour alone), progress comes only from measured stage completion, and UNKNOWN is never
   shown as ZERO (no cost, no score, no runtime is ever invented). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).reverseview = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var STAGES = [
    { id: 'preflight', label: 'Preflight' }, { id: 'mesh_export', label: 'STL export' }, { id: 'inventory', label: 'Geometry inventory' },
    { id: 'planning', label: 'View planning' }, { id: 'drawing', label: 'Native drawing' }, { id: 'dimensioning', label: 'Dimensions' },
    { id: 'verification', label: 'Verification' }, { id: 'publishing', label: 'Publish' }
  ];
  var TERMINAL = ['completed', 'review_required', 'failed', 'canceled'];
  var DRAFT_NOTICE = 'PRELIMINARY / FOR REVIEW - not approved for manufacture';
  var NO_API_COST = '$0.00 API usage (CAD automation; licence/compute excluded)';
  var QA_NOTE = 'Software QA is not engineering approval.';

  /* part state -> label, icon (McA.icons name), tone (green amber red blue violet none), badge class */
  var PART_STATE = {
    queued: { label: 'Queued', icon: 'recent', tone: 'none', kind: '' },
    preflight: { label: 'Preflight', icon: 'spinner', tone: 'violet', kind: 'steel' },
    mesh_export: { label: 'Exporting STL', icon: 'spinner', tone: 'violet', kind: 'steel' },
    inventory: { label: 'Reading geometry', icon: 'spinner', tone: 'violet', kind: 'steel' },
    planning: { label: 'Planning views', icon: 'spinner', tone: 'violet', kind: 'steel' },
    drawing: { label: 'Creating drawing', icon: 'spinner', tone: 'violet', kind: 'steel' },
    dimensioning: { label: 'Dimensioning', icon: 'spinner', tone: 'violet', kind: 'steel' },
    verification: { label: 'Verifying', icon: 'spinner', tone: 'violet', kind: 'steel' },
    publishing: { label: 'Publishing', icon: 'spinner', tone: 'violet', kind: 'steel' },
    completed: { label: 'Completed', icon: 'check', tone: 'green', kind: 'ok' },
    review_required: { label: 'Review required', icon: 'warn', tone: 'amber', kind: 'warn' },
    failed: { label: 'Failed', icon: 'x', tone: 'red', kind: 'err' },
    canceled: { label: 'Canceled', icon: 'cancel', tone: 'none', kind: '' }
  };
  var UNKNOWN_STATE = { label: 'Unknown', icon: 'info', tone: 'none', kind: '' };
  var SUMMARY = {
    queued: 'Queued', running: 'Running', completed: 'Completed', review_required: 'Review required', failed: 'Failed', canceled: 'Canceled',
    completed_with_failures: 'Completed with failures'
  };

  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  function partStateInfo(state) { return PART_STATE[state] || UNKNOWN_STATE; }
  function isTerminal(state) { return TERMINAL.indexOf(state) >= 0; }
  function isActive(summary) { return summary === 'running' || summary === 'queued'; }
  function summaryLabel(s) { return SUMMARY[s] || 'Unknown'; }

  /** Tracker nodes for one part: state is one of pending running succeeded warning failed skipped. Only real stage records count;
      no time guesses. A canceled part shows its interrupted stage as skipped, not failed. */
  function stageStates(part) {
    var stages = (part && part.stages) || {};
    var canceled = part && part.state === 'canceled';
    return STAGES.map(function (s) {
      var rec = stages[s.id];
      var st = 'pending', seconds = null, warnings = [], errors = [];
      if (rec) {
        warnings = rec.warnings || []; errors = rec.errors || []; seconds = isNum(rec.seconds) ? rec.seconds : null;
        if (rec.status === 'succeeded') st = 'succeeded';
        else if (rec.status === 'warning') st = 'warning';
        else if (rec.status === 'running') st = canceled ? 'skipped' : 'running';
        else if (rec.status === 'failed') st = (canceled || errors.indexOf('canceled') >= 0) ? 'skipped' : 'failed';
        else if (rec.status === 'skipped') st = 'skipped';
      } else if (part && part.state === s.id) st = 'running';
      return { id: s.id, label: s.label, state: st, seconds: seconds, warnings: warnings, errors: errors };
    });
  }
  var STATE_WORD = { pending: 'Pending', running: 'Running', succeeded: 'Done', warning: 'Done with warnings', failed: 'Failed', skipped: 'Skipped' };
  function stateWord(s) { return STATE_WORD[s] || 'Pending'; }

  /** Caption under the tracker: the current / failing stage and the part's state. */
  function stageCaption(part) {
    if (!part) return 'No part selected';
    var nodes = stageStates(part);
    var cur = nodes.filter(function (n) { return n.state === 'running'; })[0];
    if (cur) return cur.label + ' (' + stateWord('running').toLowerCase() + ')';
    var bad = nodes.filter(function (n) { return n.state === 'failed'; })[0];
    if (bad) return bad.label + ' failed';
    if (part.state === 'queued') return 'Waiting in the queue';
    if (part.state === 'canceled') return 'Canceled';
    if (part.state === 'completed') return 'All stages done';
    if (part.state === 'review_required') return 'All stages done; review required';
    return partStateInfo(part.state).label;
  }

  /** Job progress from the server's measured stage counts. Never time-based, never above 99 until every part is terminal. */
  function percent(progress, summary) {
    if (!progress || !isNum(progress.stages_total) || progress.stages_total <= 0) return null;
    var p = Math.floor(100 * progress.stages_done / progress.stages_total);
    if (isActive(summary)) p = Math.min(p, 99);
    return Math.max(0, Math.min(100, p));
  }
  function progressText(progress, summary) {
    if (!progress || !progress.parts_total) return 'No parts';
    var pc = percent(progress, summary);
    return progress.parts_done + ' of ' + progress.parts_total + ' part' + (progress.parts_total === 1 ? '' : 's') + ' done' +
      (pc === null ? '' : ' · ' + pc + '% of stages (' + progress.stages_done + '/' + progress.stages_total + ')');
  }

  /** Header engine chip: the ACTUAL detected revision / SP from a job or the status probe; "not detected yet" otherwise. */
  function engineText(job, status) {
    var sw = (job && job.solidworks && job.solidworks.revision) ? job.solidworks : null;
    if (!sw && status && status.solidworks && status.solidworks.revision) sw = status.solidworks;
    if (sw) {
      var name = sw.is_2025 ? 'SOLIDWORKS 2025' : 'SOLIDWORKS';
      return name + ' · ' + sw.revision + (sw.service_pack ? ' ' + sw.service_pack : '');
    }
    if (status && status.solidworks && status.solidworks.detected === true) return 'SOLIDWORKS · running, revision read on first job';
    return 'SOLIDWORKS · not detected yet';
  }
  /** Measured runtime: the sum of recorded part seconds, or '' when none were measured. */
  function runtimeText(parts) {
    var secs = (parts || []).map(function (p) { return p.seconds; }).filter(isNum);
    if (!secs.length) return '';
    var t = secs.reduce(function (a, b) { return a + b; }, 0);
    var m = Math.floor(t / 60), s = Math.round(t - m * 60);
    return (m ? m + ' min ' + s + ' s' : Math.round(t * 10) / 10 + ' s') + (secs.length < parts.length ? ' (finished parts only)' : '');
  }
  /** API cost chip. Zero is stated only when the job recorded a measured zero; a missing value is never shown as $0. */
  function costText(job) {
    if (!job || !isNum(job.actual_api_cost_usd)) return 'API usage not recorded';
    if (job.actual_api_cost_usd === 0) return NO_API_COST;
    return '$' + job.actual_api_cost_usd.toFixed(2) + ' API usage (measured)';
  }

  /** The runtime estimate from GET /estimate: a range with its basis, or an honest "not enough data". */
  function estimateText(e) {
    if (!e) return 'Estimate unavailable';
    if (!e.available) return 'Not enough data to estimate' + (e.basis ? ' (' + e.basis + ')' : '');
    var f = function (s) { var m = Math.round(s / 60 * 10) / 10; return m < 1 ? Math.round(s) + ' s' : m + ' min'; };
    return 'About ' + f(e.low_s) + ' to ' + f(e.high_s) + ' (' + e.basis + ')';
  }

  /* severity */
  var SEV = {
    critical: { label: 'Critical', icon: 'x', rank: 0, kind: 'err' }, high: { label: 'High', icon: 'warn', rank: 1, kind: 'err' },
    medium: { label: 'Medium', icon: 'warn', rank: 2, kind: 'warn' }, low: { label: 'Low', icon: 'info', rank: 3, kind: '' },
    info: { label: 'Info', icon: 'info', rank: 4, kind: '' }
  };
  function severityInfo(s) { return SEV[s] || { label: 'Unrated', icon: 'info', rank: 5, kind: '' }; }
  var DISP = { open: { label: 'Open', icon: 'warn' }, accepted: { label: 'Accepted', icon: 'check' }, rejected: { label: 'Rejected', icon: 'x' } };
  function dispositionInfo(i) { return DISP[(i && i.disposition) || 'open'] || DISP.open; }
  /** Open issues first, then by severity, then by id. */
  function sortIssues(issues) {
    return (issues || []).slice().sort(function (a, b) {
      var da = (a.disposition || 'open') === 'open' ? 0 : 1, db = (b.disposition || 'open') === 'open' ? 0 : 1;
      if (da !== db) return da - db;
      var ra = severityInfo(a.severity).rank, rb = severityInfo(b.severity).rank;
      return ra !== rb ? ra - rb : String(a.id).localeCompare(String(b.id));
    });
  }
  function issueLocation(i) {
    var bits = [];
    if (i.view) bits.push('View ' + i.view);
    if (i.sheet !== null && i.sheet !== undefined && i.sheet !== '') bits.push('Sheet ' + i.sheet);
    return bits.length ? bits.join(', ') : 'Whole drawing';
  }
  function openIssueCount(issues) { return (issues || []).filter(function (i) { return (i.disposition || 'open') === 'open'; }).length; }
  function historyLine(h) {
    var verbs = { accept: 'Accepted', reject: 'Rejected', reopen: 'Reopened' };
    var at = h.at ? String(h.at).replace('T', ' ').replace(/\+00:00$|Z$/, ' UTC') : 'time not recorded';
    return (verbs[h.action] || h.action) + ' by ' + (h.user || 'unknown') + ' on ' + at + (h.note ? ': ' + h.note : '');
  }
  /** Why an accept / reject cannot be submitted yet ('' when it can). Reopen needs no note. */
  function reviewBlock(action, note) {
    if (action === 'reopen') return '';
    if (!String(note || '').trim()) return 'Enter a note to ' + action + ' this issue.';
    if (String(note).length > 2000) return 'The note is limited to 2000 characters.';
    return '';
  }

  /** Coverage diagnostic text: "N of M applicable characteristics verified" with the exclusions kept visible. */
  function coverageText(cov) {
    if (!cov || !isNum(cov.applicable)) return 'Coverage not available';
    if (cov.applicable === 0) return 'No applicable characteristics were identified';
    var ex = (cov.excluded || []).length;
    return cov.covered + ' of ' + cov.applicable + ' applicable characteristics verified' + (ex ? ' (' + ex + ' excluded, listed below)' : '');
  }
  /** Score for grade colouring: only a real number in range; null means "not available" (neutral grey). */
  function coverageScore(cov) { return cov && isNum(cov.percent) && cov.percent >= 0 && cov.percent <= 100 ? cov.percent : null; }

  /** Which of the viewer artifacts exist. Only files the server listed (it lists only files that exist). */
  function viewerSources(part) {
    var f = (part && part.files) || {};
    var stl = f['model.stl'], pdf = f['drawing.pdf'];
    var pages = 0;
    Object.keys(f).forEach(function (k) { if (/^preview\/page-\d+\.png$/.test(k)) pages++; });
    return { stl: stl ? { rel: stl.url_path, bytes: stl.bytes } : null, pdf: pdf ? { rel: pdf.url_path, bytes: pdf.bytes } : null, previews: pages,
             thumb: f['preview/page-001.png'] ? f['preview/page-001.png'].url_path : null };
  }
  function viewerKey(jobId, partId, src) { return src ? jobId + '|' + partId + '|' + src.rel + '|' + src.bytes : ''; }
  function fileLabel(name) {
    var map = { 'model.stl': 'Model (STL)', 'drawing.pdf': 'Drawing (PDF)', 'drawing.slddrw': 'Drawing (SLDDRW)', 'qa.json': 'QA report', 'manifest.json': 'Manifest',
      'inventory.json': 'Geometry inventory', 'drawing_plan.json': 'Drawing plan', 'dimension_coverage.json': 'Dimension coverage', 'pdf_check.json': 'PDF check',
      'reopen_check.json': 'Reopen check', 'stl_validation.json': 'STL validation' };
    if (map[name]) return map[name];
    var m = /^preview\/page-(\d+)\.png$/.exec(name);
    return m ? 'Preview, sheet ' + parseInt(m[1], 10) : name;
  }
  function fileList(part) {
    var f = (part && part.files) || {};
    return Object.keys(f).sort().map(function (k) { return { name: k, label: fileLabel(k), bytes: f[k].bytes, rel: f[k].url_path }; });
  }

  /** Banner for the drawing panel. Never claims approval. */
  function drawingStatus(part) {
    if (!part) return { label: 'No drawing', tone: 'none' };
    var src = viewerSources(part);
    if (!src.pdf) {
      if (part.state === 'failed') return { label: 'No drawing: the run failed', tone: 'red' };
      if (part.state === 'canceled') return { label: 'No drawing: canceled', tone: 'none' };
      return { label: part.state === 'queued' ? 'Drawing not started' : 'Drawing in progress', tone: 'violet' };
    }
    if (part.state === 'review_required') return { label: 'Draft: review required', tone: 'amber' };
    if (part.state === 'completed') return { label: part.review_status === 'resolved' ? 'Reviewed (not approved for manufacture)' : 'Draft: for review', tone: 'blue' };
    return { label: 'Draft', tone: 'violet' };
  }

  /** Why Run is disabled ('' when it can run). */
  function runBlock(o) {
    if (!o.count) return 'Choose one or more SOLIDWORKS parts (.SLDPRT) first.';
    if (!o.templateId) return 'Choose a drawing template first.';
    if (o.templateReason) return o.templateReason;
    if (o.taskRunning) return 'A template task is using the CAD worker. Wait for it to finish.';
    if (o.submitting) return 'Submitting...';
    return '';
  }
  function templateBlock(t) {
    if (!t) return 'Choose a drawing template first.';
    if (t.available === false) return 'That template is no longer on disk.';
    if (t.validation && t.validation.ok === false) return 'That template failed validation.';
    return '';
  }
  function templateStatus(t) {
    if (!t) return { label: 'Unknown', icon: 'info', tone: 'none' };
    if (t.available === false) return { label: 'Missing on disk', icon: 'x', tone: 'red' };
    if (t.validation && t.validation.ok === true) return { label: 'Validated in SOLIDWORKS', icon: 'check', tone: 'green' };
    if (t.validation && t.validation.ok === false) return { label: 'Failed validation', icon: 'x', tone: 'red' };
    if (t.source === 'stock') return { label: 'Stock template (not generated by us)', icon: 'info', tone: 'blue' };
    return { label: 'Not validated yet', icon: 'warn', tone: 'amber' };
  }
  var SOURCE_WORD = { generated: 'Generated default', uploaded: 'Uploaded', stock: 'SOLIDWORKS stock' };
  function sourceWord(s) { return SOURCE_WORD[s] || 'Template'; }

  /* ---- part picker */
  function isSldprt(name) { return /\.sldprt$/i.test(String(name || '')); }
  function depthOf(rel) { var p = String(rel || '').split('/').filter(Boolean); return Math.max(0, p.length - 1); }
  /** Files chosen from a folder: .sldprt only (case-insensitive), lock files dropped, and when not recursive only the folder's own files
      (relative path depth 1 = directly inside the chosen folder). Items: {name, rel}. */
  function filterPicked(items, recursive) {
    return (items || []).filter(function (it) {
      if (!isSldprt(it.name) || /^~\$/.test(it.name)) return false;
      return recursive || !it.rel || depthOf(it.rel) <= 1;
    });
  }
  /** Mark duplicates (same file name, case-insensitive) with dup = number of copies. */
  function markDuplicates(items) {
    var counts = {};
    items.forEach(function (i) { var k = i.name.toLowerCase(); counts[k] = (counts[k] || 0) + 1; });
    return items.map(function (i) { return Object.assign({}, i, { dup: counts[i.name.toLowerCase()] > 1 ? counts[i.name.toLowerCase()] : 0 }); });
  }
  function pickedSummary(items, rejected) {
    var n = items.length, d = items.filter(function (i) { return i.dup; }).length;
    var t = n + ' part' + (n === 1 ? '' : 's') + ' selected';
    if (d) t += ' (' + d + ' with duplicate names; each runs separately)';
    if (rejected) t += '; ' + rejected + ' non-part file' + (rejected === 1 ? '' : 's') + ' ignored';
    return t;
  }

  /** Request guard: a result is applied only if its token is still the newest one (no stale mesh or drawing after a fast switch). */
  function makeGuard() {
    var n = 0;
    return { next: function () { return ++n; }, isCurrent: function (t) { return t === n; }, current: function () { return n; } };
  }

  /** Previous-run label: a finished job that was not started in this browser session. */
  function isPreviousRun(job, sessionJobIds) {
    return !!job && (sessionJobIds || []).indexOf(job.job_id) < 0;
  }

  /** Log lines for the Logs tab. */
  function eventLine(e) {
    var bits = [e.kind];
    if (e.stage) bits.push(e.stage);
    if (e.status) bits.push(e.status);
    if (e.error) bits.push(e.error);
    if (e.state) bits.push(e.state);
    if (e.action) bits.push(e.action);
    return bits.join(' · ');
  }
  function mergeEvents(list, incoming) {
    var seen = {};
    list.forEach(function (e) { seen[e.seq] = true; });
    var out = list.slice();
    incoming.forEach(function (e) { if (!seen[e.seq]) out.push(e); });
    return out.sort(function (a, b) { return a.seq - b.seq; });
  }

  return { STAGES: STAGES, TERMINAL: TERMINAL, DRAFT_NOTICE: DRAFT_NOTICE, NO_API_COST: NO_API_COST, QA_NOTE: QA_NOTE, PART_STATE: PART_STATE, partStateInfo: partStateInfo,
           isTerminal: isTerminal, isActive: isActive, summaryLabel: summaryLabel, stageStates: stageStates, stateWord: stateWord, stageCaption: stageCaption, percent: percent,
           progressText: progressText, engineText: engineText, runtimeText: runtimeText, costText: costText, estimateText: estimateText, severityInfo: severityInfo,
           dispositionInfo: dispositionInfo, sortIssues: sortIssues, issueLocation: issueLocation, openIssueCount: openIssueCount, historyLine: historyLine, reviewBlock: reviewBlock,
           coverageText: coverageText, coverageScore: coverageScore, viewerSources: viewerSources, viewerKey: viewerKey, fileLabel: fileLabel, fileList: fileList,
           drawingStatus: drawingStatus, runBlock: runBlock, templateBlock: templateBlock, templateStatus: templateStatus, sourceWord: sourceWord, isSldprt: isSldprt,
           filterPicked: filterPicked, markDuplicates: markDuplicates, pickedSummary: pickedSummary, makeGuard: makeGuard, isPreviousRun: isPreviousRun, eventLine: eventLine,
           mergeEvents: mergeEvents };
});
