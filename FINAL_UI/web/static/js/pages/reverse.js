/* 3D -> 2D page (#/reverse): SOLIDWORKS part(s) in, native drawing out. Everything shown comes from GET /api/reverse/*; presentation rules live in
   logic/reverseview.js. No placeholder files, no invented numbers: a viewer shows a file only when the server lists it. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  McA.pages = McA.pages || {};
  var h = function () { return McA.dom.h.apply(null, arguments); };
  var V = function () { return McA.reverseview; };
  var icon = function (n, s) { return McA.icons.get(n, s || 16); };

  var TABS = [['overview', 'Overview'], ['inventory', 'Geometry Inventory'], ['plan', 'Drawing Plan'], ['coverage', 'Dimensions & Coverage'], ['review', 'Engineering Review'],
    ['verification', 'Verification'], ['files', 'Files'], ['logs', 'Logs']];
  var S = {
    status: null, profiles: [], templates: [], defaultId: null, task: null, estimate: null, jobs: [], jobId: '', partId: '', job: null, loadErr: '', loading: false,
    picked: [], recursive: false, templateId: '', profile: 'us_third_angle_inch', config: '', submitting: false, setupOpen: true, resultsOpen: true, tab: 'overview',
    events: [], eventsNext: 0, sessionJobs: [], notice: null, review: {}, artifacts: {}, logScope: 'part', overlay: false, inited: false, visible: false,
    view: {}, sync: false, caps: null
  };
  var R = {};                     // element refs
  var rail = null;                // McA.reverseRail (setup rail, reference flow, export)
  var timer = null, taskTimer = null, lastSummary = {}, guard = null;
  var viewKey = '', loadedStl = '', loadedPdf = '', loadedSrc = '', stlState = { status: 'empty', msg: '' }, pdfState = { status: 'empty', msg: '' };

  /* ───────────────────────── API ───────────────────────── */
  function call(url, init) {
    return fetch(url, init).catch(function () { throw { status: 0, detail: 'The server could not be reached.' }; }).then(function (res) {
      if (res.ok) return res.json();
      return res.text().then(function (t) {
        var d = ''; try { var j = JSON.parse(t); d = typeof j.detail === 'string' ? j.detail : (Array.isArray(j.detail) ? j.detail.map(function (x) { return x.msg; }).join('; ') : ''); } catch (e) { /* not JSON */ }
        throw { status: res.status, detail: d || res.statusText || ('HTTP ' + res.status) };
      });
    });
  }
  var enc = encodeURIComponent;
  function encPath(rel) { return String(rel).split('/').map(enc).join('/'); }
  function fileURL(jobId, rel, bytes) { return '/api/reverse/jobs/' + enc(jobId) + '/files/' + encPath(rel) + (bytes !== undefined ? '?v=' + bytes : ''); }
  var API = {
    status: function () { return call('/api/reverse/status'); },
    profiles: function () { return call('/api/reverse/profiles'); },
    templates: function () { return call('/api/reverse/templates'); },
    estimate: function (n) { return call('/api/reverse/estimate?parts=' + n); },
    jobs: function () { return call('/api/reverse/jobs'); },
    job: function (id) { return call('/api/reverse/jobs/' + enc(id)); },
    events: function (id, after) { return call('/api/reverse/jobs/' + enc(id) + '/events?after=' + after); },
    cancel: function (id) { return call('/api/reverse/jobs/' + enc(id) + '/cancel', { method: 'POST' }); },
    retry: function (id, ids) { return call('/api/reverse/jobs/' + enc(id) + '/retry', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(ids ? { part_ids: ids } : {}) }); },
    del: function (id) { return call('/api/reverse/jobs/' + enc(id), { method: 'DELETE' }); },
    review: function (id, part, body) { return call('/api/reverse/jobs/' + enc(id) + '/parts/' + enc(part) + '/review', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); },
    submit: function (fd) { return call('/api/reverse/jobs', { method: 'POST', body: fd }); },
    submitFolder: function (o) { return call('/api/reverse/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(o) }); },
    uploadTemplate: function (file) { var fd = new FormData(); fd.append('file', file, file.name); return call('/api/reverse/templates', { method: 'POST', body: fd }); },
    generateTemplate: function (key) { return call('/api/reverse/templates/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: key }) }); },
    artifact: function (jobId, rel, bytes) { return call(fileURL(jobId, rel, bytes)); },
    caps: function () { return call('/api/reverse/capabilities'); },
    stage: function (fd) { return call('/api/reverse/stage', { method: 'POST', body: fd }); },
    dropStage: function (id) { return call('/api/reverse/stage/' + enc(id), { method: 'DELETE' }); },
    candidates: function (o) { return call('/api/reverse/reference/candidates', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(o) }); },
    confirm: function (o) { return call('/api/reverse/reference/confirm', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(o) }); },
    uploadReference: function (file) { var fd = new FormData(); fd.append('file', file, file.name); return call('/api/reverse/reference/upload', { method: 'POST', body: fd }); },
    exportInfo: function (jobId, partId) { return call('/api/reverse/jobs/' + enc(jobId) + '/parts/' + enc(partId) + '/export'); }
  };
  function errText(e) { return (e && (e.detail || e.message)) || 'Something went wrong.'; }
  function announce(t) { var n = document.getElementById('status-live'); if (n) n.textContent = t; }

  /* ───────────────────────── small DOM helpers ───────────────────────── */
  function badge(info, extra) {
    return h('span', { class: 'badge-c rv-badge ' + (info.kind || '') + (extra ? ' ' + extra : ''), 'data-tone': info.tone || 'none' }, icon(info.icon, 13), h('span', { text: info.label }));
  }
  function pill(sev) {
    var i = V().severityInfo(sev);
    return h('span', { class: 'rv-sev rv-sev-' + (V().severityInfo(sev).rank <= 5 ? sev : 'info') }, icon(i.icon, 13), h('span', { text: i.label }));
  }
  function empty(ic, title, text) {
    return h('div', { class: 'rv-empty' }, h('span', { class: 'empty-ic' }, icon(ic, 28)), h('p', { class: 'empty-t', text: title }), text ? h('p', { class: 'empty-d', text: text }) : null);
  }
  function banner(kind, text, extra) {
    return h('div', { class: 'banner is-' + kind, role: kind === 'err' ? 'alert' : 'status' }, icon(kind === 'err' || kind === 'warn' ? 'warn' : 'info', 18), h('span', { class: 'rv-banner-t', text: text }), extra || null);
  }
  function fmtBytes(n) { return McA.util && McA.util.fmtBytes ? McA.util.fmtBytes(n) : n + ' B'; }
  function fmtWhen(iso) { var d = new Date(iso); return isNaN(d) ? '' : d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }); }
  function part() { return S.job && S.job.parts ? S.job.parts.filter(function (p) { return p.part_id === S.partId; })[0] || null : null; }
  function renderSetup() { if (rail) rail.render(); }
  function renderRunButtons() { if (rail) rail.renderRunButtons(); }
  function reasonBtn(btn, reason, reasonEl) {
    btn.disabled = !!reason; btn.title = reason || '';
    if (reasonEl) { reasonEl.textContent = reason || ''; reasonEl.hidden = !reason; }
  }

  /* ───────────────────────── data flow ───────────────────────── */
  function loadStatic() {
    API.status().then(function (s) { S.status = s; renderHeader(); renderSetup(); }, function () { S.status = null; });
    API.profiles().then(function (r) { S.profiles = r.profiles || []; renderSetup(); }, function () { /* the select stays empty with a visible note */ renderSetup(); });
    API.caps().then(function (c) { S.caps = c; renderSetup(); }, function () { S.caps = { reference: false, candidates: false, upload: false, confirm: false, export: true }; renderSetup(); });
    loadTemplates();
    refreshJobs();
  }
  function loadTemplates() {
    return API.templates().then(function (r) {
      S.templates = r.templates || []; S.defaultId = r.default_id; S.task = r.task || null;
      if (!S.templateId || !S.templates.some(function (t) { return t.id === S.templateId; })) S.templateId = S.defaultId || (S.templates[0] && S.templates[0].id) || '';
      renderSetup();
      if (S.task && S.task.state === 'running' && !taskTimer) taskTimer = setTimeout(function () { taskTimer = null; loadTemplates(); }, 2000);
    }, function (e) { S.templates = []; S.tplErr = errText(e); renderSetup(); });
  }
  function refreshJobs() {
    return API.jobs().then(function (r) {
      S.jobs = r.jobs || []; S.jobsErr = '';
      renderQueueBar();
      if (!S.jobId && S.jobs.length) selectJob(S.jobs[0].job_id, '');
      else if (!S.jobs.length) renderAll();
    }, function (e) { S.jobsErr = errText(e); renderQueueBar(); });
  }
  function selectJob(jobId, partId) {
    if (S.jobId !== jobId) { S.job = null; S.events = []; S.eventsNext = 0; S.artifacts = {}; }
    S.jobId = jobId; S.partId = partId || S.partId; S.loading = true; S.loadErr = '';
    renderAll();
    return API.job(jobId).then(function (j) {
      if (S.jobId !== jobId) return;
      applyJob(j, partId);
    }, function (e) {
      if (S.jobId !== jobId) return;
      S.loading = false; S.job = null; S.loadErr = errText(e); renderAll();
    });
  }
  function applyJob(j, wantPart) {
    var prev = S.job;
    S.job = j; S.loading = false; S.loadErr = '';
    var ids = (j.parts || []).map(function (p) { return p.part_id; });
    if (wantPart && ids.indexOf(wantPart) >= 0) S.partId = wantPart;
    else if (ids.indexOf(S.partId) < 0) {
      var pick = (j.parts || []).filter(function (p) { return p.state === 'review_required'; })[0] || (j.parts || [])[0];
      S.partId = pick ? pick.part_id : '';
    }
    if (prev && prev.job_id === j.job_id) (j.parts || []).forEach(function (p) {
      var o = (prev.parts || []).filter(function (x) { return x.part_id === p.part_id; })[0];
      if (o && o.state !== p.state && V().isTerminal(p.state)) announce(p.name + ': ' + V().partStateInfo(p.state).label);
    });
    renderAll();
    pollEvents();
    schedulePoll();
  }
  function schedulePoll() {
    clearTimeout(timer); timer = null;
    if (!S.visible || !S.job || !V().isActive(S.job.summary_state)) return;
    var id = S.jobId;
    timer = setTimeout(function () {
      if (document.hidden) { schedulePoll(); return; }
      API.job(id).then(function (j) { if (S.jobId === id) { var was = S.job && S.job.summary_state; applyJob(j); if (was !== j.summary_state) refreshJobs(); } }, function () { schedulePoll(); });
    }, 1500);
  }
  function pollEvents() {
    if (!S.jobId || S.tab !== 'logs') return;
    var id = S.jobId;
    API.events(id, S.eventsNext).then(function (r) {
      if (S.jobId !== id) return;
      S.events = V().mergeEvents(S.events, r.events || []); S.eventsNext = r.next || S.eventsNext;
      if (S.tab === 'logs') renderResults();
    }, function () { /* the Logs tab shows what it has */ });
  }

  /* ───────────────────────── header, tracker ───────────────────────── */
  function chip(id, ic, key) {
    return h('div', { class: 'chip rv-chip', id: id }, h('span', { class: 'chip-ic' }, icon(ic, 20)), h('span', { class: 'chip-body' }, h('span', { class: 'chip-k', text: key }), h('span', { class: 'chip-v', 'data-v': '' })));
  }
  function setChip(id, text, title) { var n = R.root.querySelector('#' + id + ' .chip-v'); if (n) { n.textContent = text; n.title = title || ''; } }
  function renderHeader() {
    var p = part(), j = S.job;
    R.sub.textContent = j ? [p ? p.name : '', p && p.config ? p.config : '', 'Job ' + j.job_id.slice(-6)].filter(Boolean).join(' · ') : 'No run selected';
    setChip('rv-chip-engine', V().engineText(j, S.status));
    var d = R.root.querySelector('#rv-chip-deliv .chip-v'); d.replaceChildren();
    var src = V().viewerSources(p);
    var files = (p && p.files) || {};
    [['PDF', !!src.pdf, 'Drawing (PDF)'], ['SLDDRW', !!files['drawing.slddrw'], 'Native drawing'], ['STL', !!src.stl, 'Model (STL)']].forEach(function (x) {
      d.append(h('span', { class: 'dv' + (x[1] ? ' is-present' : ''), title: x[1] ? x[2] + ' produced' : x[2] + ' not produced yet', text: x[0] }));
    });
    setChip('rv-chip-runtime', j ? (V().runtimeText(j.parts) || 'Not measured yet') : '—');
    setChip('rv-chip-cost', j ? V().costText(j) : '—');
  }
  var STATE_ICON = { succeeded: 'check', warning: 'warn', failed: 'x', skipped: 'dash', na: 'dash' };
  function renderTracker() {
    var p = part(), j = S.job, nodes = V().stageStates(p, j);
    R.steps.replaceChildren();
    nodes.forEach(function (n) {
      var li = h('li', { class: 'trk-step', 'data-stage': n.id, 'data-state': n.state }, h('span', { class: 'trk-node', 'aria-hidden': 'true' }, STATE_ICON[n.state] ? icon(STATE_ICON[n.state], 14) : null),
        h('span', { class: 'trk-label', text: n.label }), h('span', { class: 'sr-only', text: ': ' + V().stateWord(n.state) + (n.seconds !== null ? ', ' + n.seconds + ' seconds' : '') }));
      if (n.errors.length || n.warnings.length) li.title = n.errors.concat(n.warnings).join('; ');
      R.steps.append(li);
    });
    R.stage.textContent = p ? V().stageCaption(p, j) : (j ? 'No part selected' : 'Not started');
    var pc = j ? V().percent(j.progress, j.summary_state) : null;
    R.progText.textContent = j ? V().progressText(j.progress, j.summary_state) : '';
    R.bar.hidden = pc === null;
    if (pc !== null) { R.bar.setAttribute('aria-valuenow', String(pc)); R.bar.setAttribute('aria-valuetext', R.progText.textContent); R.barFill.style.width = pc + '%'; }
  }

  /* ───────────────────────── viewers: 3D (three.js) ───────────────────────── */
  var T = { inited: false, failed: false, renderer: null, scene: null, camera: null, controls: null, mesh: null, grid: null, radius: 100, anim: null, view: 'Isometric', pan: false, resize: false };
  var DIRS = { Isometric: [1.4, 1.1, 1.8], Front: [0, 0, 1], Top: [0, 1, 0.001], Right: [1, 0, 0] };
  function tok(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function init3d() {
    if (T.inited || T.failed) return T.inited;
    if (typeof THREE === 'undefined' || !THREE.STLLoader || !THREE.OrbitControls) { T.failed = true; return false; }
    try {
      T.scene = new THREE.Scene();
      T.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100000);
      T.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      T.renderer.setClearColor(0x000000, 0);
      T.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      R.canvasWrap.appendChild(T.renderer.domElement);
      T.controls = new THREE.OrbitControls(T.camera, T.renderer.domElement);
      T.controls.enableDamping = true; T.controls.dampingFactor = 0.08;
      T.scene.add(new THREE.HemisphereLight(new THREE.Color(tok('--ink-2')), new THREE.Color(tok('--bg')), 0.7));
      var key = new THREE.DirectionalLight(new THREE.Color(tok('--ink')), 0.9); key.position.set(1, 1, 1); T.scene.add(key);
      var rim = new THREE.DirectionalLight(new THREE.Color(tok('--ink-2')), 0.35); rim.position.set(-1, 0.4, -0.8); T.scene.add(rim);
      new ResizeObserver(function () { T.resize = true; }).observe(R.canvasWrap);
      T.inited = true; sizeStl(); loop3d();
    } catch (e) { T.failed = true; T.inited = false; return false; }
    return true;
  }
  function sizeStl() { if (!T.inited) return; var w = R.canvasWrap.clientWidth || 1, hh = R.canvasWrap.clientHeight || 1; T.renderer.setSize(w, hh, false); T.camera.aspect = w / hh; T.camera.updateProjectionMatrix(); }
  function loop3d() {
    requestAnimationFrame(loop3d);
    if (document.hidden || !R.canvasWrap.offsetParent) return;
    if (T.resize) { sizeStl(); T.resize = false; }
    if (T.anim) { var t = Math.min(1, (performance.now() - T.anim.t0) / T.anim.ms), k = 1 - Math.pow(1 - t, 3); T.camera.position.lerpVectors(T.anim.from, T.anim.to, k); if (t >= 1) T.anim = null; }
    T.controls.update(); T.renderer.render(T.scene, T.camera);
  }
  function clear3d() {
    if (!T.inited) return;
    if (T.mesh) { T.scene.remove(T.mesh); T.mesh.geometry.dispose(); T.mesh.material.dispose(); T.mesh = null; }
    if (T.grid) { T.scene.remove(T.grid); if (T.grid.geometry) T.grid.geometry.dispose(); T.grid = null; }
  }
  function distance3d() { var v = T.camera.fov * Math.PI / 180, hf = 2 * Math.atan(Math.tan(v / 2) * (T.camera.aspect || 1)); return T.radius / Math.sin(Math.min(v, hf) / 2) * 1.12; }
  function moveCamera(dir) {
    if (!T.mesh) return;
    var d = new THREE.Vector3(dir[0], dir[1], dir[2]).normalize().multiplyScalar(distance3d());
    T.controls.target.set(0, 0, 0);
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) { T.camera.position.copy(d); T.anim = null; }
    else T.anim = { from: T.camera.position.clone(), to: d, t0: performance.now(), ms: 260 };
  }
  function showMesh(buf) {
    var geo = new THREE.STLLoader().parse(buf);
    var n = geo.attributes && geo.attributes.position ? geo.attributes.position.count : 0;
    if (!n) throw new Error('The STL file contains no triangles.');
    geo.computeBoundingBox();
    var bb = geo.boundingBox, c = new THREE.Vector3(), size = new THREE.Vector3(); bb.getCenter(c); bb.getSize(size);
    if (!isFinite(size.x + size.y + size.z)) throw new Error('The STL file has invalid coordinates.');
    geo.translate(-c.x, -c.y, -c.z); geo.computeBoundingSphere(); geo.computeVertexNormals();
    var maxDim = Math.max(size.x, size.y, size.z) || 100;
    T.radius = (geo.boundingSphere && geo.boundingSphere.radius) || maxDim / 2;
    T.camera.near = maxDim / 100; T.camera.far = maxDim * 100; T.camera.updateProjectionMatrix();
    clear3d();
    T.mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: new THREE.Color(tok('--model-mesh')), metalness: 0.45, roughness: 0.5 }));
    T.scene.add(T.mesh);
    T.grid = new THREE.GridHelper(maxDim * 3, 20, new THREE.Color(tok('--model-grid')), new THREE.Color(tok('--model-grid-2'))); T.grid.position.y = -size.y / 2; T.scene.add(T.grid);
    T.view = 'Isometric'; R.viewSel.value = 'Isometric'; moveCamera(DIRS.Isometric);
    return { triangles: n / 3, size: [size.x, size.y, size.z] };
  }
  function setStl(status, msg) { stlState = { status: status, msg: msg || '' }; renderStlOverlay(); }
  function renderStlOverlay() {
    var s = stlState, p = part(), box = R.stlEmpty;
    box.replaceChildren();
    R.stlRetry = null;
    var showing = s.status === 'ready';
    box.hidden = showing;
    ['rv-stl-tools'].forEach(function () { R.stlTools.querySelectorAll('button,select').forEach(function (b) { b.disabled = !showing; }); });
    if (showing) return;
    if (s.status === 'loading') box.append(h('span', { class: 'rv-spin' }, icon('spinner', 24)), h('p', { class: 'empty-t', text: 'Loading model...' }));
    else if (s.status === 'error') {
      R.stlRetry = h('button', { class: 'btn secondary sm', type: 'button', text: 'Retry', onclick: function () { loadedStl = ''; syncViewers(); } });
      box.append(icon('warn', 26), h('p', { class: 'empty-t', text: 'The model could not be shown' }), h('p', { class: 'empty-d', text: s.msg }), R.stlRetry);
    } else {
      var why = !p ? 'Select a part, or start a run.' : p.state === 'failed' ? 'The run failed before the STL was exported.' : p.state === 'canceled' ? 'The run was canceled before the STL was exported.' : 'The STL is exported in the second stage of the run.';
      box.append(icon('cube', 28), h('p', { class: 'empty-t', text: 'No model yet' }), h('p', { class: 'empty-d', text: why }));
    }
  }

  /* ───────────────────────── viewers: PDF (pdf.js) ───────────────────────── */
  var P = { doc: null, page: 1, zoom: 1, task: null, rendering: false, again: false };
  function setPdf(status, msg) { pdfState = { status: status, msg: msg || '' }; renderPdfOverlay(); }
  function renderPdfOverlay() {
    var s = pdfState, p = part(), box = R.pdfEmpty;
    box.replaceChildren();
    var showing = s.status === 'ready';
    box.hidden = showing; R.paperWrap.hidden = !showing;
    R.pdfTools.querySelectorAll('button').forEach(function (b) { if (!b.hasAttribute('data-always')) b.disabled = !showing; });
    R.pdfDl.setAttribute('aria-disabled', showing ? 'false' : 'true');
    R.pdfOverlayBtn.disabled = !(p && (p.issues || []).length);
    if (showing) return;
    if (s.status === 'loading') box.append(h('span', { class: 'rv-spin' }, icon('spinner', 24)), h('p', { class: 'empty-t', text: 'Loading drawing...' }));
    else if (s.status === 'error') box.append(icon('warn', 26), h('p', { class: 'empty-t', text: 'The drawing could not be shown' }), h('p', { class: 'empty-d', text: s.msg }),
      h('button', { class: 'btn secondary sm', type: 'button', text: 'Retry', onclick: function () { loadedPdf = ''; syncViewers(); } }));
    else box.append(icon('file', 28), h('p', { class: 'empty-t', text: 'No drawing yet' }), h('p', { class: 'empty-d', text: V().drawingStatus(p).label + '. The drawing appears here once the run publishes it.' }));
  }
  function pdfjs() { return typeof pdfjsLib !== 'undefined' ? pdfjsLib : null; }
  function loadPdf(url, tokn, key) {
    var lib = pdfjs();
    if (!lib) { setPdf('error', 'The PDF reader did not load.'); return; }
    if (lib.GlobalWorkerOptions) lib.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.js';
    setPdf('loading');
    lib.getDocument(url).promise.then(function (doc) {
      if (!guard.isCurrent(tokn) || viewKey !== key.split('#')[0]) { doc.destroy && doc.destroy(); return; }
      if (P.doc && P.doc.destroy) P.doc.destroy();
      P.doc = doc; P.page = 1; P.zoom = 1; loadedPdf = key; setPdf('ready'); renderPage(); updateSyncBtn();
    }, function (e) { if (guard.isCurrent(tokn)) { loadedPdf = ''; setPdf('error', 'The PDF could not be read (' + ((e && e.message) || 'unknown error') + ').'); } });
  }
  function clearPdf() {
    if (P.task) { try { P.task.cancel(); } catch (e) { /* ignore */ } P.task = null; }
    if (P.doc && P.doc.destroy) { try { P.doc.destroy(); } catch (e) { /* ignore */ } }
    P.doc = null; var c = R.paper.getContext('2d'); c.clearRect(0, 0, R.paper.width, R.paper.height); R.paper.width = R.paper.height = 0;
  }
  function renderPage() {
    if (!P.doc) return;
    if (P.rendering) { P.again = true; return; }
    P.rendering = true;
    var doc = P.doc, n = P.page;
    doc.getPage(n).then(function (pg) {
      if (doc !== P.doc) { P.rendering = false; return; }
      var v1 = pg.getViewport({ scale: 1 }), box = R.paperWrap, aw = Math.max(80, box.clientWidth - 24), ah = Math.max(80, box.clientHeight - 24);
      var fit = Math.min(aw / v1.width, ah / v1.height) || 1, scale = fit * P.zoom, dpr = Math.min(window.devicePixelRatio || 1, 2);
      var vp = pg.getViewport({ scale: scale * dpr });
      R.paper.width = Math.floor(vp.width); R.paper.height = Math.floor(vp.height);
      R.paper.style.width = Math.floor(vp.width / dpr) + 'px'; R.paper.style.height = Math.floor(vp.height / dpr) + 'px';
      var ctx = R.paper.getContext('2d');
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, R.paper.width, R.paper.height);
      P.task = pg.render({ canvasContext: ctx, viewport: vp });
      return P.task.promise.then(function () { P.task = null; });
    }).catch(function (e) { if (e && e.name === 'RenderingCancelledException') return; setPdf('error', 'The page could not be drawn.'); })
      .then(function () {
        P.rendering = false;
        R.pageLbl.textContent = P.doc ? 'Sheet ' + P.page + ' of ' + P.doc.numPages : '';
        R.zoomLbl.textContent = Math.round(P.zoom * 100) + '%';
        R.prevBtn.disabled = !P.doc || P.page <= 1; R.nextBtn.disabled = !P.doc || P.page >= P.doc.numPages;
        renderOverlay();
        if (P.again) { P.again = false; renderPage(); }
      });
  }
  function renderOverlay() {
    var p = part(), box = R.overlayBox;
    box.hidden = !S.overlay || pdfState.status !== 'ready';
    box.replaceChildren();
    if (box.hidden) return;
    var list = V().sortIssues((p && p.issues) || []).filter(function (i) { return i.sheet === null || i.sheet === undefined || i.sheet === '' || Number(i.sheet) === P.page; });
    box.append(h('p', { class: 'rv-ov-h', text: 'Review overlay (separate from the drawing; the PDF itself stays clean). Issues for sheet ' + P.page + ':' }));
    if (!list.length) box.append(h('p', { class: 'reason', text: 'No issues are recorded for this sheet.' }));
    list.forEach(function (i) { box.append(h('div', { class: 'rv-ov-i' }, pill(i.severity), h('span', { text: ' ' + V().issueLocation(i) + ': ' + i.message }))); });
  }

  /* Atomic switch: any change of job/part clears BOTH viewers first, then loads what exists, guarded by one request token. */
  function syncViewers() {
    var p = part(), j = S.job;
    var key = j && p ? j.job_id + '|' + p.part_id : '';
    var src = V().viewerSources(p);
    if (key !== viewKey) {
      if (viewKey && S.view[viewKey] && R.srcPane.isReady()) S.view[viewKey].src = R.srcPane.getView();      // remember this part's source page / zoom, then reset everything
      viewKey = key; guard.next(); loadedStl = ''; loadedPdf = ''; loadedSrc = '';
      clear3d(); clearPdf(); R.srcPane.clear(); stlState = { status: 'empty', msg: '' }; pdfState = { status: 'empty', msg: '' };
    }
    var tokn = guard.current();
    var sk = V().viewerKey(j && j.job_id, p && p.part_id, src.stl), pk = V().viewerKey(j && j.job_id, p && p.part_id, src.pdf);
    if (!src.stl && loadedStl) { loadedStl = ''; clear3d(); setStl('empty'); }
    if (!src.pdf && loadedPdf) { loadedPdf = ''; clearPdf(); setPdf('empty'); }
    if (src.stl && sk !== loadedStl && stlState.status !== 'loading') {
      if (!init3d()) setStl('error', T.failed ? 'WebGL or the 3D library is not available in this browser.' : '');
      else {
        setStl('loading');
        fetch(fileURL(j.job_id, src.stl.rel, src.stl.bytes)).then(function (res) { if (!res.ok) throw new Error('HTTP ' + res.status); return res.arrayBuffer(); }).then(function (buf) {
          if (!guard.isCurrent(tokn) || viewKey !== key) return;
          try { showMesh(buf); loadedStl = sk; setStl('ready'); } catch (e) { setStl('error', e.message || 'The STL could not be parsed.'); }
        }, function (e) { if (guard.isCurrent(tokn) && viewKey === key) setStl('error', 'The STL could not be downloaded (' + (e && e.message) + ').'); });
      }
    } else if (!src.stl && stlState.status !== 'empty') setStl('empty');
    else renderStlOverlay();
    if (src.pdf && pk !== loadedPdf && pdfState.status !== 'loading') loadPdf(fileURL(j.job_id, src.pdf.rel, src.pdf.bytes), tokn, key + '#' + pk);
    else if (!src.pdf && pdfState.status !== 'empty') setPdf('empty');
    else renderPdfOverlay();
    syncLeft();
    // panel headers
    var prev = j && V().isPreviousRun(j, S.sessionJobs) && V().isTerminal(p ? p.state : '');
    R.stlBadges.replaceChildren.apply(R.stlBadges, [
      p && p.config ? h('span', { class: 'badge-c', title: 'Configuration', text: 'Config: ' + p.config }) : (p ? h('span', { class: 'badge-c', title: 'No configuration was requested; the active saved configuration is used', text: 'Config: active' }) : null),
      prev && src.stl ? h('span', { class: 'badge-c steel', text: 'Previous run' }) : null].filter(Boolean));
    var ds = V().drawingStatus(p);
    R.pdfBadges.replaceChildren.apply(R.pdfBadges, [h('span', { class: 'badge-c rv-draft', 'data-tone': ds.tone, title: V().DRAFT_NOTICE }, icon(ds.tone === 'red' ? 'x' : 'info', 13), h('span', { text: ds.label })),
      prev && src.pdf ? h('span', { class: 'badge-c steel', text: 'Previous run' }) : null].filter(Boolean));
    R.root.querySelector('#rv-gen-lbl').hidden = !src.pdf;
    R.pdfDl.href = src.pdf && j ? fileURL(j.job_id, src.pdf.rel) : '#';
    R.pdfDl.setAttribute('download', p ? p.part_id + '-drawing.pdf' : 'drawing.pdf');
  }

  /* ───────────────────────── left viewer: 3D model | source PDF ───────────────────────── */
  function leftKey() { var j = S.job, p = part(); return j && p ? j.job_id + '|' + p.part_id : ''; }
  function viewFor(key) { return S.view[key] || (S.view[key] = { mode: '3d', src: null }); }
  function leftMode() { var k = leftKey(); return k && viewFor(k).mode === 'source' && McA.referenceview.sourceView(part()).available ? 'source' : '3d'; }
  function setLeftMode(mode) {
    var k = leftKey(); if (!k) return;
    if (mode === 'source' && !McA.referenceview.sourceView(part()).available) return;
    viewFor(k).mode = mode;
    syncViewers(); T.resize = true;
    var b = document.getElementById(mode === 'source' ? 'rv-left-src' : 'rv-left-3d'); if (b) b.focus();
  }
  /** Brings the left panel in line with the selected part + mode: which layer shows, which tools, which label, and (only when needed) loads the source PDF. */
  function syncLeft() {
    var F = McA.referenceview, p = part(), j = S.job, sv = F.sourceView(p), mode = leftMode(), key = leftKey();
    var seg3 = document.getElementById('rv-left-3d'), segS = document.getElementById('rv-left-src');
    seg3.className = mode === '3d' ? 'on' : ''; seg3.setAttribute('aria-pressed', String(mode === '3d'));
    segS.className = mode === 'source' ? 'on' : ''; segS.setAttribute('aria-pressed', String(mode === 'source'));
    segS.setAttribute('aria-disabled', sv.available ? 'false' : 'true');
    segS.title = sv.available ? 'Show the original reference drawing (' + sv.filename + ')' : sv.reason;
    R.stlLayer.hidden = mode === 'source'; R.srcLayer.hidden = mode !== 'source';
    R.stlTools.hidden = mode === 'source'; R.stlBadges.hidden = mode === 'source'; R.srcTools.hidden = mode !== 'source';
    R.leftTitle.textContent = mode === 'source' ? 'Source PDF (Original)' : '3D Model (STL)';
    R.srcProv.hidden = mode !== 'source'; R.srcProv.textContent = mode === 'source' ? 'Original reference. ' + (sv.provenance || sv.filename || '') : '';
    if (mode === 'source') {
      var sk = sv.rel ? key + '|src|' + sv.rel + '|' + sv.bytes : '';
      if (sk !== loadedSrc) { loadedSrc = sk; R.srcPane.load(fileURL(j.job_id, sv.rel, sv.bytes), sk, viewFor(key).src).then(function () { updateSyncBtn(); }); }
    } else if (loadedSrc && !sv.available) { loadedSrc = ''; R.srcPane.clear(); }
    updateSyncBtn();
  }
  function updateSyncBtn() {
    if (!R.syncBtn) return;
    var ok = R.srcPane.isReady() && !!P.doc, same = ok && R.srcPane.numPages() === P.doc.numPages;
    var disabled = !ok || !same;
    R.syncBtn.setAttribute('aria-disabled', disabled ? 'true' : 'false');
    R.syncBtn.setAttribute('aria-pressed', String(!!S.sync && !disabled));
    R.syncBtn.title = !ok ? 'Both drawings must be loaded to synchronise them.' : !same ? 'The sheets do not correspond (' + R.srcPane.numPages() + ' source vs ' + P.doc.numPages + ' generated), so they are not synchronised.' : 'Keep page and zoom in step with the generated drawing';
  }
  function syncFromRight() { if (S.sync && R.srcPane.isReady() && P.doc && R.srcPane.numPages() === P.doc.numPages) R.srcPane.setView({ page: P.page, zoom: P.zoom }); }
  function syncFromLeft(v) { if (S.sync && P.doc && R.srcPane.numPages() === P.doc.numPages) { P.page = Math.max(1, Math.min(P.doc.numPages, v.page)); P.zoom = v.zoom; renderPage(); } }

  /** Reference-match verification (V7_CONTRACT 4): shown in the Verification tab only when the backend supplied it. */
  function verificationBlock(wrap, p, j) {
    var F = McA.referenceview, v = p.verification, info = F.verificationInfo(v);
    wrap.append(h('h3', { class: 'sub-h', text: 'Reference and drawing verification' }));
    wrap.append(h('div', { class: 'rv-card' }, h('span', { class: 'rv-st', 'data-state': info.tone === 'green' ? 'succeeded' : info.tone === 'red' ? 'failed' : info.tone === 'amber' ? 'warning' : 'pending' }, icon(info.icon, 13), info.label),
      p.reference && p.reference.mode === 'match' ? h('p', { class: 'reason', text: F.refStatusInfo(p.reference).label + (p.reference.filename ? ': ' + p.reference.filename : '') }) : h('p', { class: 'reason', text: 'No reference drawing was used (Standard mode).' })));
    var lines = F.verificationLines(v);
    if (lines.length) wrap.append(h('dl', { class: 'rv-kv' }, lines.map(function (x) { return [h('dt', { text: x[0] }), h('dd', { text: x[1] })]; })));
    var un = (v && v.coverage && v.coverage.unresolved) || [];
    if (un.length) wrap.append(h('h3', { class: 'sub-h', text: 'Unresolved items (' + un.length + ')' }), kv(un));
    var imgs = F.comparisonImages(p);
    if (imgs.length) wrap.append(h('h3', { class: 'sub-h', text: 'Comparison with the source' }), h('div', { class: 'rv-cmp' }, imgs.map(function (x) {
      return h('a', { class: 'rv-cmp-a', href: fileURL(j.job_id, x.rel, x.bytes), target: '_blank', rel: 'noopener', 'aria-label': 'Open comparison ' + x.name }, h('img', { src: fileURL(j.job_id, x.rel, x.bytes), alt: 'Comparison of the source and generated drawing: ' + x.name, loading: 'lazy', decoding: 'async' }), h('span', { class: 'reason', text: x.name }));
    })));
  }

  /* ───────────────────────── queue (batch table) ───────────────────────── */
  function renderQueueBar() {
    var sel = R.jobSel; sel.replaceChildren();
    if (!S.jobs.length) sel.append(h('option', { value: '', text: S.jobsErr ? 'Could not load runs' : 'No runs yet' }));
    S.jobs.forEach(function (jb) {
      var n = jb.parts.length;
      sel.append(h('option', { value: jb.job_id, text: fmtWhen(jb.created) + ' · ' + n + ' part' + (n === 1 ? '' : 's') + ' · ' + V().summaryLabel(jb.state) }));
    });
    sel.value = S.jobId || ''; sel.disabled = !S.jobs.length;
  }
  function renderQueue() {
    var j = S.job, box = R.queueBody; box.replaceChildren();
    renderQueueBar();
    var active = j && V().isActive(j.summary_state);
    var failed = j ? j.parts.filter(function (p) { return p.state === 'failed' || p.state === 'canceled'; }) : [];
    reasonBtn(R.cancelBtn, !j ? 'No run selected.' : active ? '' : 'This run is not running or queued.');
    reasonBtn(R.retryAllBtn, !j ? 'No run selected.' : active ? 'Wait for the run to finish.' : failed.length ? '' : 'No failed or canceled parts.');
    reasonBtn(R.deleteBtn, !j ? 'No run selected.' : active ? 'Cancel the run first.' : '');
    R.queueSummary.textContent = j ? V().summaryLabel(j.summary_state) + ' · ' + V().progressText(j.progress, j.summary_state) : (S.jobsErr || '');
    if (S.loadErr) { box.append(banner('err', S.loadErr)); return; }
    if (!j) { box.append(S.loading ? empty('spinner', 'Loading run...') : empty('files', 'No runs yet', 'Choose parts in Setup and press Run. Each part becomes a row here with its own progress and result.')); return; }
    var rej = (j.options && j.options.rejected) || [];
    if (rej.length) box.append(banner('warn', rej.length + ' file' + (rej.length === 1 ? ' was' : 's were') + ' not run: ' + rej.map(function (r) { return r.reason; }).join(' ')));
    var rows = j.parts.map(function (p) {
      var info = V().partStateInfo(p.state), nodes = V().stageStates(p, j), sp = V().stageProgress(nodes), done = sp.done;
      var open = V().openIssueCount(p.issues), files = (p.files || {});
      var links = [['drawing.pdf', 'PDF'], ['drawing.slddrw', 'SLDDRW'], ['model.stl', 'STL']].filter(function (x) { return files[x[0]]; }).map(function (x) {
        return h('a', { class: 'linkbtn rv-flink', href: fileURL(j.job_id, files[x[0]].url_path), download: p.part_id + '-' + x[0], 'aria-label': 'Download ' + x[1] + ' for ' + p.name, text: x[1] });
      });
      var sc = V().coverageScore({ percent: p.coverage_pct });
      var tr = h('tr', { 'data-part': p.part_id, 'aria-selected': String(p.part_id === S.partId), class: p.part_id === S.partId ? 'is-sel' : '' },
        h('td', null, h('button', { class: 'linkbtn rv-pname', type: 'button', 'aria-current': p.part_id === S.partId ? 'true' : null, title: 'Show this part in both viewers', text: p.name,
          onclick: function () { selectPart(p.part_id); } })),
        h('td', null, badge(info)),
        h('td', null, h('span', { class: 'rv-seg', role: 'img', 'aria-label': done + ' of ' + sp.total + ' stages done' }, nodes.map(function (n) { return h('i', { 'data-state': n.state }); })), h('span', { class: 'rv-segn', text: done + '/' + sp.total })),
        h('td', { class: 'num', text: typeof p.seconds === 'number' ? p.seconds + ' s' : '—' }),
        h('td', { class: 'num' }, sc === null ? h('span', { class: 'reason', text: 'not available' }) : h('span', { class: 'rv-score', style: 'color:' + McA.grade.colorOf(sc), title: McA.grade.gradeOf(sc).label, text: McA.grade.format(sc, 1) + '%' })),
        h('td', { text: p.state === 'queued' || !p.issues ? '—' : open ? open + ' open' : (p.issues.length ? 'All dispositioned' : 'None') }),
        h('td', null, links.length ? h('span', { class: 'rv-flinks' }, links) : h('span', { class: 'reason', text: 'none yet' })),
        h('td', null, h('div', { class: 'acts' },
          p.state === 'review_required' || (p.issues && p.issues.length) ? h('button', { class: 'btn secondary sm', type: 'button', text: 'Review', 'aria-label': 'Review ' + p.name, onclick: function () { selectPart(p.part_id); setTab('review'); } }) : null,
          (p.state === 'failed' || p.state === 'canceled') ? h('button', { class: 'btn secondary sm', type: 'button', text: 'Retry', disabled: active ? true : null, title: active ? 'Wait for the run to finish.' : '', 'aria-label': 'Retry ' + p.name, onclick: function () { doRetry([p.part_id]); } }) : null)));
      if (p.reference && p.reference.mode === 'match') { var ri = McA.referenceview.refStatusInfo(p.reference); tr.firstChild.append(h('div', { class: 'rv-qref', 'data-tone': ri.tone }, icon(ri.icon, 12), h('span', { text: ri.label }))); }
      if (p.error) tr.firstChild.append(h('div', { class: 'rv-perr', role: 'note', text: p.error }));
      return tr;
    });
    box.append(h('div', { class: 'tbl-wrap', tabindex: '0', role: 'region', 'aria-label': 'Table (scrolls sideways when narrow)' }, h('table', { class: 'tbl rv-tbl' }, h('caption', { class: 'sr-only', text: 'Parts in this run' }),
      h('thead', null, h('tr', null, ['Part', 'Result', 'Stages', 'Runtime', 'Coverage', 'Review', 'Files', 'Actions'].map(function (t) { return h('th', { scope: 'col', text: t }); }))), h('tbody', null, rows))));
  }
  function selectPart(id) { if (S.partId === id) return; S.partId = id; S.review = {}; renderAll(); }
  function doRetry(ids) {
    API.retry(S.jobId, ids).then(function () { announce('Retry queued'); schedulePoll(); return selectJob(S.jobId, ''); }, function (e) { toast(errText(e), true); });
  }
  function toast(msg, kind) { var k = kind === true ? 'err' : (kind || 'info'); if (McA.toast && McA.toast.show) McA.toast.show(msg, k); else announce(msg); }

  /* ───────────────────────── results panel ───────────────────────── */
  function setTab(id) { S.tab = id; S.resultsOpen = true; renderResultsHead(); renderResults(); if (id === 'logs') pollEvents(); }
  function renderResultsHead() {
    var p = part();
    R.tabs.replaceChildren();
    TABS.forEach(function (t, i) {
      var cnt = t[0] === 'review' && p ? V().openIssueCount(p.issues) : 0;
      var b = h('button', { type: 'button', role: 'tab', id: 'rv-tab-' + t[0], 'aria-selected': String(S.tab === t[0]), 'aria-controls': 'rv-results-body', tabindex: S.tab === t[0] ? '0' : '-1', 'data-tab': t[0],
        onclick: function () { setTab(t[0]); }, onkeydown: function (e) {
          var k = e.key, idx = TABS.map(function (x) { return x[0]; }).indexOf(S.tab), n = k === 'ArrowRight' ? idx + 1 : k === 'ArrowLeft' ? idx - 1 : k === 'Home' ? 0 : k === 'End' ? TABS.length - 1 : -1;
          if (n < 0) return; e.preventDefault(); n = (n + TABS.length) % TABS.length; setTab(TABS[n][0]); var nb = document.getElementById('rv-tab-' + TABS[n][0]); if (nb) nb.focus();
        } }, t[1], cnt ? h('span', { class: 'rv-cnt', 'aria-label': cnt + ' open', text: String(cnt) }) : null);
      R.tabs.append(b);
    });
    R.toggleRes.setAttribute('aria-expanded', String(S.resultsOpen));
    R.toggleRes.querySelector('.rv-tg-l').textContent = S.resultsOpen ? 'Collapse' : 'Expand';
    R.resBody.hidden = !S.resultsOpen;
  }
  function fetchArtifact(name, cb) {
    var p = part(), f = p && p.files && p.files[name];
    if (!f) { cb(null, 'missing'); return; }
    var key = S.jobId + '|' + p.part_id + '|' + name + '|' + f.bytes, c = S.artifacts[key];
    if (c) { cb(c.data, c.err); return; }
    var id = S.jobId;
    API.artifact(S.jobId, f.url_path, f.bytes).then(function (d) { S.artifacts[key] = { data: d }; if (S.jobId === id && part() === p) renderResults(); }, function (e) { S.artifacts[key] = { err: errText(e) }; if (S.jobId === id) renderResults(); });
    cb(undefined, null);
  }
  function scalar(v) { return v === null || v === undefined ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v); }
  function kv(v, depth) {
    depth = depth || 0;
    if (Array.isArray(v)) {
      if (!v.length) return h('span', { class: 'reason', text: 'none' });
      if (v.every(function (x) { return x && typeof x === 'object' && !Array.isArray(x); })) {
        var cols = []; v.forEach(function (o) { Object.keys(o).forEach(function (k) { if (cols.indexOf(k) < 0 && (o[k] === null || typeof o[k] !== 'object')) cols.push(k); }); });
        cols = cols.slice(0, 10);
        return h('div', { class: 'tbl-wrap', tabindex: '0', role: 'region', 'aria-label': 'Table (scrolls sideways when narrow)' }, h('table', { class: 'tbl' }, h('thead', null, h('tr', null, cols.map(function (c) { return h('th', { scope: 'col', text: c }); }))),
          h('tbody', null, v.map(function (o) { return h('tr', null, cols.map(function (c) { return h('td', { class: 'mono', text: scalar(o[c]) }); })); }))));
      }
      return h('span', { class: 'mono', text: v.map(scalar).join(', ') });
    }
    if (v && typeof v === 'object') {
      if (depth >= 3) return h('span', { class: 'mono', text: JSON.stringify(v) });
      return h('dl', { class: 'rv-kv' }, Object.keys(v).map(function (k) { return [h('dt', { text: k }), h('dd', null, kv(v[k], depth + 1))]; }));
    }
    return h('span', { class: 'mono', text: scalar(v) });
  }
  function jsonSection(name, title, emptyText) {
    var wrap = h('div', { class: 'rv-sec' });
    fetchArtifact(name, function (d, err) {
      if (err === 'missing') wrap.append(empty('file', title + ' not available', emptyText));
      else if (d === undefined) wrap.append(h('p', { class: 'reason', text: 'Loading...' }));
      else if (err) wrap.append(banner('err', err));
      else {
        wrap.append(kv(d));
        wrap.append(h('details', { class: 'rv-raw' }, h('summary', { text: 'Raw JSON' }), h('pre', { class: 'mono', text: JSON.stringify(d, null, 2) })));
      }
    });
    return wrap;
  }
  function renderResults() {
    var body = R.resBody, p = part(), j = S.job;
    body.replaceChildren();
    body.setAttribute('aria-labelledby', 'rv-tab-' + S.tab);
    if (!j || !p) { body.append(empty('results', 'Nothing to show yet', 'Results for the selected part appear here.')); return; }
    var fn = { overview: tabOverview, inventory: tabInventory, plan: tabPlan, coverage: tabCoverage, review: tabReview, verification: tabVerification, files: tabFiles, logs: tabLogs }[S.tab];
    body.append(fn(p, j));
  }
  function tabOverview(p, j) {
    var wrap = h('div', { class: 'rv-sec' });
    wrap.append(h('div', { class: 'rv-ovg' },
      h('div', { class: 'rv-card' }, h('span', { class: 'chip-k', text: 'Part result' }), badge(V().partStateInfo(p.state)), h('p', { class: 'reason', text: V().stageCaption(p) })),
      h('div', { class: 'rv-card' }, h('span', { class: 'chip-k', text: 'Review' }), h('strong', { text: p.review_status === 'required' ? 'Required' : p.review_status === 'resolved' ? 'Resolved' : 'None recorded' }),
        h('p', { class: 'reason', text: V().openIssueCount(p.issues) + ' open issue(s) of ' + (p.issues || []).length })),
      h('div', { class: 'rv-card' }, h('span', { class: 'chip-k', text: 'Coverage (diagnostic)' }), h('strong', { text: p.coverage_pct === null || p.coverage_pct === undefined ? 'Not available' : McA.grade.format(p.coverage_pct, 1) + '%' }),
        h('p', { class: 'reason', text: 'Open Dimensions & Coverage for the counts.' })),
      h('div', { class: 'rv-card' }, h('span', { class: 'chip-k', text: 'Material' }), h('strong', { text: (p.material && p.material.name) || 'Not recorded' }))));
    wrap.append(h('p', { class: 'rv-note', role: 'note' }, icon('info', 14), h('span', { text: V().DRAFT_NOTICE + '. ' + V().QA_NOTE })));
    if (p.error) wrap.append(banner('err', p.error));
    var nodes = V().stageStates(p, j);
    wrap.append(h('h3', { class: 'sub-h', text: 'Stages' }), h('div', { class: 'tbl-wrap', tabindex: '0', role: 'region', 'aria-label': 'Table (scrolls sideways when narrow)' }, h('table', { class: 'tbl' }, h('caption', { class: 'sr-only', text: 'Stage results' }),
      h('thead', null, h('tr', null, ['Stage', 'Status', 'Seconds', 'Warnings and errors'].map(function (t) { return h('th', { scope: 'col', text: t }); }))),
      h('tbody', null, nodes.map(function (n) { return h('tr', null, h('td', { text: n.label }), h('td', null, h('span', { class: 'rv-st', 'data-state': n.state }, STATE_ICON[n.state] ? icon(STATE_ICON[n.state], 13) : null, V().stateWord(n.state))),
        h('td', { class: 'num', text: n.seconds === null ? '—' : String(n.seconds) }), h('td', { text: n.errors.concat(n.warnings).join('; ') || '—' })); })))));
    wrap.append(h('p', { class: 'reason', text: V().costText(j) + ' · ' + (V().runtimeText(j.parts) ? 'Measured runtime ' + V().runtimeText(j.parts) : 'Runtime not measured yet') + ' · ' + V().engineText(j, S.status) }));
    return wrap;
  }
  function tabInventory() { return jsonSection('inventory.json', 'Geometry inventory', 'It is written after the geometry inventory stage.'); }
  function tabPlan() { return jsonSection('drawing_plan.json', 'Drawing plan', 'It is written after the view planning stage.'); }
  function tabCoverage(p) {
    var wrap = h('div', { class: 'rv-sec' });
    var qa = null;
    fetchArtifact('qa.json', function (d, err) { qa = err ? null : d; });
    var cov = qa && qa.coverage;
    if (!cov && p.coverage_pct !== null && p.coverage_pct !== undefined) cov = { percent: p.coverage_pct };
    var score = V().coverageScore(cov);
    wrap.append(h('div', { class: 'rv-covhead' }, h('p', { class: 'rv-covt', text: cov && typeof cov.applicable === 'number' ? V().coverageText(cov) : 'Coverage not available yet' }),
      score === null ? h('span', { class: 'badge-c', 'data-grade': 'none', style: 'color:' + McA.grade.colorOf(null) }, 'Not available') :
        h('span', { class: 'badge-c rv-grade', style: 'color:' + McA.grade.colorOf(score) + ';border-color:' + McA.grade.colorOf(score), title: McA.grade.gradeOf(score).label }, McA.grade.gradeOf(score).glyph + ' ' + McA.grade.format(score, 1) + '%')));
    wrap.append(h('p', { class: 'reason', text: 'Diagnostic only: geometric coverage is not manufacturing completeness or approval.' }));
    if (cov && (cov.excluded || []).length) wrap.append(h('h3', { class: 'sub-h', text: 'Excluded characteristics' }), kv(cov.excluded));
    wrap.append(h('h3', { class: 'sub-h', text: 'Coverage ledger' }));
    var items = h('div');
    fetchArtifact('dimension_coverage.json', function (d, err) {
      if (err === 'missing') items.append(empty('file', 'Ledger not available', 'It is written after the dimensioning stage.'));
      else if (d === undefined) items.append(h('p', { class: 'reason', text: 'Loading...' }));
      else if (err) items.append(banner('err', err));
      else items.append(kv(d.items || []));
    });
    wrap.append(items);
    return wrap;
  }
  function tabVerification(p, j) {
    var wrap = h('div', { class: 'rv-sec' });
    var vs = V().stageStates(p, j).filter(function (n) { return n.id === 'verification' || n.id === 'publishing' || n.id === 'publish'; });
    wrap.append(h('p', { class: 'rv-note', role: 'note' }, icon('info', 14), h('span', { text: V().QA_NOTE + ' Verification here means the drawing was checked by software; an engineer still reviews it.' })));
    wrap.append(h('div', { class: 'rv-ovg' }, vs.map(function (n) { return h('div', { class: 'rv-card' }, h('span', { class: 'chip-k', text: n.label }), h('span', { class: 'rv-st', 'data-state': n.state }, STATE_ICON[n.state] ? icon(STATE_ICON[n.state], 13) : null, V().stateWord(n.state)), h('p', { class: 'reason', text: n.errors.concat(n.warnings).join('; ') || (n.seconds === null ? '' : n.seconds + ' s') })); })));
    verificationBlock(wrap, p, j);
    [['pdf_check.json', 'PDF check'], ['reopen_check.json', 'Reopen check'], ['stl_validation.json', 'STL validation']].forEach(function (x) {
      wrap.append(h('h3', { class: 'sub-h', text: x[1] }));
      fetchArtifact(x[0], function (d, err) {
        if (err === 'missing') wrap.append(h('p', { class: 'reason', text: 'Not produced yet.' }));
        else if (d === undefined) wrap.append(h('p', { class: 'reason', text: 'Loading...' }));
        else if (err) wrap.append(banner('err', err));
        else wrap.append(kv(d));
      });
    });
    return wrap;
  }
  function tabFiles(p, j) {
    var list = V().fileList(p);
    if (!list.length) return empty('files', 'No files yet', 'Files are listed only after they exist.');
    return h('div', { class: 'tbl-wrap', tabindex: '0', role: 'region', 'aria-label': 'Table (scrolls sideways when narrow)' }, h('table', { class: 'tbl' }, h('caption', { class: 'sr-only', text: 'Files of this part' }),
      h('thead', null, h('tr', null, ['File', 'Size', 'Actions'].map(function (t) { return h('th', { scope: 'col', text: t }); }))),
      h('tbody', null, list.map(function (f) {
        var inl = /\.(pdf|png|stl)$/i.test(f.name);
        return h('tr', null, h('td', null, h('strong', { text: f.label }), h('div', { class: 'mono reason', text: f.name })), h('td', { class: 'num', text: fmtBytes(f.bytes) }),
          h('td', null, h('div', { class: 'acts' }, inl && !/\.stl$/i.test(f.name) ? h('a', { class: 'btn secondary sm', href: fileURL(j.job_id, f.rel), target: '_blank', rel: 'noopener', 'aria-label': 'Open ' + f.label, text: 'Open' }) : null,
            h('a', { class: 'btn secondary sm', href: fileURL(j.job_id, f.rel), download: p.part_id + '-' + f.name.replace(/\//g, '-'), 'aria-label': 'Download ' + f.label }, icon('download', 14), 'Download'))));
      }))));
  }
  function tabLogs(p, j) {
    var wrap = h('div', { class: 'rv-sec' });
    var sel = h('select', { class: 'input-c vp-sel', 'aria-label': 'Log scope', onchange: function () { S.logScope = sel.value; renderResults(); } },
      h('option', { value: 'part', text: 'This part' }), h('option', { value: 'all', text: 'Whole run' }));
    sel.value = S.logScope;
    wrap.append(h('div', { class: 'rv-logbar' }, sel, h('button', { class: 'btn secondary sm', type: 'button', text: 'Refresh', onclick: pollEvents })));
    var evs = S.events.filter(function (e) { return S.logScope === 'all' || !e.part || e.part === p.part_id; });
    if (!evs.length) { wrap.append(empty('files', 'No log lines yet', 'Run events (stage starts and ends, failures, reviews) appear here.')); return wrap; }
    wrap.append(h('ol', { class: 'rv-log mono', 'aria-label': 'Run events' }, evs.map(function (e) { return h('li', null, h('time', { text: (e.t || '').slice(11, 19) }), h('span', { text: ' ' + (e.part ? '[' + e.part + '] ' : '') + V().eventLine(e) })); })));
    return wrap;
  }
  function tabReview(p, j) {
    var wrap = h('div', { class: 'rv-sec' }), issues = V().sortIssues(p.issues || []);
    wrap.append(h('p', { class: 'rv-note', role: 'note' }, icon('info', 14), h('span', { text: V().QA_NOTE + ' ' + V().DRAFT_NOTICE + '. Accepting an issue records who accepted it and why; it does not approve the part.' })));
    var active = V().isActive(j.summary_state);
    if (active) wrap.append(banner('info', 'Review actions are available when the run has finished.'));
    if (!issues.length) { wrap.append(empty('check', p.state === 'completed' || p.state === 'review_required' ? 'No issues recorded' : 'No review data yet', 'Issues are listed here after the verification stage.')); return wrap; }
    wrap.append(h('p', { class: 'rv-covt', text: V().openIssueCount(issues) + ' open of ' + issues.length + ' issues' }));
    issues.forEach(function (i) { wrap.append(issueCard(p, j, i, active)); });
    return wrap;
  }
  function issueCard(p, j, i, active) {
    var disp = V().dispositionInfo(i), st = S.review[i.id] || (S.review[i.id] = { note: '', busy: false, err: '' });
    var note = h('textarea', { class: 'input-c rv-note-in', id: 'rv-note-' + i.id, rows: '2', maxlength: '2000', placeholder: 'Note (required to accept or reject)', 'aria-label': 'Note for ' + i.id, 'aria-describedby': 'rv-why-' + i.id });
    note.value = st.note;
    var why = h('span', { class: 'reason', id: 'rv-why-' + i.id });
    var btns = [];
    function mk(action, label) {
      var b = h('button', { class: 'btn secondary sm', type: 'button', 'data-action': action, text: label, onclick: function () { submit(action); } });
      btns.push([action, b]); return b;
    }
    function refresh() {
      st.note = note.value;
      var reason = active ? 'The run is still going.' : st.busy ? 'Saving...' : '';
      btns.forEach(function (x) { var r = reason || V().reviewBlock(x[0], note.value); if (x[0] === 'reopen' && (i.disposition || 'open') === 'open') r = reason || 'The issue is already open.'; x[1].disabled = !!r; x[1].title = r; });
      var act = ['accept', 'reject'].map(function (a) { return V().reviewBlock(a, note.value); }).filter(Boolean)[0];
      why.textContent = st.err || (active ? 'Wait for the run to finish.' : act || '');
    }
    function submit(action) {
      st.busy = true; st.err = ''; refresh();
      API.review(j.job_id, p.part_id, { issue_id: i.id, action: action, note: note.value }).then(function () { st.note = ''; st.busy = false; announce('Issue ' + i.id + ' ' + action + 'ed'); return selectJob(j.job_id, p.part_id); },
        function (e) { st.busy = false; st.err = errText(e); refresh(); });
    }
    var hist = (i.history || []);
    var card = h('article', { class: 'rv-issue', 'data-sev': i.severity, 'data-disp': i.disposition || 'open', 'aria-labelledby': 'rv-t-' + i.id },
      h('header', { class: 'rv-issue-h' }, pill(i.severity), h('span', { class: 'badge-c' }, icon(disp.icon, 13), disp.label), h('h4', { id: 'rv-t-' + i.id, text: i.message })),
      h('dl', { class: 'rv-kv rv-issue-kv' },
        h('dt', { text: 'Source' }), h('dd', { text: i.source_ref || '—' }), h('dt', { text: 'Where' }), h('dd', { text: V().issueLocation(i) }),
        h('dt', { text: 'Observed' }), h('dd', { text: i.observed || '—' }), h('dt', { text: 'Expected' }), h('dd', { text: i.expected || '—' }),
        h('dt', { text: 'Next action' }), h('dd', { text: i.next_action || '—' })),
      hist.length ? h('ol', { class: 'rv-hist', 'aria-label': 'Resolution history' }, hist.map(function (x) { return h('li', { text: V().historyLine(x) }); })) : h('p', { class: 'reason', text: 'No resolution history yet.' }),
      h('div', { class: 'rv-act' }, note, h('div', { class: 'rv-actb' }, mk('accept', 'Accept'), mk('reject', 'Reject'), mk('reopen', 'Reopen')), why));
    note.addEventListener('input', refresh); refresh();
    return card;
  }

  function renderNotice() {
    R.notice.replaceChildren();
    if (S.submitErr) R.notice.append(banner('err', S.submitErr));
    if (S.notice) R.notice.append(banner('warn', S.notice, h('button', { class: 'ibtn', type: 'button', 'aria-label': 'Dismiss', onclick: function () { S.notice = null; renderNotice(); } }, icon('x', 14))));
  }

  /* ───────────────────────── render + build ───────────────────────── */
  function renderAll() {
    if (!R.root) return;
    renderHeader(); renderTracker(); renderQueue(); renderResultsHead(); renderResults(); syncViewers(); renderNotice();
    if (rail) rail.refreshExport();
    fitRail();
    var empty_ = !S.jobs.length && !S.job && !S.loading;
    R.root.setAttribute('data-empty', empty_ ? 'true' : 'false');
    R.root.setAttribute('data-run-state', S.job ? S.job.summary_state : 'none');
    renderRunButtons();
    if (rail) { rail.renderProvenance(); rail.renderRuntime(); }
  }
  function toolBtn(attrs, ic, label, fn) {
    return h('button', Object.assign({ class: 'ibtn', type: 'button', title: label, 'aria-label': label, onclick: fn }, attrs || {}), icon(ic, 18));
  }
  function build() {
    var root = document.getElementById('page-reverse');
    R.root = root;
    root.replaceChildren();
    R.sub = h('span', { class: 'ws-sub rv-sub' });
    var head = h('header', { class: 'rv-head' },
      h('button', { id: 'rv-setup-btn', class: 'btn secondary sm rv-setup-btn', type: 'button', 'aria-expanded': 'true', 'aria-controls': 'rv-setup', onclick: function () { toggleSetup(); } }, icon('settings', 16), h('span', { class: 'rv-sb-l', text: 'Setup' })),
      h('div', { class: 'ws-title rv-title' }, h('div', { class: 'ws-line' }, h('h1', { id: 'rv-h1', tabindex: '-1', text: '3D → 2D Drawings' }), h('span', { class: 'ws-dot', 'aria-hidden': 'true', text: '·' }), h('span', { class: 'ws-crumb', text: 'SOLIDWORKS part to drawing' })), R.sub),
      h('div', { class: 'ws-chips rv-chips' }, chip('rv-chip-engine', 'settings', 'Engine'), chip('rv-chip-deliv', 'layers', 'Deliverables'), chip('rv-chip-runtime', 'recent', 'Runtime'), chip('rv-chip-cost', 'info', 'API usage')));
    R.root.append(head);
    R.root.append(h('p', { class: 'rv-draft-note', role: 'note' }, icon('info', 14), h('span', { text: V().DRAFT_NOTICE + '. ' + V().QA_NOTE })));
    R.notice = h('div', { class: 'rv-notice' });
    R.root.append(R.notice);
    /* tracker */
    R.steps = h('ol', { class: 'trk-steps', role: 'list' });
    R.stage = h('span', { class: 'trk-stage', role: 'status' });
    R.progText = h('span', { class: 'trk-caption' });
    R.barFill = h('i');
    R.bar = h('div', { class: 'rv-bar', role: 'progressbar', 'aria-label': 'Run progress (finished stages of all stages)', 'aria-valuemin': '0', 'aria-valuemax': '100', hidden: true }, R.barFill);
    R.root.append(h('section', { class: 'tracker rv-tracker', 'aria-label': 'Drawing run progress' }, h('h2', { class: 'trk-title', text: 'Run' }), R.steps, h('div', { class: 'trk-meta' }, R.stage, R.progText), R.bar));
    /* viewers */
    R.canvasWrap = h('div', { class: 'rv-canvas', tabindex: '0', role: 'group', 'aria-label': '3D model viewer. Drag to orbit, right-drag to pan, scroll to zoom, plus and minus to zoom, arrow keys to orbit.' });
    R.stlEmpty = h('div', { class: 'vp-empty rv-vempty' });
    R.viewSel = h('select', { class: 'input-c vp-sel', 'aria-label': 'Standard view', onchange: function () { T.view = R.viewSel.value; moveCamera(DIRS[T.view] || DIRS.Isometric); } }, Object.keys(DIRS).map(function (k) { return h('option', { value: k, text: k }); }));
    R.stlTools = h('div', { class: 'vp-tools', role: 'toolbar', 'aria-label': '3D tools' }, R.viewSel,
      toolBtn({ 'data-act': 'pan', 'aria-pressed': 'false' }, 'pan', 'Pan with left mouse button', function (e) { T.pan = !T.pan; if (T.controls) { T.controls.mouseButtons.LEFT = T.pan ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE; T.controls.mouseButtons.RIGHT = T.pan ? THREE.MOUSE.ROTATE : THREE.MOUSE.PAN; } e.currentTarget.setAttribute('aria-pressed', String(T.pan)); }),
      toolBtn({ 'data-act': 'zoom-in' }, 'zoom-in', 'Zoom in', function () { dolly(0.8); }), toolBtn({ 'data-act': 'zoom-out' }, 'zoom-out', 'Zoom out', function () { dolly(1.25); }),
      toolBtn({ 'data-act': 'reset' }, 'reset', 'Reset view', function () { R.viewSel.value = 'Isometric'; moveCamera(DIRS.Isometric); }),
      toolBtn({ 'data-act': 'fit' }, 'fit', 'Fit to view', function () { if (T.mesh) { var d = T.camera.position.clone().sub(T.controls.target); moveCamera([d.x, d.y, d.z]); } }),
      toolBtn({ 'data-act': 'fullscreen', 'data-always': '' }, 'fullscreen', 'Fullscreen 3D', function () { fs(R.p3d); }));
    R.stlBadges = h('div', { class: 'vp-meta' });
    R.srcPane = McA.pdfpane.create({ label: 'Source PDF', icon: icon, onView: function (v) { var k = leftKey(); if (k) viewFor(k).src = v; syncFromLeft(v); } });
    R.syncBtn = h('button', { class: 'ibtn', type: 'button', id: 'rv-sync', title: 'Keep page and zoom in step with the generated drawing', 'aria-label': 'Synchronise page and zoom with the generated drawing', 'aria-pressed': 'false',
      onclick: function () { if (R.syncBtn.getAttribute('aria-disabled') === 'true') return; S.sync = !S.sync; updateSyncBtn(); if (S.sync) syncFromRight(); } }, icon('refresh', 18));
    R.srcTools = h('div', { class: 'vp-tools rv-src-tools', role: 'toolbar', 'aria-label': 'Source PDF tools', hidden: true }, R.srcPane.tools, R.syncBtn,
      toolBtn({ 'data-always': '', id: 'rv-src-fs' }, 'fullscreen', 'Fullscreen source PDF', function () { fs(R.p3d); }));
    R.leftTitle = h('h2', { id: 'rv-3d-t', text: '3D Model (STL)' });
    R.leftSeg = h('div', { class: 'seg-c rv-leftseg', id: 'rv-left-seg', role: 'group', 'aria-label': 'Left viewer content' },
      h('button', { type: 'button', id: 'rv-left-3d', class: 'on', 'aria-pressed': 'true', text: '3D Model', onclick: function () { setLeftMode('3d'); } }),
      h('button', { type: 'button', id: 'rv-left-src', 'aria-pressed': 'false', 'aria-disabled': 'true', title: 'Select a part first.', text: 'Source PDF', onclick: function () { setLeftMode('source'); } }));
    R.srcProv = h('p', { class: 'rv-prov-line', id: 'rv-src-prov', hidden: true });
    R.stlLayer = h('div', { class: 'rv-leftlayer', id: 'rv-stl-layer' }, R.canvasWrap, R.stlEmpty);
    R.srcLayer = h('div', { class: 'rv-leftlayer', id: 'rv-src-layer', hidden: true }, R.srcPane.el);
    R.p3d = h('section', { class: 'vpanel rv-panel', id: 'rv-3d', 'aria-labelledby': 'rv-3d-t' },
      h('header', { class: 'vp-head' }, h('span', { class: 'vp-ic' }, icon('cube', 20)), R.leftTitle, R.leftSeg, R.stlBadges, R.stlTools, R.srcTools),
      R.srcProv, h('div', { class: 'vp-body rv-stage' }, R.stlLayer, R.srcLayer));
    R.canvasWrap.addEventListener('keydown', function (e) {
      if (!T.mesh) return;
      if (e.key === '+' || e.key === '=') { e.preventDefault(); dolly(0.8); } else if (e.key === '-') { e.preventDefault(); dolly(1.25); }
      else if (e.key.indexOf('Arrow') === 0) { e.preventDefault(); orbitKey(e.key); }
    });
    R.paper = h('canvas', { class: 'rv-paper', 'aria-label': 'Drawing sheet' });
    R.paperWrap = h('div', { class: 'rv-paperwrap', tabindex: '0', role: 'region', 'aria-label': 'Drawing sheet (scrollable)', hidden: true }, R.paper);
    R.pdfEmpty = h('div', { class: 'vp-empty rv-vempty' });
    R.overlayBox = h('div', { class: 'rv-overlay', hidden: true, 'aria-live': 'polite' });
    R.pageLbl = h('span', { class: 'rv-pagelbl', 'aria-live': 'polite' }); R.zoomLbl = h('span', { class: 'rv-zoomlbl' });
    R.prevBtn = toolBtn({}, 'chevron-left', 'Previous sheet', function () { if (P.doc && P.page > 1) { P.page--; renderPage(); syncFromRight(); } });
    R.nextBtn = toolBtn({}, 'chevron-right', 'Next sheet', function () { if (P.doc && P.page < P.doc.numPages) { P.page++; renderPage(); syncFromRight(); } });
    R.pdfDl = h('a', { class: 'ibtn', href: '#', title: 'Download PDF', 'aria-label': 'Download PDF', 'aria-disabled': 'true', onclick: function (e) { if (R.pdfDl.getAttribute('aria-disabled') === 'true') e.preventDefault(); } }, icon('download', 18));
    R.pdfOverlayBtn = h('button', { class: 'ibtn', type: 'button', title: 'Show issues for this sheet next to the drawing (the PDF stays clean)', 'aria-label': 'Review overlay', 'aria-pressed': 'false', onclick: function () { S.overlay = !S.overlay; R.pdfOverlayBtn.setAttribute('aria-pressed', String(S.overlay)); renderOverlay(); } }, icon('mark', 18));
    R.pdfTools = h('div', { class: 'vp-tools', role: 'toolbar', 'aria-label': 'Drawing tools' }, R.prevBtn, R.pageLbl, R.nextBtn,
      toolBtn({}, 'zoom-out', 'Zoom out', function () { P.zoom = Math.max(0.25, Math.round((P.zoom - 0.25) * 100) / 100); renderPage(); syncFromRight(); }), R.zoomLbl,
      toolBtn({}, 'zoom-in', 'Zoom in', function () { P.zoom = Math.min(6, Math.round((P.zoom + 0.25) * 100) / 100); renderPage(); syncFromRight(); }),
      toolBtn({}, 'fit', 'Fit sheet to view', function () { P.zoom = 1; renderPage(); syncFromRight(); }), R.pdfOverlayBtn, R.pdfDl,
      toolBtn({ 'data-always': '' }, 'fullscreen', 'Fullscreen drawing', function () { fs(R.p2d); }));
    R.pdfBadges = h('div', { class: 'vp-meta' });
    R.p2d = h('section', { class: 'vpanel rv-panel', id: 'rv-2d', 'aria-labelledby': 'rv-2d-t' },
      h('header', { class: 'vp-head' }, h('span', { class: 'vp-ic' }, icon('file', 20)), h('h2', { id: 'rv-2d-t', text: 'Drawing (PDF)' }), h('span', { class: 'badge-c steel rv-lbl', id: 'rv-gen-lbl', title: 'Generated by this run (not the original)', text: 'Generated' }), R.pdfBadges, R.pdfTools),
      h('div', { class: 'vp-body rv-sheetbody' }, R.paperWrap, R.pdfEmpty), R.overlayBox);
    rail = McA.reverseRail;
    var rp = rail.init({ S: S, R: R, API: API, errText: errText, toast: toast, announce: announce, banner: banner, part: part, loadTemplates: loadTemplates, refreshJobs: refreshJobs, selectJob: selectJob,
      renderNotice: function () { renderNotice(); } });
    R.setup = h('aside', { class: 'rv-setup', id: 'rv-setup', 'aria-label': 'Setup and actions' },
      h('div', { class: 'rv-setup-h' }, h('h2', { text: 'Setup' }), h('button', { class: 'ibtn rv-setup-x', type: 'button', 'aria-label': 'Close setup', onclick: function () { toggleSetup(false); } }, icon('x', 16))), rp.scroll, rp.foot, rp.inputs);
    R.mainEl = h('div', { class: 'rv-main' }, h('div', { class: 'rv-split' }, R.p3d, R.p2d), h('div', { class: 'rv-railcell' }, R.setup));
    R.root.append(R.mainEl, h('div', { class: 'rv-scrim', id: 'rv-scrim', hidden: true, onclick: function () { toggleSetup(false); } }));
    /* queue */
    R.jobSel = h('select', { class: 'input-c vp-sel rv-jobsel', 'aria-label': 'Run', onchange: function () { if (R.jobSel.value) selectJob(R.jobSel.value, ''); } });
    R.queueSummary = h('span', { class: 'rv-qsum', role: 'status' });
    R.cancelBtn = h('button', { class: 'btn secondary sm', type: 'button', onclick: function () { API.cancel(S.jobId).then(function () { announce('Cancel requested'); return selectJob(S.jobId, ''); }, function (e) { toast(errText(e), true); }); } }, icon('cancel', 14), 'Cancel run');
    R.retryAllBtn = h('button', { class: 'btn secondary sm', type: 'button', onclick: function () { doRetry(null); } }, icon('refresh', 14), 'Retry failed');
    R.deleteBtn = h('button', { class: 'btn secondary sm', type: 'button', onclick: function () {
      McA.dialog.confirm('Delete this run?', 'Its drawings, models and review history are removed from this machine. This cannot be undone.', 'Delete run', true).then(function (ok) {
        if (ok) API.del(S.jobId).then(function () { S.jobId = ''; S.job = null; S.partId = ''; refreshJobs().then(function () { if (!S.jobs.length) renderAll(); }); }, function (e) { toast(errText(e), true); });
      });
    } }, icon('trash', 14), 'Delete run');
    R.queueBody = h('div', { class: 'rv-qbody' });
    R.mainEl.append(h('section', { class: 'rv-queue', id: 'rv-queue', 'aria-labelledby': 'rv-q-t' }, h('div', { class: 'rv-qhead' }, h('h2', { id: 'rv-q-t', text: 'Batch queue' }), R.jobSel, R.queueSummary,
      h('div', { class: 'rv-qacts' }, R.cancelBtn, R.retryAllBtn, R.deleteBtn)), R.queueBody));
    /* results */
    R.tabs = h('div', { class: 'rv-tabs', role: 'tablist', 'aria-label': 'Results' });
    R.toggleRes = h('button', { class: 'btn ghost sm', type: 'button', 'aria-expanded': 'true', 'aria-controls': 'rv-results-body', onclick: function () { S.resultsOpen = !S.resultsOpen; renderResultsHead(); } }, icon('chevron-down', 14), h('span', { class: 'rv-tg-l', text: 'Collapse' }));
    R.resBody = h('div', { class: 'rv-results-body', id: 'rv-results-body', role: 'tabpanel', tabindex: '0' });
    R.root.append(h('section', { class: 'rv-results', 'aria-label': 'Results' }, h('div', { class: 'rv-reshead' }, R.tabs, R.toggleRes), R.resBody));
  }
  function dolly(f) { if (!T.mesh) return; T.anim = null; var off = T.camera.position.clone().sub(T.controls.target), len = Math.min(T.radius * 40, Math.max(T.radius * 0.3, off.length() * f)); T.camera.position.copy(T.controls.target).add(off.setLength(len)); }
  function orbitKey(k) {
    var a = 0.12, off = T.camera.position.clone().sub(T.controls.target);
    if (k === 'ArrowLeft' || k === 'ArrowRight') off.applyAxisAngle(new THREE.Vector3(0, 1, 0), k === 'ArrowLeft' ? a : -a);
    else { var ax = new THREE.Vector3().crossVectors(off, T.camera.up).normalize(); off.applyAxisAngle(ax, k === 'ArrowUp' ? a : -a); }
    T.camera.position.copy(T.controls.target).add(off);
  }
  function fs(el) { if (document.fullscreenElement) document.exitFullscreen(); else if (el.requestFullscreen) el.requestFullscreen().catch(function () { toast('Fullscreen is not available here.', true); }); }
  /** Height of the part of the rail cell that is on screen (the rail is sticky inside it). Pure layout: never touches state. */
  var fitQueued = false;
  function fitRail() {
    if (fitQueued) return;
    fitQueued = true;
    requestAnimationFrame(function () {
      fitQueued = false;
      var cell = R.setup && R.setup.parentNode; if (!cell || !cell.offsetParent) return;
      var c = cell.getBoundingClientRect(), vh = window.innerHeight || document.documentElement.clientHeight;
      var avail = Math.max(320, Math.min(c.height, vh - Math.max(c.top, 12) - 12));
      var v = Math.round(avail) + 'px';
      if (cell.style.getPropertyValue('--rv-rail-h') !== v) cell.style.setProperty('--rv-rail-h', v);
    });
  }
  function toggleSetup(open) {
    S.setupOpen = open === undefined ? !S.setupOpen : open;
    R.root.setAttribute('data-setup', S.setupOpen ? 'open' : 'closed');
    document.getElementById('rv-setup-btn').setAttribute('aria-expanded', String(S.setupOpen));
    var narrow = window.matchMedia('(max-width: 1099.98px)').matches;
    document.getElementById('rv-scrim').hidden = !(narrow && S.setupOpen);
    if (narrow && S.setupOpen) { var f = R.setup.querySelector('input,button,select'); if (f) f.focus(); }
    if (!S.setupOpen) { var b = document.getElementById('rv-setup-btn'); if (b && document.activeElement && R.setup.contains(document.activeElement)) b.focus(); }
    T.resize = true; if (P.doc) setTimeout(renderPage, 50);
    fitRail();
  }

  /* ───────────────────────── Projects / Recent Files ───────────────────────── */
  function listSection(id, anchorId, kind) {
    var anchor = document.getElementById(anchorId);
    if (!anchor) return null;
    var sec = document.getElementById(id);
    if (!sec) { sec = h('section', { id: id, class: 'rv-list', 'aria-label': '3D to 2D drawing runs' }); anchor.insertAdjacentElement('afterend', sec); }
    return sec;
  }
  function renderLists() {
    var pages = [['rv-projects', 'proj-body', 'projects'], ['rv-recent', 'recent-body', 'recent']];
    pages.forEach(function (x) { var pg = document.getElementById('page-' + x[2]); if (pg && !pg.hidden) fillList(listSection(x[0], x[1], x[2]), x[2]); });
  }
  function fillList(sec, kind) {
    if (!sec) return;
    API.jobs().then(function (r) {
      var jobs = r.jobs || [];
      sec.replaceChildren();
      if (!jobs.length) { sec.hidden = true; return; }
      sec.hidden = false;
      sec.append(h('h2', { class: 'sec-h', text: '3D → 2D drawing runs' }));
      if (kind === 'projects') {
        sec.append(h('ul', { class: 'pgrid rv-cards' }, jobs.map(function (jb) {
          var th = jb.thumb ? h('img', { alt: 'Drawing preview of ' + (jb.parts[0] ? jb.parts[0].name : 'run'), src: fileURL(jb.job_id, jb.thumb.url_path), decoding: 'async', loading: 'lazy' }) : h('span', { class: 'pcard-nopv' }, icon('file', 30), h('span', { text: 'Preview unavailable' }));
          return h('li', { class: 'pcard' }, h('button', { class: 'pcard-th', type: 'button', 'aria-label': 'Open run ' + (jb.parts[0] ? jb.parts[0].name : jb.job_id), onclick: function () { McA.router.go('reverse', { job: jb.job_id }); } }, th),
            h('div', { class: 'pcard-b' }, h('div', { class: 'pcard-n', title: jb.parts.map(function (p) { return p.name; }).join(', '), text: jb.parts.length === 1 ? jb.parts[0].name : jb.parts.length + ' parts' }),
              h('div', { class: 'pcard-t' }, h('time', { class: 'pcard-when', datetime: jb.created, text: fmtWhen(jb.created) })),
              h('div', { class: 'pcard-m' }, h('span', { class: 'badge-c steel rv-modebadge', text: '3D → 2D' }), badge(V().partStateInfo(jb.state === 'running' ? 'drawing' : jb.state === 'completed_with_failures' ? 'review_required' : jb.state))),
              h('div', { class: 'pcard-a' }, h('button', { class: 'btn act act-open', type: 'button', text: 'Open', onclick: function () { McA.router.go('reverse', { job: jb.job_id }); } }))));
        })));
      } else {
        sec.append(h('div', { class: 'tbl-wrap', tabindex: '0', role: 'region', 'aria-label': 'Table (scrolls sideways when narrow)' }, h('table', { class: 'tbl' }, h('caption', { class: 'sr-only', text: '3D to 2D runs, newest first' }),
          h('thead', null, h('tr', null, ['Part(s)', 'Type', 'Run time', 'Result', 'Actions'].map(function (t) { return h('th', { scope: 'col', text: t }); }))),
          h('tbody', null, jobs.map(function (jb) {
            return h('tr', null, h('td', null, h('strong', { text: jb.parts.length === 1 ? jb.parts[0].name : jb.parts.length + ' parts' })), h('td', null, h('span', { class: 'badge-c steel rv-modebadge', text: '3D → 2D' })),
              h('td', { class: 'num', text: fmtWhen(jb.created) }), h('td', null, h('span', { text: V().summaryLabel(jb.state) })),
              h('td', null, h('div', { class: 'acts' }, h('button', { class: 'btn act act-open', type: 'button', text: 'Open drawing run', onclick: function () { McA.router.go('reverse', { job: jb.job_id }); } }))));
          })))));
      }
    }, function () { sec.hidden = true; });
  }

  /* ───────────────────────── lifecycle ───────────────────────── */
  McA.pages.reverse = {
    init: function () {
      if (S.inited) return;
      S.inited = true; guard = V().makeGuard();
      build();
      var narrow = window.matchMedia('(max-width: 1099.98px)').matches;
      S.setupOpen = !narrow; toggleSetup(S.setupOpen);
      window.matchMedia('(max-width: 1099.98px)').addEventListener('change', function (m) { S.setupOpen = !m.matches; toggleSetup(S.setupOpen); });
      document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && S.visible && window.matchMedia('(max-width: 1099.98px)').matches && S.setupOpen && !McA.dialog.isOpen()) { toggleSetup(false); document.getElementById('rv-setup-btn').focus(); } });
      renderAll(); renderSetup(); renderResultsHead(); renderPdfOverlay(); renderStlOverlay(); rail.renderExport();
      window.addEventListener('hashchange', function () { setTimeout(renderLists, 0); });
      setTimeout(renderLists, 0);
      window.addEventListener('resize', McA.util.debounce(function () { if (S.visible && P.doc) renderPage(); }, 150));
      window.addEventListener('resize', fitRail);
      var scroller = document.getElementById('main'); if (scroller) scroller.addEventListener('scroll', fitRail, { passive: true });
      if (typeof ResizeObserver !== 'undefined') new ResizeObserver(fitRail).observe(R.setup.parentNode);
    },
    enter: function (params) {
      S.visible = true;
      loadStatic();
      if (params && params.job) { S.jobId = ''; S.job = null; selectJob(params.job, params.part || ''); }
      else if (S.jobId) selectJob(S.jobId, S.partId);
      renderAll();
    },
    leave: function () { S.visible = false; clearTimeout(timer); timer = null; },
    _state: S
  };
  McA.reverse = { open: function (job, partId) { McA.router.go('reverse', partId ? { job: job, part: partId } : { job: job }); }, refreshLists: renderLists };
})();
