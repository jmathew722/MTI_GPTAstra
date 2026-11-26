/* McA.materialview: PURE presentation rules for the material features (no DOM, no network, no prices of its own).
   The server (GET /api/parts/{s}/{p}/material, /api/materials/*) is the single source of truth. This module only turns it into
   words, an icon name and a tone, so every status has a label AND an icon (never colour alone) and UNKNOWN is never shown as ZERO. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).materialview = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var ILLUSTRATIVE = 'Illustrative material estimate — not a supplier quote';
  var APPEARANCE_CAPTION = 'Illustrative appearance, not a finish specification';
  var UNAVAILABLE = 'estimate unavailable';
  var NOT_EVALUATED = 'Not evaluated yet';
  var NOT_EVALUATED_DETAIL = 'The material is read from the drawing on the next run. Nothing is shown here until then.';
  var CAVEAT = 'Material only: excludes machining, tooling, finishing, setup, and any supplier price.';

  /* status -> label, icon (McA.icons name), tone (a band: green amber orange red blue none), kind (badge-c class) */
  var STATUS = {
    assigned_verified: { label: 'Verified on part', icon: 'check', tone: 'green', kind: 'ok' },
    matched: { label: 'Matched from drawing', icon: 'check', tone: 'blue', kind: 'steel' },
    not_specified: { label: 'No material specified on drawing', icon: 'dash', tone: 'blue', kind: 'steel' },
    unmatched: { label: 'Not in catalog', icon: 'warn', tone: 'amber', kind: 'warn' },
    ambiguous: { label: 'Needs review', icon: 'warn', tone: 'orange', kind: 'orange' },
    override_pending: { label: 'Manual override — differs from the drawing', icon: 'warn', tone: 'amber', kind: 'warn' },
    assignment_failed: { label: 'Assignment failed', icon: 'x', tone: 'red', kind: 'err' }
  };
  var UNKNOWN = { label: 'Status unknown', icon: 'info', tone: 'none', kind: '' };

  function isNum(v) { return typeof v === 'number' && isFinite(v); }

  /** Status of a composed part-material payload (GET .../material). Not evaluated is its own state, never a guess. */
  function statusInfo(m) {
    if (!m || !m.evaluated || !m.resolution) return { id: 'not_evaluated', label: NOT_EVALUATED, icon: 'dash', tone: 'none', kind: '' };
    var res = m.resolution, st = res.status, base = STATUS[st] || UNKNOWN, out = { id: st || 'unknown', label: base.label, icon: base.icon, tone: base.tone, kind: base.kind };
    if (res.selection_source === 'manual_override' && st !== 'assignment_failed') {
      var b = STATUS.override_pending;
      out.label = st === 'assigned_verified' ? 'Manual override — verified on part' : b.label; out.icon = b.icon; out.tone = st === 'assigned_verified' ? 'amber' : b.tone; out.kind = b.kind;
    }
    if (m.from_saved_extraction && (st === 'matched')) out.label = 'Matched from saved extraction';
    return out;
  }

  /** The one-line title for a part: what the material is, or why there is none. */
  function titleOf(m) {
    if (!m || !m.evaluated || !m.resolution) return NOT_EVALUATED;
    var res = m.resolution, ch = res.chosen;
    if (ch && ch.label) return ch.label;
    return res.label || statusInfo(m).label;
  }

  function fmtNum(n, digits) { return isNum(n) ? Number(n).toLocaleString('en-US', { maximumFractionDigits: digits === undefined ? 4 : digits }) : ''; }
  function density(n) { return isNum(n) ? fmtNum(n, 1) + ' kg/m³' : 'density not stated'; }
  /** "4.00 USD/kg (synthetic_demo_usd_per_kg)"; an absent price is "price not set", never 0. */
  function price(p, currency, basis) {
    if (!isNum(p)) return 'price not set';
    var s = p.toFixed(2) + ' ' + (currency || '') + '/kg';
    return basis ? s.replace('  ', ' ') + ' (' + String(basis).replace(/_/g, ' ') + ')' : s;
  }

  /** Cost line of a costing payload. available + number -> display; anything else -> "estimate unavailable" with the reason. */
  function costInfo(c) {
    if (!c) return { available: false, text: UNAVAILABLE, reason: 'No costing was produced for this part yet.', illustrative: false, label: '' };
    var disp = c.display && c.display.net_material_cost;
    var ok = !!c.available && isNum(c.net_material_cost);
    if (!ok) return { available: false, text: UNAVAILABLE, reason: c.reason || 'No verified material, volume or price.', illustrative: false, label: '' };
    var ill = /illustrative/i.test(String(c.label || '')) || /demo|synthetic/i.test(String(c.inputs && c.inputs.price_basis || ''));
    return { available: true, text: disp || (fmtNum(c.net_material_cost, 2) + ' ' + (c.currency || '')), reason: '', illustrative: ill || !!c.label, label: c.label || (ill ? ILLUSTRATIVE : '') };
  }

  /** Compact one-line summary used in the Workspace and tables: {title, status, cost}. */
  function summary(m) {
    var s = statusInfo(m), c = m && m.evaluated ? costInfo(m.costing) : null;
    return { title: titleOf(m), status: s, cost: c, costText: c ? (c.available ? c.text : UNAVAILABLE) : '' };
  }

  /** Per-part record from /api/materials/batch -> {status, title, costText, illustrative}. */
  function compactInfo(c) {
    if (!c || !c.evaluated) return { evaluated: false, label: NOT_EVALUATED, icon: 'dash', tone: 'none', kind: '', title: NOT_EVALUATED, costText: UNAVAILABLE, illustrative: false };
    var base = STATUS[c.status] || UNKNOWN, label = base.label, icon = base.icon, tone = base.tone, kind = base.kind;
    if (c.selection_source === 'manual_override') { var b = STATUS.override_pending; label = c.status === 'assigned_verified' ? 'Manual override — verified on part' : b.label; icon = b.icon; tone = b.tone; kind = b.kind; }
    var cost = c.cost || {}, ok = !!cost.available && !!cost.display;
    return { evaluated: true, label: label, icon: icon, tone: tone, kind: kind, title: c.material_label || c.label || label, costText: ok ? cost.display : UNAVAILABLE,
             illustrative: ok && /illustrative/i.test(String(cost.label || '')), fromSaved: !!c.from_saved_extraction };
  }

  /** Batch totals text. Unknown parts are named, never counted as zero; currencies are never summed together. */
  function batchText(b) {
    if (!b || typeof b.total_parts !== 'number') return '';
    var n = b.total_parts, priced = b.priced_parts || 0, un = b.unpriced_parts || 0;
    var totals = Object.keys(b.totals || {}).map(function (k) { return b.totals[k].display || (fmtNum(b.totals[k].value, 2) + ' ' + k); });
    if (!priced) return n ? 'Material cost: estimate unavailable for ' + un + ' of ' + n + ' part' + (n === 1 ? '' : 's') + '.' : '';
    var s = 'Material cost: ' + totals.join(' + ') + ' for ' + priced + ' priced part' + (priced === 1 ? '' : 's');
    if (un) s += '; estimate unavailable for ' + un + ' (not counted as zero)';
    return s + '.';
  }

  /** Library control line: which catalog is used and how many records it holds. */
  function libraryLine(lib) {
    if (!lib || !lib.active) return lib && lib.error ? 'Company library not usable: ' + lib.error : 'No company library. Using the demo catalog.';
    var s = lib.name + ' · ' + lib.entries + ' material' + (lib.entries === 1 ? '' : 's');
    return lib.rejected ? s + ' · ' + lib.rejected + ' rejected' : s;
  }
  /** Which catalog a run will use, for the Run All dialog. */
  function runCatalogLine(settings) {
    var lib = settings && settings.library;
    if (lib && lib.active) return 'Material library: ' + lib.name + ' (' + lib.entries + ' materials)';
    return 'Material library: demo catalog (synthetic prices). Costs are illustrative.';
  }

  /** Is a native flag shown as Yes / No / "At build"? */
  function nativeWord(rec, source) {
    if (rec && rec.native) return 'Yes';
    return source === 'demo' ? 'At build' : 'No';
  }

  /** Decide what the 3D viewer does with the appearance sidecar response (server already compared the STL hash). */
  function appearanceDecision(a) {
    if (a && a.viewer_apply === true && /^#[0-9a-fA-F]{6}$/.test(String(a.color || '')) && isNum(a.metalness) && isNum(a.roughness)) {
      return { apply: true, color: a.color, metalness: Math.min(1, Math.max(0, a.metalness)), roughness: Math.min(1, Math.max(0, a.roughness)),
               label: a.material_label || 'Material', status: 'Verified on part', caption: APPEARANCE_CAPTION };
    }
    var why = !a ? 'No appearance data for this model.' : a.stl_matches === false ? 'The appearance data belongs to a different model file.' : a.verified !== true ? 'The material is not verified on the native part.' : 'Appearance data is incomplete.';
    return { apply: false, label: 'Preview: material not verified', status: 'Not verified', caption: why };
  }

  /** Section tone for Pipeline Results nav: {tone, word}. */
  function sectionTone(m) {
    if (!m || !m.evaluated) return { tone: 'none', word: NOT_EVALUATED.toLowerCase() };
    var s = statusInfo(m), w = { assigned_verified: 'verified', matched: 'matched', not_specified: 'not specified', unmatched: 'review', ambiguous: 'review', override_pending: 'override', assignment_failed: 'failed' }[m.resolution.status] || 'present';
    if (m.stale && s.tone === 'green') return { tone: 'amber', word: 'out of date' };
    return { tone: s.tone, word: w };
  }

  /** Validation of the override form: returns '' when valid, else the reason the Apply button is disabled. */
  function overrideBlock(materialId, reason) {
    if (!materialId) return 'Choose a catalog material.';
    if (!String(reason || '').trim()) return 'Enter a reason for the override.';
    if (String(reason).length > 500) return 'The reason is limited to 500 characters.';
    return '';
  }

  /** Who/when line of an override. */
  function overrideLine(o) {
    if (!o) return '';
    var who = o.user || 'unknown', at = o.at ? String(o.at).replace('T', ' ').replace(/\+00:00$|Z$/, ' UTC') : 'time not recorded';
    return 'Set by ' + who + ' on ' + at;
  }

  return { ILLUSTRATIVE: ILLUSTRATIVE, APPEARANCE_CAPTION: APPEARANCE_CAPTION, UNAVAILABLE: UNAVAILABLE, NOT_EVALUATED: NOT_EVALUATED, NOT_EVALUATED_DETAIL: NOT_EVALUATED_DETAIL,
           CAVEAT: CAVEAT, STATUS: STATUS, statusInfo: statusInfo, titleOf: titleOf, density: density, price: price, costInfo: costInfo, summary: summary,
           compactInfo: compactInfo, batchText: batchText, libraryLine: libraryLine, runCatalogLine: runCatalogLine, nativeWord: nativeWord,
           appearanceDecision: appearanceDecision, sectionTone: sectionTone, overrideBlock: overrideBlock, overrideLine: overrideLine };
});
