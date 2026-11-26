/* Projects: parts of this session, folder upload, Run All Parts, all runs, Clear all models. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  McA.pages = McA.pages || {};
  var $ = function (id) { return document.getElementById(id); };
  var h = function () { return McA.dom.h.apply(null, arguments); };
  var BATCH = { queued: 'Queued', running: 'Running', succeeded: 'Succeeded', succeeded_with_warnings: 'Review flags', failed: 'Failed', cancelled: 'Cancelled' };

  function empty(icon, title, text, extra) {
    return h('div', { class: 'empty' }, h('span', { class: 'empty-ic' }, McA.icons.get(icon, 30)), h('p', { class: 'empty-t', text: title }), h('p', { class: 'empty-d', text: text }), extra);
  }
  function statusChip(p, batch) {
    var r = batch.results && batch.results[p.name];
    if (r && BATCH[r.state]) return h('span', { class: 'badge-c ' + (r.state === 'failed' ? 'err' : r.state === 'succeeded' ? 'ok' : r.state === 'succeeded_with_warnings' ? 'warn' : ''), text: BATCH[r.state] });
    return h('span', { class: 'badge-c' + (p.has_output ? ' steel' : ''), text: p.has_output ? 'Has output' : 'Not run' });
  }
  /* The preview is the first page of the ORIGINAL drawing (rendered server-side from the PDF, or the image itself),
     shown whole on a neutral canvas so title blocks and dimensions are never cropped. Order of attempts: real preview,
     the saved JPEG thumbnail, then a labelled fallback icon. Loading and failure are both visible states. */
  function previewButton(p, sess) {
    var th = h('button', { class: 'pcard-th is-loading', type: 'button', 'aria-label': 'Open ' + p.name, 'data-state': 'loading' }, McA.icons.get('file', 30));
    th.addEventListener('click', function () { McA.openPart(sess, p.name); });
    var tried = 0;
    var urls = [];
    if (p.has_original !== false) urls.push(McA.api.previewURL(sess, p.name, p.last_activity || ''));
    if (p.has_thumb !== false) urls.push(McA.api.thumbURL(sess, p.name, p.last_activity || ''));
    function next() {
      if (tried >= urls.length) {
        th.classList.remove('is-loading'); th.setAttribute('data-state', 'unavailable');
        th.replaceChildren(McA.icons.get('file', 30), h('span', { class: 'pcard-nopv', text: 'Preview unavailable' }));
        th.setAttribute('aria-label', 'Preview unavailable. Open ' + p.name);        // the accessible name must contain the visible text
        return;
      }
      var img = h('img', { alt: 'Drawing preview of ' + p.name, decoding: 'async' });
      img.addEventListener('load', function () { th.classList.remove('is-loading'); th.setAttribute('data-state', tried === 1 ? 'preview' : 'thumbnail'); th.replaceChildren(img); });
      img.addEventListener('error', next);
      img.src = urls[tried++];
    }
    /* Lazy: a preview is requested only when its card is about to scroll into view (a detached <img loading=lazy> never loads). */
    if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (es) { if (es.some(function (e) { return e.isIntersecting; })) { io.disconnect(); next(); } }, { rootMargin: '300px' });
      io.observe(th);
    } else next();
    return th;
  }
  function whenEl(p) {
    var w = McA.projectorder.whenLine(p);
    var t = h('time', { class: 'pcard-when', text: w.primary });
    var iso = McA.projectorder.isoOf(p.last_activity); if (iso) t.setAttribute('datetime', iso);
    return h('div', { class: 'pcard-t' }, t, w.secondary ? h('span', { class: 'pcard-created', text: w.secondary }) : null);
  }
  function partCard(p, sess, batch) {
    var th = previewButton(p, sess);
    var sheets = (p.n_views || 0) + ' image' + (p.n_views === 1 ? '' : 's');
    return h('li', { class: 'pcard' }, th, h('div', { class: 'pcard-b' },
      h('div', { class: 'pcard-n', title: p.name, text: p.name }),
      whenEl(p),
      h('div', { class: 'pcard-m' }, statusChip(p, batch), p.has_output && McA.scorecache ? McA.scorecache.badge(McA.scorecache.get(p.name)) : null, h('span', { class: 'badge-c', text: sheets }),
        p.has_overview ? h('span', { class: 'badge-c', text: 'Overview' }) : null, p.has_marked ? h('span', { class: 'badge-c', text: 'Marked' }) : null,
        p.source_format ? h('span', { class: 'badge-c mono', text: String(p.source_format).toUpperCase() }) : null),
      h('div', { class: 'pcard-a' },
        h('button', { class: 'btn act act-open', type: 'button', text: 'Open', onclick: function () { McA.openPart(sess, p.name); } }),
        p.has_output ? h('button', { class: 'btn act act-gold', type: 'button', text: 'Results', onclick: function () { McA.openPart(sess, p.name, 'results'); } }) : null)));
  }
  function runsTable(runs) {
    var keys = [['extraction', 'Extraction'], ['build_plan', 'Plan'], ['macros', 'VBA'], ['sldprt', 'SLDPRT'], ['stl', 'STL']];
    var rows = runs.map(function (r) {
      var pres = r.present || {};
      return h('tr', null,
        h('td', null, h('strong', { text: r.part })),
        h('td', { class: 'num', text: r.timestamp || McA.dom.fmtTime(r.epoch) }),
        h('td', null, McA.scorecache ? McA.scorecache.badge(McA.scorecache.get(r.part)) : null),
        h('td', null, h('span', { class: 'pres', 'aria-label': 'Files present' }, keys.map(function (k) { return h('span', { class: 'p' + (pres[k[0]] ? ' on' : ''), title: pres[k[0]] ? 'Present' : 'Not present', text: k[1] }); }))),
        h('td', null, h('div', { class: 'acts' },
          h('button', { class: 'btn act act-open', type: 'button', text: 'Open', onclick: function () { McA.openPart(r.session, r.part); } }),
          h('button', { class: 'btn act act-gold', type: 'button', text: 'Results', onclick: function () { McA.router.go('results', { run: r.session + '|' + r.part }); } }))));
    });
    return h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl' },
      h('caption', { class: 'sr-only', text: 'All runs' }),
      h('thead', null, h('tr', null, ['Part', 'Run time', 'Fidelity score', 'Files', 'Actions'].map(function (t) { return h('th', { scope: 'col', text: t }); }))),
      h('tbody', null, rows)));
  }

  function render() {
    var s = McA.store.get(), body = $('proj-body'), sess = s.session.id;
    body.replaceChildren();
    if (s.parts.error) body.append(h('div', { class: 'banner is-err', role: 'alert' }, McA.icons.get('warn', 18), 'Could not load parts: ' + s.parts.error));
    body.append(h('h2', { class: 'sec-h', text: 'Parts in this session' }));
    if (!s.parts.list.length) {
      body.append(empty('folder', 'No parts in this session', 'Upload a drawing from Home, or upload a folder of parts. Parts from earlier sessions that have not been run are not listed.', h('a', { class: 'btn secondary sm', href: '#/home', text: 'Go to Home' })));
    } else body.append(h('ul', { class: 'pgrid' }, McA.projectorder.sortParts(s.parts.list).map(function (p) { return partCard(p, sess, s.batch); })));
    body.append(h('h2', { class: 'sec-h', text: 'All runs' }));
    var runs = (s.history.runs || []).slice().sort(function (a, b) { return (b.epoch || 0) - (a.epoch || 0); });
    if (s.history.error) body.append(h('div', { class: 'banner is-err', role: 'alert' }, McA.icons.get('warn', 18), 'Could not load run history: ' + s.history.error));
    else if (!runs.length) body.append(empty('recent', 'No runs yet', 'Runs appear here once the pipeline has produced output for a part.'));
    else body.append(runsTable(runs));

    var runnable = s.parts.list.length;
    var reason = !s.server.reachable ? 'Server unreachable.' : s.run.state === 'running' || s.run.state === 'queued' ? 'A run is in progress.' : !s.server.live ? ((s.server.keyName || 'The extraction API key') + ' is not set on the server. Run All Parts makes paid API calls.') : !runnable ? 'No saved parts.' : '';
    var btn = $('proj-runall'); btn.setAttribute('aria-disabled', String(!!reason)); $('proj-runall-why').textContent = reason;
    var failed = Object.keys((s.batch && s.batch.results) || {}).filter(function (k) { return s.batch.results[k].state === 'failed'; });
    var rb = $('proj-retry');
    if (rb) {
      var busy = s.run.state === 'running' || s.run.state === 'queued' || (s.batch && s.batch.active);
      rb.hidden = !failed.length;
      rb.textContent = 'Retry failed (' + failed.length + ')';
      rb.setAttribute('aria-disabled', String(!!busy));
      rb.title = busy ? 'A run is in progress.' : 'Re-run only the parts that failed. Successful parts are not run again.';
    }
  }

  function clearAll() {
    var n = McA.store.get().history.runs.length;
    return McA.dialog.confirm('Clear all models?', 'This deletes the saved output of ' + n + ' run' + (n === 1 ? '' : 's') + ' from this machine. It cannot be undone. Saved parts and drawings are not removed.', 'Clear all models', true).then(function (ok) {
      if (!ok) return;
      return McA.api.clearHistory().then(function (r) {
        var errs = (r && r.errors && r.errors.length) || 0;
        McA.toast.show('Removed ' + ((r && r.removed) || 0) + ' item(s)' + (errs ? ', ' + errs + ' could not be removed.' : '.'), errs ? 'warn' : 'ok');
        return McA.api.runHistory().then(function (x) { McA.store.dispatch('history/loaded', { runs: x.runs || [] }); });
      }).catch(function (e) { McA.toast.show('Could not clear models: ' + (e && e.detail || e.message || e), 'err'); });
    });
  }
  McA.clearAllModels = clearAll;

  McA.pages.projects = {
    init: function () {
      var more = $('proj-more'), menu = $('proj-menu');
      var setMenu = function (o) { menu.hidden = !o; more.setAttribute('aria-expanded', String(o)); if (o) $('proj-clear').focus(); };
      more.addEventListener('click', function () { setMenu(menu.hidden); });
      menu.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.stopPropagation(); setMenu(false); more.focus(); } });
      document.addEventListener('click', function (e) { if (!menu.hidden && !e.target.closest('#proj-menu, #proj-more')) setMenu(false); });
      $('proj-clear').addEventListener('click', function () { setMenu(false); clearAll(); });
      var folder = $('proj-folder');
      folder.addEventListener('change', function () {
        var list = Array.prototype.slice.call(folder.files); folder.value = '';
        if (!list.length) return;
        if (!McA.store.has('intake/folder')) { McA.toast.show('Folder upload is not available in this build.', 'err'); return; }
        McA.dom.dispatch('intake/folder', { files: list, source: 'projects' });
      });
      var retry = $('proj-retry');
      if (retry) retry.addEventListener('click', function (e) {
        if (e.currentTarget.getAttribute('aria-disabled') === 'true') return;
        if (!McA.store.has('batch/retry')) { McA.toast.show('The batch runner is not available in this build.', 'err'); return; }
        McA.dom.dispatch('batch/retry');
      });
      $('proj-runall').addEventListener('click', function (e) {
        if (e.currentTarget.getAttribute('aria-disabled') === 'true') return;
        if (!McA.store.has('batch/request')) { McA.toast.show('The batch runner is not available in this build.', 'err'); return; }
        McA.dom.dispatch('batch/request');
      });
      ['parts', 'history', 'batch', 'server'].forEach(function (k) { McA.store.subscribe(function (s) { return s[k]; }, render); });
      if (McA.scorecache) McA.scorecache.onChange(render);
      McA.store.subscribe(function (s) { return s.run.state; }, render);
      render();
    },
    enter: render,
  };
})();
