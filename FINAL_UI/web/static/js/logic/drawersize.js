/* McA.drawerSize: PURE drawer sizing. No DOM. The drawer maximum is the real space left under the
   header and tracker (measured by the caller), never a fraction of the viewport. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).drawerSize = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var MIN = 160, DEFAULT = 320, SIZES = ['remembered', 'fit', 'max'];

  /** Available drawer height. Grid layout: page minus the rows above it and their gaps (header | tracker |
   *  canvas collapsed to 0 | drawer = three gaps). Flow layout (narrow): the visible scroll area. */
  function maxHeight(m) {
    var v = m.flow ? (m.viewportH || 0) - 16
      : (m.pageH || 0) - (m.headH || 0) - (m.trackerH || 0) - 3 * (m.gap === undefined ? 12 : m.gap);
    return Math.max(MIN, Math.round(v));
  }
  function clamp(h, min, max) { return Math.min(max, Math.max(min, Math.round(h))); }
  function resolve(o) {
    var min = o.min === undefined ? MIN : o.min, max = o.max;
    var size = SIZES.indexOf(o.size) >= 0 ? o.size : 'remembered';
    if (size === 'max') return max;
    if (size === 'fit') return clamp(typeof o.fit === 'number' ? o.fit : DEFAULT, min, max);
    return clamp(typeof o.remembered === 'number' ? o.remembered : DEFAULT, min, max);
  }
  function viewportClass(width) { return width < 1100 ? 'narrow' : width < 1440 ? 'medium' : 'wide'; }
  function rememberedFor(map, cls, fallback) {
    var v = map && typeof map === 'object' ? map[cls] : undefined;
    return typeof v === 'number' && isFinite(v) && v >= MIN ? v : fallback;
  }
  function toggleMax(size) { return size === 'max' ? 'remembered' : 'max'; }

  return { MIN: MIN, DEFAULT: DEFAULT, SIZES: SIZES, maxHeight: maxHeight, resolve: resolve, clamp: clamp,
           viewportClass: viewportClass, rememberedFor: rememberedFor, toggleMax: toggleMax };
});
