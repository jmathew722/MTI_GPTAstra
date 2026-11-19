/* McA.markupview: PURE logic for the automatic Engineering Markup view (Stage 3). No DOM, no fetch.
   The pipeline renders <part>_engineering_markup.pdf + page previews and a manifest; the server validates it and
   puts a summary at payload.categories.engineering_markup. This file decides what the viewer shows: whether the
   view exists, whether to select it automatically, which page a flag is on, where its clickable regions are, and
   what to say when the marked PDF is partial, failed or stale. It never invents a location. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).markupview = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /** usable: ready/partial with pages; failed: flags exist but no PDF; stale: another drawing revision; none: nothing to show. */
  function model(cat) {
    if (!cat || !cat.present) return { state: 'none' };
    var count = cat.finding_count || 0;
    if (cat.status === 'stale') return { state: 'stale', count: count, key: cat.generation_key || '' };
    if (cat.status === 'failed') return { state: count > 0 ? 'failed' : 'none', count: count, failure: cat.failure || null, key: cat.generation_key || '' };
    if ((cat.status !== 'ready' && cat.status !== 'partial') || count === 0) return { state: 'none' };
    var pages = (cat.pages || []).slice().sort(function (a, b) { return a.page - b.page; });
    if (!pages.length) return { state: 'none' };
    return { state: cat.status, count: count, located: cat.located_count || 0, unlocated: cat.unlocated_count || 0,
             key: cat.generation_key || '', pages: pages, findings: cat.findings || [], hasPdf: !!cat.has_pdf,
             warnings: cat.warnings || [], reportPages: cat.report_pages || 0 };
  }
  function usable(m) { return !!m && (m.state === 'ready' || m.state === 'partial'); }
  function exists(m) { return !!m && (usable(m) || m.state === 'failed'); }

  /** Select the view automatically once per generated artifact, unless the person already chose Overview for it. */
  function autoSelect(m, seenKey, userChoseOverviewForKey) {
    if (!usable(m)) return false;
    if (seenKey === m.key) return false;
    return !userChoseOverviewForKey;
  }

  function findFlag(m, id) {
    if (!usable(m)) return null;
    for (var i = 0; i < m.findings.length; i++) if (m.findings[i].finding_id === id || m.findings[i].id === id) return m.findings[i];
    return null;
  }
  function firstPage(m) {
    if (!usable(m)) return 1;
    var best = null;
    m.findings.forEach(function (f) { if (f.location_status === 'located' && f.page && (best === null || f.page < best)) best = f.page; });
    return best || (m.pages[0] && m.pages[0].page) || 1;
  }
  function hasFlag(m, id) { return !!findFlag(m, id); }
  function pageInfo(m, page) {
    if (!usable(m)) return null;
    for (var i = 0; i < m.pages.length; i++) if (m.pages[i].page === page) return m.pages[i];
    return null;
  }

  /** The page a flag is on: its region's page, its card's page (unlocated), else null. */
  function pageOf(m, id) {
    var f = findFlag(m, id);
    if (!f) return null;
    if (f.regions && f.regions.length && f.regions[0].page) return f.regions[0].page;
    if (f.page) return f.page;
    return f.card && f.card.page ? f.card.page : null;
  }

  function frac(rect, pg) {
    if (!rect || !pg || !(pg.width_pt > 0) || !(pg.height_pt > 0)) return null;
    return { x: rect[0] / pg.width_pt, y: rect[1] / pg.height_pt, w: (rect[2] - rect[0]) / pg.width_pt, h: (rect[3] - rect[1]) / pg.height_pt };
  }

  /** Clickable regions on one page as fractions of the marked page: the red boxes and the label cards. */
  function hitBoxes(m, page) {
    var pg = pageInfo(m, page);
    if (!pg) return [];
    var out = [];
    m.findings.forEach(function (f) {
      (f.regions || []).forEach(function (g, i) {
        if (g.page !== page) return;
        var fr = frac(g.rect_marked_pt, pg);
        if (fr) out.push({ id: f.id, findingId: f.finding_id, number: f.number, severity: f.severity, title: f.title, kind: 'region', index: i, frac: fr });
      });
      if (f.card && f.card.page === page) {
        var fc = frac(f.card.rect, pg);
        if (fc) out.push({ id: f.id, findingId: f.finding_id, number: f.number, severity: f.severity, title: f.title, kind: 'card', index: 0, frac: fc });
      }
    });
    return out;
  }

  /** Where to look for a flag: a located flag's first region (to zoom to), else its card (page only, no zoom). */
  function focusTarget(m, id) {
    var f = findFlag(m, id);
    if (!f) return null;
    var page = pageOf(m, id);
    if (!page) return null;
    var pg = pageInfo(m, page);
    if (f.location_status === 'located' && f.regions && f.regions.length) {
      var fr = frac(f.regions[0].rect_marked_pt, pg);
      if (fr) return { page: page, frac: fr, zoom: true, status: 'located' };
    }
    return { page: page, frac: f.card ? frac(f.card.rect, pg) : null, zoom: false, status: f.location_status };
  }

  /** A fraction rect of an image fitted into the container -> container pixels (before the viewer's pan/zoom). */
  function fracPx(fr, fit) {
    return { left: fit.x + fr.x * fit.w, top: fit.y + fr.y * fit.h, width: fr.w * fit.w, height: fr.h * fit.h };
  }

  function label(b) {
    return b.id + ' ' + String(b.severity || '').toUpperCase() + ': ' + b.title + (b.kind === 'card' ? ' (label)' : '') + '. Press Enter for details.';
  }

  /** Honest status line for the viewer. Never says "no flags" because markup failed. */
  function banner(m) {
    if (!m) return '';
    if (m.state === 'failed') {
      return 'Engineering flags exist, but the marked PDF could not be generated' + (m.failure && m.failure.code ? ' (' + m.failure.code + ')' : '') +
             '. The flags are still listed in Results.';
    }
    if (m.state === 'stale') return 'The engineering markup belongs to a different revision of this drawing, so it is not shown. Re-run the pipeline to refresh it.';
    if (m.state === 'partial') return m.unlocated + ' of ' + m.count + ' flag' + (m.count === 1 ? '' : 's') + ' could not be placed precisely; they are listed on the page label rail as UNLOCATED.';
    return '';
  }

  return { model: model, usable: usable, exists: exists, autoSelect: autoSelect, findFlag: findFlag, hasFlag: hasFlag, firstPage: firstPage,
           pageInfo: pageInfo, pageOf: pageOf, hitBoxes: hitBoxes, focusTarget: focusTarget, fracPx: fracPx, label: label, banner: banner };
});
