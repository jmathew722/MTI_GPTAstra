/* McA.referenceview: PURE presentation rules for the v7 3D -> 2D reference, export and source-viewer features (no DOM, no network).
   The server (GET /api/reverse/*) is the single source of truth; this module turns its payloads into words, an icon name and a tone, and decides
   which control is enabled and why not. Missing fields are omitted or shown as "not recorded", never as zero and never invented. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).referenceview = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function isNum(v) { return typeof v === 'number' && isFinite(v); }

  /* ------------------------------------------------------------------ artifacts */
  /** One artifact of a part by kind. The backend lists stable aliases (V7_CONTRACT 4) next to the legacy names; both are understood, and an entry the
      server marks `available: false` (or does not list at all) is absent. Returns {rel, bytes} or null. */
  var ALIASES = { slddrw: ['slddrw', 'drawing.slddrw'], pdf: ['pdf', 'drawing.pdf'], source_pdf: ['source_pdf', 'reference/source.pdf'], stl: ['stl', 'model.stl'], qa_json: ['qa_json', 'qa.json'] };
  function artifactOf(part, kind) {
    var f = (part && part.files) || {}, names = ALIASES[kind] || [kind];
    for (var i = 0; i < names.length; i++) {
      var e = f[names[i]];
      if (e && e.available !== false && typeof e.url_path === 'string' && e.url_path) return { rel: e.url_path, bytes: isNum(e.bytes) ? e.bytes : 0 };
    }
    return null;
  }
  /** Comparison page images (side-by-side / overlay), when the backend produced them. */
  function comparisonImages(part) {
    var c = part && part.files && part.files.comparison_images;
    var list = c && Array.isArray(c.files) && c.available !== false ? c.files : [];
    return list.filter(function (x) { return x && typeof x.url_path === 'string'; }).map(function (x) { return { name: String(x.name || ''), rel: x.url_path, bytes: isNum(x.bytes) ? x.bytes : 0 }; });
  }

  /* ------------------------------------------------------------------ export */
  var EXPORT_KINDS = [['slddrw', 'Download SLDDRW'], ['pdf', 'Download PDF'], ['zip', 'Download both (ZIP)']];
  /** Export panel state from GET .../export (server-computed): which buttons are enabled and why not. `ack` = the user ticked the acknowledgement. */
  function exportView(info, ack, busy) {
    if (!info || !info.downloads) {
      return { ready: false, needsAck: false, any: false, status: { key: 'none', label: 'No part selected', tone: 'none', requires_ack: false, reasons: [] },
        buttons: EXPORT_KINDS.map(function (k) { return { kind: k[0], label: k[1], enabled: false, available: false, reason: 'Select a part first.' }; }) };
    }
    var st = info.status || { key: 'review_required', label: 'Draft: review required', tone: 'amber', requires_ack: true, reasons: [] };
    var buttons = EXPORT_KINDS.map(function (k) {
      var d = info.downloads[k[0]] || {};
      var reason = '';
      if (!d.available) reason = d.reason || 'Not available for this part.';
      else if (busy) reason = 'A download is in progress.';
      else if (st.requires_ack && !ack) reason = 'Tick the acknowledgement to download this unapproved draft.';
      return { kind: k[0], label: k[1], enabled: !reason, available: !!d.available, reason: reason, bytes: d.bytes, filename: d.filename };
    });
    return { ready: true, status: st, buttons: buttons, needsAck: !!st.requires_ack, any: buttons.some(function (b) { return b.available; }) };
  }
  /** A key that changes when anything the export panel depends on changes (selection, state, files): used to refetch and to drop a stale acknowledgement. */
  function exportKey(job, part) {
    if (!job || !part) return '';
    var d = artifactOf(part, 'slddrw'), p = artifactOf(part, 'pdf'), v = part.verification && part.verification.status;
    return [job.job_id, part.part_id, part.state, part.review_status || '', v || '', d ? d.bytes : '-', p ? p.bytes : '-'].join('|');
  }

  /* ------------------------------------------------------------------ reference (setup rail) */
  var REF_MODE = { standard: 'Standard', match: 'Match reference' };
  var REF_SOURCE = { auto: 'Auto-find', upload: 'Upload PDF', saved: 'Select saved source' };
  function pagesText(n) { return isNum(n) && n > 0 ? n + ' page' + (n === 1 ? '' : 's') : ''; }
  function candidateLine(c) {
    var bits = [c.filename || 'PDF', pagesText(c.pages), [c.project, c.run].filter(Boolean).join(' / '), c.date ? String(c.date).slice(0, 10) : '', isNum(c.confidence) ? Math.round(c.confidence * 100) + '% confidence' : ''].filter(Boolean);
    return bits.join(' · ');
  }
  /** Resolution of ONE batch row before the run. row = {source, upload, artifactId, confirmed, lookup:{selected,candidates,error}|null, looking}; `fallback` is the
      second argument is unused (kept for call compatibility): a part runs in Standard only when the user chose that for the row. status: ready needs_confirmation unmatched checking unknown standard. */
  function rowResolution(row, fallback) {
    var src = row.source || 'auto';
    if (src === 'upload') {
      return row.upload ? { status: 'ready', kind: 'upload', label: 'Uploaded: ' + (row.upload.filename || 'PDF') + (pagesText(row.upload.pages) ? ' (' + pagesText(row.upload.pages) + ')' : '') }
        : { status: 'unmatched', kind: 'upload', label: 'Upload a reference PDF for this part' };
    }
    if (src === 'none') return { status: 'standard', kind: 'none', label: 'Standard layout for this part (explicit)' };
    var lk = row.lookup;
    if (src === 'artifact') {
      var cs = (lk && lk.candidates) || [], c = cs.filter(function (x) { return x.artifact_id === row.artifactId; })[0];
      if (!c) return { status: 'unmatched', kind: 'artifact', label: 'Choose a saved source' };
      if (c.needs_confirmation && !row.confirmed) return { status: 'needs_confirmation', kind: 'artifact', label: 'Confirm: ' + candidateLine(c) };
      return { status: 'ready', kind: 'artifact', label: 'Saved source: ' + candidateLine(c) };
    }
    if (row.looking) return { status: 'checking', kind: 'auto', label: 'Looking for a saved source...' };
    if (!lk) return { status: 'unknown', kind: 'auto', label: 'Not checked yet' };
    var n = (lk.candidates || []).length;
    if (lk.selected && !lk.selected.needs_confirmation) return { status: 'ready', kind: 'auto', candidate: lk.selected, label: 'Auto-matched: ' + candidateLine(lk.selected) };
    if (n) return { status: 'needs_confirmation', kind: 'auto', label: n + ' possible match' + (n === 1 ? '' : 'es') + ': choose one to confirm' };
    return { status: 'unmatched', kind: 'auto', note: lk.error || '', label: 'No saved source found' };
  }
  /** Why a match-mode run cannot start ('' when it can) and which rows need the user. */
  function referenceRunBlock(o) {
    if (o.mode !== 'match') return { reason: '', actionable: [] };
    if (!o.caps || !o.caps.reference) return { reason: 'Reference matching is not available in this backend build. Use Standard.', actionable: [] };
    var res = (o.rows || []).map(function (r) { return { row: r, res: rowResolution(r, o.fallback) }; });
    if (res.some(function (x) { return x.res.status === 'checking' || x.res.status === 'unknown'; })) return { reason: 'Checking saved references...', actionable: [] };
    var act = res.filter(function (x) { return x.res.status === 'unmatched' || x.res.status === 'needs_confirmation'; });
    var nc = act.filter(function (x) { return x.res.status === 'needs_confirmation'; }).length, nu = act.length - nc;
    var keys = act.map(function (x) { return x.row.key; });
    if (nc) return { reason: 'Choose and confirm the reference for ' + nc + ' part' + (nc === 1 ? '' : 's') + '.', actionable: keys };
    if (nu) return { reason: nu + ' part' + (nu === 1 ? ' has' : 's have') + ' no reference. Upload one or choose Standard for ' + (nu === 1 ? 'it' : 'them') + '.', actionable: keys };
    return { reason: '', actionable: [] };
  }
  /** One-line status for the Reference panel. */
  function referenceLine(o) {
    if (o.mode !== 'match') return 'Standard layout. No reference drawing is used.';
    var rows = o.rows || [];
    if (!rows.length) return 'Choose parts to find their reference drawings.';
    var res = rows.map(function (r) { return rowResolution(r, o.fallback).status; });
    var c = function (s) { return res.filter(function (x) { return x === s; }).length; };
    var bits = [c('ready') + ' of ' + rows.length + ' matched'];
    if (c('needs_confirmation')) bits.push(c('needs_confirmation') + ' need confirmation');
    if (c('unmatched')) bits.push(c('unmatched') + ' unmatched');
    if (c('standard')) bits.push(c('standard') + ' in Standard');
    if (c('checking') || c('unknown')) bits.push('checking');
    return bits.join(' · ');
  }
  /** Browser payload for POST /jobs. An auto row that resolved to one clear match sends exactly that artifact id (what the user saw is what runs). */
  function buildReferencePayload(mode, rows, fallback) {
    if (mode !== 'match') return { mode: 'standard' };
    var per = {};
    (rows || []).forEach(function (r) {
      var res = rowResolution(r);
      if (r.source === 'upload' && r.upload) per[r.key] = { source: 'upload', upload_id: r.upload.upload_id };
      else if (r.source === 'artifact' && r.artifactId) per[r.key] = { source: 'artifact', artifact_id: r.artifactId };
      else if (res.status === 'ready' && res.candidate) per[r.key] = { source: 'artifact', artifact_id: res.candidate.artifact_id };
      else per[r.key] = { source: 'none' };
    });
    var anyNone = Object.keys(per).some(function (k) { return per[k].source === 'none'; });
    return { mode: 'match', fallback_standard: anyNone, per_part: per };
  }

  /* ------------------------------------------------------------------ what a finished part used (job_view part.reference) */
  var REF_STATUS = {
    resolved: { label: 'Reference matched', tone: 'green', icon: 'check' }, blocked: { label: 'Reference blocked', tone: 'red', icon: 'x' },
    fallback_standard: { label: 'Standard (fallback)', tone: 'amber', icon: 'warn' }, pending: { label: 'Reference pending', tone: 'violet', icon: 'recent' },
    not_applicable: { label: 'Standard (no reference)', tone: 'none', icon: 'dash' }
  };
  var SOURCE_KIND = { upload: 'Uploaded PDF', artifact: 'Saved source', history: 'Forward run history', confirmed_link: 'Confirmed link', none: 'None' };
  var LINK_WORD = { part_hash: 'same part file (SHA-256)', forward_run: 'same forward run folder', recorded_source_hash: 'recorded source hash', confirmed: 'confirmed by a user' };
  var CACHE_WORD = { hit: 'Reused saved extraction (no new model call)', supplemented: 'Saved extraction supplemented with a new call', fresh: 'Fresh extraction', none: 'No extraction' };
  function refStatusInfo(ref) { return REF_STATUS[ref && ref.status] || { label: 'Reference unknown', tone: 'none', icon: 'info' }; }
  function shortHash(h) { return typeof h === 'string' && h ? h.slice(0, 12) : ''; }
  /** OpenAI usage of one part's reference extraction. Local CAD time is never a token cost; unknown is "Not recorded", never $0. */
  function apiUsageText(u) {
    if (!u || typeof u !== 'object' || !isNum(u.usd)) return 'Not recorded';
    var t = u.usd === 0 && !(u.calls > 0) ? 'No OpenAI call in this run ($0.00)' : '$' + u.usd.toFixed(4) + ' OpenAI (this run)';
    if (isNum(u.calls) && u.calls > 0) t += ', ' + u.calls + ' call' + (u.calls === 1 ? '' : 's');
    if (isNum(u.input_tokens) || isNum(u.output_tokens)) t += ', ' + (u.input_tokens || 0) + ' in / ' + (u.output_tokens || 0) + ' out tokens';
    return t;
  }
  function provenanceRows(ref) {
    if (!ref || ref.mode !== 'match') return [];
    var rows = [['Status', refStatusInfo(ref).label], ['Source', SOURCE_KIND[ref.source_kind] || '']];
    if (ref.filename) rows.push(['File', ref.filename + (pagesText(ref.pages) ? ' (' + pagesText(ref.pages) + ')' : '')]);
    if (ref.sha256) rows.push(['SHA-256', shortHash(ref.sha256)]);
    if (ref.link) rows.push(['Linked by', LINK_WORD[ref.link] || ref.link]);
    if (isNum(ref.confidence)) rows.push(['Confidence', Math.round(ref.confidence * 100) + '%']);
    if (ref.extraction_cache) rows.push(['Extraction', CACHE_WORD[ref.extraction_cache] || ref.extraction_cache]);
    if (ref.api_usage) rows.push(['OpenAI usage', apiUsageText(ref.api_usage)]);
    return rows.filter(function (r) { return r[1]; });
  }
  /** One line under the left viewer's Source PDF label: what it is and where it came from. */
  function sourceProvenance(ref) {
    if (!ref || ref.mode !== 'match') return '';
    var bits = [ref.filename || 'Reference PDF'];
    if (pagesText(ref.pages)) bits.push(pagesText(ref.pages));
    if (SOURCE_KIND[ref.source_kind]) bits.push(SOURCE_KIND[ref.source_kind]);
    if (shortHash(ref.sha256)) bits.push('SHA-256 ' + shortHash(ref.sha256));
    return bits.join(' · ');
  }
  /** Left viewer "Source PDF" availability. Never falls back to the generated PDF; the reason names what is missing. */
  function sourceView(part) {
    if (!part) return { available: false, reason: 'Select a part first.' };
    var a = artifactOf(part, 'source_pdf'), ref = part.reference || null;
    if (a) return { available: true, rel: a.rel, bytes: a.bytes, provenance: sourceProvenance(ref), filename: (ref && ref.filename) || 'source.pdf' };
    if (!ref) return { available: false, reason: 'No source PDF is recorded for this part.' };
    if (ref.mode === 'standard' || ref.status === 'not_applicable') return { available: false, reason: 'This part ran in Standard mode, so there is no source PDF.' };
    if (ref.status === 'blocked') return { available: false, reason: 'The reference was blocked, so no source PDF was used.' };
    if (ref.status === 'fallback_standard') return { available: false, reason: 'No reference was found; the part ran in Standard mode.' };
    if (ref.status === 'pending') return { available: false, reason: 'The reference is still being resolved.' };
    return { available: false, reason: 'The source PDF file is not available.' };
  }

  /* ------------------------------------------------------------------ verification block (job_view part.verification) */
  var VER_STATUS = {
    passed: { label: 'Verification passed (draft, not approved)', tone: 'green', icon: 'check' }, review_required: { label: 'Review required', tone: 'amber', icon: 'warn' },
    failed: { label: 'Verification failed', tone: 'red', icon: 'x' }, pending: { label: 'Verification pending', tone: 'violet', icon: 'recent' }, not_run: { label: 'Verification not run', tone: 'none', icon: 'dash' }
  };
  function verificationInfo(v) { return VER_STATUS[v && v.status] || { label: 'Verification not recorded', tone: 'none', icon: 'info' }; }
  function verificationLines(v) {
    if (!v || typeof v !== 'object') return [];
    var out = [], c = v.coverage;
    if (c && isNum(c.total)) out.push(['Items matched', (isNum(c.matched) ? c.matched : 0) + ' of ' + c.total + ((c.unresolved || []).length ? ' (' + c.unresolved.length + ' unresolved)' : '')]);
    if (v.collisions && isNum(v.collisions.count)) out.push(['Overlaps', v.collisions.count === 0 ? 'None found' : v.collisions.count + ' found']);
    if (v.iterations && isNum(v.iterations.used)) out.push(['Correction passes', v.iterations.used + (isNum(v.iterations.max) ? ' of ' + v.iterations.max : '')]);
    return out;
  }

  /* ------------------------------------------------------------------ cost split (OpenAI vs local CAD time) */
  /** Runtime & Cost summary for the setup rail. OpenAI spend and local CAD time are separate lines; CAD time is "no token cost". */
  function costSummary(job, estimateText, mode) {
    var parts = (job && job.parts) || [];
    var usd = 0, known = 0;
    parts.forEach(function (p) { var u = p.reference && p.reference.api_usage; if (u && isNum(u.usd)) { usd += u.usd; known++; } });
    var openai;
    if (!job) openai = mode === 'match' ? 'Reference extraction may use OpenAI; the measured cost is shown after the run.' : 'No OpenAI calls (Standard mode).';
    else if (known) openai = '$' + usd.toFixed(4) + ' OpenAI across ' + known + ' part' + (known === 1 ? '' : 's') + (known < parts.length ? ' (others not recorded)' : '');
    else if (isNum(job.actual_api_cost_usd) && job.actual_api_cost_usd > 0) openai = '$' + job.actual_api_cost_usd.toFixed(4) + ' OpenAI (measured)';
    else if (isNum(job.actual_api_cost_usd)) openai = '$0.00 OpenAI (no model calls recorded)';
    else openai = 'OpenAI usage not recorded';
    return { openai: openai, cad: 'Local CAD automation: no token cost', estimate: estimateText || '' };
  }

  return { artifactOf: artifactOf, comparisonImages: comparisonImages, exportView: exportView, exportKey: exportKey, EXPORT_KINDS: EXPORT_KINDS, REF_MODE: REF_MODE, REF_SOURCE: REF_SOURCE,
           pagesText: pagesText, candidateLine: candidateLine, rowResolution: rowResolution, referenceRunBlock: referenceRunBlock, referenceLine: referenceLine,
           buildReferencePayload: buildReferencePayload, refStatusInfo: refStatusInfo, apiUsageText: apiUsageText, provenanceRows: provenanceRows, sourceProvenance: sourceProvenance,
           sourceView: sourceView, verificationInfo: verificationInfo, verificationLines: verificationLines, costSummary: costSummary };
});
