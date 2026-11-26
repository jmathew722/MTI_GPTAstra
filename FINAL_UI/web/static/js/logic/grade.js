/* McA.grade: the ONE place that turns a 0-100 score into a grade, a colour, a word and a glyph (no DOM, no network).
   Fixed thresholds for every individual number, bar, badge, chart and table cell; a smooth gradient only for spectrum visualisations.
   The colours here are mirrored by the --grade-* tokens in design-tokens.css (a test keeps them identical).

     0-39    Poor            #D95763        80-89   Good           #B5C76B
     40-59   Below Average   #D98B55        90-99   Excellent      #8DD49A
     60-79   Fair            #D6AF6B        100     Perfect        #4CB782

   Rules: the grade follows the ACTUAL number. A score below 100 is never promoted to Perfect (99.99 is Excellent), and a score is
   never shown rounded up to a grade it did not earn (formatting truncates, it does not round up). A missing, unavailable or invalid score
   (null, NaN, below 0 or above 100) is neutral grey, never red. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).grade = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var DASH = '–';
  /* Lowest first. `min` is inclusive, `max` is the top of the displayed range. */
  var GRADES = [
    { id: 'poor',      label: 'Poor',          min: 0,   max: 39,  color: '#D95763', glyph: '✕' },
    { id: 'below',     label: 'Below Average', min: 40,  max: 59,  color: '#D98B55', glyph: '▲' },
    { id: 'fair',      label: 'Fair',          min: 60,  max: 79,  color: '#D6AF6B', glyph: '!' },
    { id: 'good',      label: 'Good',          min: 80,  max: 89,  color: '#B5C76B', glyph: '✓' },
    { id: 'excellent', label: 'Excellent',     min: 90,  max: 99,  color: '#8DD49A', glyph: '✓✓' },
    { id: 'perfect',   label: 'Perfect',       min: 100, max: 100, color: '#4CB782', glyph: '★' }
  ];
  var NONE = { id: 'none', label: 'Not scored', min: null, max: null, color: '#92949E', glyph: DASH };

  function valid(score) { return typeof score === 'number' && isFinite(score) && score >= 0 && score <= 100; }

  /** The grade of a number. No rounding: 99.99 is Excellent, 39.99 is Poor, 100 alone is Perfect. */
  function gradeOf(score) {
    if (!valid(score)) return NONE;
    for (var i = GRADES.length - 1; i >= 0; i--) if (score >= GRADES[i].min) return GRADES[i];
    return GRADES[0];
  }
  /** Grade of a 0..1 credit (item-level credits are fractions). */
  function gradeOfCredit(c) { return typeof c === 'number' && isFinite(c) ? gradeOf(Math.round(c * 1e9) / 1e7) : NONE; }
  function colorOf(score) { return gradeOf(score).color; }
  function classOf(score) { return 'grade-' + gradeOf(score).id; }
  function byId(id) { for (var i = 0; i < GRADES.length; i++) if (GRADES[i].id === id) return GRADES[i]; return NONE; }

  /** Format a score WITHOUT rounding it up: truncates to `digits` decimals, so 99.96 reads 99.9 and only exactly 100 reads 100. */
  function format(score, digits) {
    if (!valid(score)) return DASH;
    var d = digits === undefined ? 1 : digits, f = Math.pow(10, d);
    var t = Math.floor(score * f + 1e-9) / f;
    return d === 0 ? String(t) : t.toFixed(d);
  }
  function formatFull(score, digits) { var t = format(score, digits); return t === DASH ? DASH : t + ' / 100'; }

  function hexToRgb(hex) { var n = parseInt(hex.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
  function rgba(hex, a) { var c = hexToRgb(hex); return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')'; }

  /** A smooth left-to-right gradient across 0..100 for SPECTRUM visualisations (legends); the six colours sit at the middle of their ranges. */
  function gradientCSS(direction) {
    var stops = GRADES.map(function (g) { var mid = g.id === 'perfect' ? 100 : (g.min + g.max) / 2; return g.color + ' ' + mid + '%'; });
    return 'linear-gradient(' + (direction || 'to right') + ', ' + stops.join(', ') + ')';
  }
  /** Position (0..100) of a score on that spectrum, for a marker. Invalid -> null. */
  function spectrumPos(score) { return valid(score) ? score : null; }

  /** Count grades over a list of scores; invalid scores are not counted. [{id, label, color, count, pct}] */
  function distribution(scores) {
    var counts = {}, total = 0;
    GRADES.forEach(function (g) { counts[g.id] = 0; });
    (scores || []).forEach(function (s) { if (valid(s)) { counts[gradeOf(s).id] += 1; total += 1; } });
    return GRADES.map(function (g) { return { id: g.id, label: g.label, color: g.color, min: g.min, max: g.max, count: counts[g.id], pct: total ? Math.round(1000 * counts[g.id] / total) / 10 : 0 }; });
  }
  function rangeText(g) { return g.min === g.max ? String(g.min) : g.min + '–' + g.max; }

  /** Perceived readability: WCAG contrast ratio of the grade colour against a background hex (used by tests). */
  function contrast(hexA, hexB) {
    function lum(h) { return hexToRgb(h).map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }).reduce(function (a, v, i) { return a + v * [0.2126, 0.7152, 0.0722][i]; }, 0); }
    var a = lum(hexA), b = lum(hexB), hi = Math.max(a, b), lo = Math.min(a, b);
    return (hi + 0.05) / (lo + 0.05);
  }

  return { GRADES: GRADES, NONE: NONE, valid: valid, gradeOf: gradeOf, gradeOfCredit: gradeOfCredit, colorOf: colorOf, classOf: classOf, byId: byId, format: format,
           formatFull: formatFull, rgba: rgba, gradientCSS: gradientCSS, spectrumPos: spectrumPos, distribution: distribution, rangeText: rangeText, contrast: contrast, DASH: DASH };
});
