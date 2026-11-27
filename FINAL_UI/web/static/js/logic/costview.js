/* McA.costview: PURE presentation rules for the v8 pre-run estimate, live usage and actual cost of a run (no DOM, no network, no prices).
   The backend (V8_CONTRACT.md sections 1 and 2) is the only source of numbers. This module turns them into words and keeps three things apart that must never
   be confused: UNKNOWN (null: shown "unavailable"), ZERO (a measured zero, or a mode that has no model call) and NOT YET (no data). Money is never shown as
   $0.00 unless the backend said it is zero. Actual cost is "calculated from token usage", not an invoice. Local CAD time never carries a token cost. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).costview = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var DASH = '–';
  var UNAVAILABLE = 'unavailable';
  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  function plural(n, w) { return n + ' ' + w + (n === 1 ? '' : 's'); }

  /* ------------------------------------------------------------------ money */
  /** Actual / measured money: up to $10 four decimals (a $0.0043 call must never read $0.00), above that cents. null/negative/NaN => "unavailable". */
  function money(v) {
    if (!isNum(v) || v < 0) return UNAVAILABLE;
    if (v === 0) return '$0.00';
    if (v < 0.0001) return '<$0.0001';
    return v < 10 ? '$' + v.toFixed(4) : '$' + v.toFixed(2);
  }
  /** Estimated money: two decimals from $0.10, four below (estimates are not precise to the sub-cent above that). */
  function moneyEst(v) {
    if (!isNum(v) || v < 0) return UNAVAILABLE;
    if (v === 0) return '$0.00';
    if (v < 0.0001) return '<$0.0001';
    return v < 0.1 ? '$' + v.toFixed(4) : '$' + v.toFixed(2);
  }
  function moneyRange(lo, ex, hi) {
    if (!isNum(lo) || !isNum(ex) || !isNum(hi)) return UNAVAILABLE;
    return 'low ' + moneyEst(lo) + ' · expected ' + moneyEst(ex) + ' · high ' + moneyEst(hi);
  }

  /* ------------------------------------------------------------------ durations */
  function dur(s) {
    if (!isNum(s) || s < 0) return '';
    if (s < 1) return '<1 s';
    if (s < 60) return Math.round(s) + ' s';
    var m = Math.floor(s / 60), r = Math.round(s - m * 60);
    if (r === 60) { m += 1; r = 0; }
    if (m < 60) return m + ' min' + (r ? ' ' + r + ' s' : '');
    var h = Math.floor(m / 60), mm = m - h * 60;
    return h + ' h' + (mm ? ' ' + mm + ' min' : '');
  }
  /** Short form for a range end: "90 s" -> "1.5 min". */
  function durShort(s) {
    if (!isNum(s) || s < 0) return '';
    if (s < 60) return Math.max(1, Math.round(s)) + ' s';
    var m = s / 60;
    if (m < 90) return (m < 10 ? Math.round(m * 10) / 10 : Math.round(m)) + ' min';
    var h = Math.floor(m / 60), mm = Math.round(m - h * 60);
    return h + ' h' + (mm ? ' ' + mm + ' min' : '');
  }
  function durRange(lo, hi) {
    if (!isNum(lo) || !isNum(hi)) return '';
    var a = durShort(lo), b = durShort(hi);
    return a === b ? a : a + ' ' + DASH + ' ' + b;
  }
  function count(n) { return isNum(n) ? Math.round(n).toLocaleString('en-US') : '—'; }

  /* ------------------------------------------------------------------ pre-run estimate (V8 section 1) */
  /** One <Estimate>. Returns {state, duration, durationRange, durationBasis, rough, cost:{state,text,range,reason}, model, rate, tokens, labels, assumptions, stages}.
      state: 'none' (no estimate object), 'ready'. Never invents a number: a missing member is simply absent. */
  function estimateView(est) {
    if (!est || typeof est !== 'object') return { state: 'none', duration: null, cost: { state: 'unknown', text: UNAVAILABLE, range: '', reason: '' }, labels: [], assumptions: [], stages: [] };
    var d = est.duration || null, c = est.cost || null;
    var out = { state: 'ready', labels: Array.isArray(est.labels) ? est.labels.slice() : [], assumptions: Array.isArray(est.assumptions) ? est.assumptions.slice() : [] };
    if (d && (isNum(d.expected_s) || (isNum(d.low_s) && isNum(d.high_s)))) {
      var rough = d.source === 'fallback';
      out.duration = { expected: isNum(d.expected_s) ? durShort(d.expected_s) : '', range: isNum(d.low_s) && isNum(d.high_s) ? durRange(d.low_s, d.high_s) : '', rough: rough, basis: d.basis || '', source: d.source || '' };
      out.duration.text = (rough ? 'Rough estimate: ' : 'About ') + (out.duration.expected || out.duration.range) + (out.duration.expected && out.duration.range ? ' (range ' + out.duration.range + ')' : '');
    } else out.duration = null;
    var cs;
    if (!c) cs = { state: 'unknown', text: UNAVAILABLE, range: '', reason: '' };
    else if (!isNum(c.low) || !isNum(c.expected) || !isNum(c.high)) cs = { state: 'unknown', text: 'Cost unavailable', range: '', reason: c.unavailable_reason || 'The rate for this model is not configured.' };
    else if (c.low === 0 && c.expected === 0 && c.high === 0) cs = { state: 'none', text: 'No OpenAI cost expected', range: '', reason: c.unavailable_reason || 'No model call is needed for this run.' };
    else cs = { state: 'ready', text: moneyEst(c.expected), range: moneyRange(c.low, c.expected, c.high), reason: '' };
    out.cost = cs;
    out.model = c && c.model ? String(c.model) : '';
    out.rate = c && c.rate_version ? String(c.rate_version) : '';
    out.currency = (c && c.currency) || 'USD';
    out.modelLine = out.model ? 'Model ' + out.model + (out.rate ? ' · rates of ' + out.rate : '') : '';
    var t = est.tokens;
    if (t && t.input && t.output && isNum(t.input.expected) && isNum(t.output.expected)) out.tokens = 'about ' + count(t.input.expected) + ' in · ' + count(t.output.expected) + ' out' + (isNum(t.cached_input) && t.cached_input > 0 ? ' · ' + count(t.cached_input) + ' cached' : '');
    else out.tokens = '';
    out.stages = stageRows(est.by_stage, 'estimate');
    return out;
  }

  /* ------------------------------------------------------------------ stages */
  var STAGE_LABEL = { extraction: 'Extraction', tiles: 'Drawing assistance', validation: 'Validation', correction: 'Correction', local_generation: 'Local generation' };
  var TOKEN_STAGES = ['extraction', 'tiles', 'validation', 'correction'];
  /** Stage rows in the order extraction, drawing assistance, local generation, validation, correction. kind: 'estimate' | 'usage'. */
  function stageRows(by, kind) {
    if (!by || typeof by !== 'object') return [];
    var order = ['extraction', 'tiles', 'local_generation', 'validation', 'correction'];
    return order.filter(function (k) { return by[k]; }).map(function (k) {
      var s = by[k], r = { key: k, label: STAGE_LABEL[k], local: k === 'local_generation' };
      if (kind === 'estimate') {
        var c = s.cost || {};
        r.cost = isNum(c.expected) ? moneyEst(c.expected) : UNAVAILABLE;
        r.calls = s.calls && isNum(s.calls.expected) ? String(s.calls.expected) : '';
        r.duration = s.duration_s && isNum(s.duration_s.expected) ? durShort(s.duration_s.expected) : '';
      } else {
        r.calls = isNum(s.calls) ? s.calls : null; r.input = isNum(s.input_tokens) ? s.input_tokens : null; r.cached = isNum(s.cached_tokens) ? s.cached_tokens : null;
        r.output = isNum(s.output_tokens) ? s.output_tokens : null; r.attempts = isNum(s.attempts) ? s.attempts : null;
        r.cost = s.cost_usd === null ? UNAVAILABLE : isNum(s.cost_usd) ? money(s.cost_usd) : UNAVAILABLE;
      }
      if (r.local) r.note = 'no token cost';
      return r;
    });
  }

  /* ------------------------------------------------------------------ actual usage (V8 section 2) */
  /** usage -> display model. Cost status: priced (exact), partial (known part + unpriced calls), unpriced (unavailable), none (no model call). */
  function usageView(u) {
    if (!u || typeof u !== 'object') return { present: false, any: false, cost: { text: 'Not recorded', status: 'missing' }, tokens: '', calls: 0, cacheHits: 0, stages: [], retries: 0, notes: [] };
    var calls = isNum(u.calls) ? u.calls : 0, hits = isNum(u.cache_hits) ? u.cache_hits : 0, st = u.cost_status || (isNum(u.cost_usd) ? 'priced' : (calls ? 'unpriced' : 'none'));
    var cost, notes = [];
    if (st === 'priced' && isNum(u.cost_usd)) cost = { text: money(u.cost_usd), status: 'priced' };
    else if (st === 'partial') {
      cost = { text: (isNum(u.cost_usd) ? money(u.cost_usd) : UNAVAILABLE) + ' + unpriced calls', status: 'partial' };
      if (isNum(u.unpriced_calls) && u.unpriced_calls) notes.push(plural(u.unpriced_calls, 'call') + ' without a configured rate');
    } else if (st === 'unpriced') { cost = { text: UNAVAILABLE, status: 'unpriced' }; if (isNum(u.unpriced_calls) && u.unpriced_calls) notes.push('No rate is configured for the model used, so the cost cannot be calculated'); }
    else if (hits > 0 && !calls) cost = { text: '$0.00', status: 'cache', note: 'extraction reused, no model call' };
    else if (!calls) cost = { text: 'No model calls recorded', status: 'none' };
    else cost = { text: isNum(u.cost_usd) ? money(u.cost_usd) : UNAVAILABLE, status: st };
    if (isNum(u.unknown_usage_calls) && u.unknown_usage_calls > 0) notes.push(plural(u.unknown_usage_calls, 'call') + ' reported no usage, so the cost may be higher');
    var stages = stageRows(u.by_stage, 'usage');
    var retries = 0;
    stages.forEach(function (s) { if (isNum(s.attempts) && s.attempts > 1) retries += s.attempts - 1; });
    if (!stages.length && Array.isArray(u.attempts)) u.attempts.forEach(function (a) { if (a && isNum(a.attempt) && a.attempt > 0) retries++; });
    var tok = (isNum(u.input_tokens) || isNum(u.output_tokens)) ? count(u.input_tokens || 0) + ' in · ' + count(u.cached_tokens || 0) + ' cached · ' + count(u.output_tokens || 0) + ' out' : '';
    var saved = '';
    if (hits > 0 && isNum(u.historical_usd)) saved = 'Extraction reused (confirmed): saves about ' + money(u.historical_usd);
    else if (hits > 0) saved = 'Extraction reused (confirmed): no model call; the original cost is not recorded';
    return { present: true, any: calls > 0 || hits > 0, cost: cost, tokens: tok, calls: calls, cacheHits: hits, stages: stages, retries: retries, notes: notes, saved: saved,
      model: u.model ? String(u.model) : '', rate: u.rate_version ? String(u.rate_version) : '' };
  }

  /* ------------------------------------------------------------------ timing */
  /** Elapsed shown now: the server's monotonic elapsed_s plus the browser's own monotonic time since that value arrived (only while running). */
  function liveElapsed(timing, fetchedAt, now) {
    if (!timing || !isNum(timing.elapsed_s)) return null;
    var extra = timing.running && isNum(fetchedAt) && isNum(now) ? Math.max(0, (now - fetchedAt) / 1000) : 0;
    return timing.elapsed_s + extra;
  }
  function remainingText(timing, elapsedNow, fetchedAt) {
    var r = timing && timing.remaining_s;
    if (!r || !isNum(r.expected)) return '';
    var spent = timing.running && isNum(fetchedAt) ? Math.max(0, elapsedNow - timing.elapsed_s) : 0;
    var ex = Math.max(0, r.expected - spent);
    if (ex <= 0) return 'taking longer than estimated';
    var rng = isNum(r.low) && isNum(r.high) ? ' (' + durRange(Math.max(0, r.low - spent), Math.max(0, r.high - spent)) + ')' : '';
    return (r.source === 'fallback' ? 'rough: ' : '') + 'about ' + durShort(ex) + ' left' + rng;
  }

  /* ------------------------------------------------------------------ actual vs estimate */
  function compareLines(job) {
    var out = [], eva = job && job.estimate_vs_actual;
    var cost = eva && eva.cost_usd, du = eva && eva.duration_s;
    if (cost && isNum(cost.actual) && isNum(cost.expected)) out.push('Cost: ' + money(cost.actual) + ' actual vs ' + moneyEst(cost.expected) + ' expected' + (cost.within_range === true ? ' (within the estimated range)' : cost.within_range === false ? ' (outside the estimated range)' : ''));
    if (du && isNum(du.actual) && isNum(du.expected)) out.push('Time: ' + dur(du.actual) + ' actual vs ' + durShort(du.expected) + ' expected' + (du.within_range === true ? ' (within the estimated range)' : du.within_range === false ? ' (outside the estimated range)' : ''));
    return out;
  }

  /* ------------------------------------------------------------------ whole-run model */
  var TERMINAL = { completed: 1, review_required: 1, failed: 1, canceled: 1, cancelled: 1 };
  var ACTIVE_STATES = { running: 1, queued: 1 };
  function partsProgress(job) {
    var ps = (job && job.parts) || [];
    var done = ps.filter(function (p) { return TERMINAL[p.state]; }).length;
    return { done: done, total: ps.length };
  }
  function perPartRows(job) {
    return ((job && job.parts) || []).map(function (p) {
      var u = usageView(p.usage), t = p.timing || {};
      return { id: p.part_id, name: p.name, state: p.state, cost: u.present ? u.cost.text : 'Not recorded', calls: u.calls, tokens: u.tokens,
        elapsed: isNum(t.elapsed_s) ? dur(t.elapsed_s) : '', cache: p.reference && p.reference.extraction_cache || '' };
    });
  }
  /** Everything the "Run Pipeline" cost area shows for one job (and optionally one selected part). job may be null (pre-run only). */
  function runModel(o) {
    o = o || {};
    var job = o.job || null, now = o.now, fetchedAt = o.fetchedAt;
    var est = estimateView(o.estimate || (job && job.estimate));
    var u = usageView(job && job.usage);
    var t = (job && job.timing) || null;
    var active = !!(job && ACTIVE_STATES[job.summary_state]);
    var el = liveElapsed(t, fetchedAt, now);
    var prog = partsProgress(job);
    var terminal = !!(job && !active && job.summary_state);
    var failedOrCanceled = job ? job.parts.filter(function (p) { return p.state === 'failed' || p.state === 'canceled'; }).length : 0;
    var m = { estimate: est, usage: u, active: active, terminal: terminal, parts: prog, elapsed: el === null ? '' : dur(el), elapsedS: el, queued: t && isNum(t.queued_s) ? dur(t.queued_s) : '',
      remaining: active ? remainingText(t, el, fetchedAt) : '', compare: terminal ? compareLines(job) : [], perPart: perPartRows(job), batch: !!(job && job.parts && job.parts.length > 1),
      timingStages: [] };
    if (t && t.by_stage) Object.keys(t.by_stage).forEach(function (k) { if (isNum(t.by_stage[k])) m.timingStages.push({ key: k, seconds: t.by_stage[k], text: dur(t.by_stage[k]) }); });
    m.keptNote = terminal && failedOrCanceled && u.present && u.any ? 'Cost already incurred by failed or canceled parts is kept in these totals.' : '';
    m.localNote = 'Local CAD processing time carries no token cost.';
    return m;
  }
  /** One line for the Run controls while a job is active. */
  function liveLine(m) {
    if (!m || !m.active) return '';
    var bits = [];
    if (m.parts.total) bits.push(m.parts.done + ' of ' + plural(m.parts.total, 'part') + ' done');
    if (m.elapsed) bits.push('elapsed ' + m.elapsed);
    if (m.usage.present && m.usage.any) bits.push(m.usage.cost.text + ' so far');
    if (m.remaining) bits.push(m.remaining);
    return bits.join(' · ');
  }
  /** Header chip text for the API usage chip. Returns '' when the backend sent no usable usage (the caller then falls back to the v7 text). */
  function chipText(job) {
    var u = usageView(job && job.usage);
    if (!u.present || (!u.any && u.cost.status === 'none')) return '';
    if (u.cost.status === 'unpriced') return 'API cost unavailable (' + plural(u.calls, 'call') + ')';
    if (u.cost.status === 'cache') return '$0.00 API usage (extraction reused)';
    return u.cost.text + ' API usage (calculated' + (u.cost.status === 'partial' ? ', partial' : '') + ')';
  }

  return { money: money, moneyEst: moneyEst, moneyRange: moneyRange, dur: dur, durShort: durShort, durRange: durRange, count: count, estimateView: estimateView, usageView: usageView, stageRows: stageRows,
    liveElapsed: liveElapsed, remainingText: remainingText, compareLines: compareLines, runModel: runModel, liveLine: liveLine, chipText: chipText, partsProgress: partsProgress, perPartRows: perPartRows,
    STAGE_LABEL: STAGE_LABEL, TOKEN_STAGES: TOKEN_STAGES, UNAVAILABLE: UNAVAILABLE };
});
