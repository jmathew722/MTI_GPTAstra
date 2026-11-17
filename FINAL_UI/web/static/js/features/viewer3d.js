/* McA.viewer3d: STL viewer (three.js). Shows ONLY bytes served by a model.stl endpoint.
   The mesh is swapped only after the new file loaded; a failed load keeps the previous mesh of the
   SAME part on screen and shows an error bar with Retry. Switching to another part clears the mesh
   first, so a model is never shown under the wrong part. Scene colors are read from CSS tokens. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var $ = function (id) { return document.getElementById(id); };
  var h = function () { return McA.dom.h.apply(null, arguments); };
  var store = function () { return McA.store; };

  var wrap, emptyEl, errBar, errMsg, loadChip;
  var inited = false, initFailed = false, needResize = false;
  var renderer, scene, camera, controls, mesh = null, grid = null, envTex = null, triad = null, panMode = false, wire = false;
  var radius = 100;                       // bounding sphere radius of the framed mesh
  var viewName = 'Isometric';
  var anim = null;                        // camera tween
  var loadedUrl = null, loadingUrl = null, shownCtx = null, failedUrl = null;
  var loadSeq = 0;
  var lastOutputsFetch = null;

  var DIRS = {
    Isometric: [1.4, 1.1, 1.8], Front: [0, 0, 1], Top: [0, 1, 0.001], Right: [1, 0, 0]
  };

  /* Colors come only from design-tokens.css (no literals here). */
  function token(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function reduced() { return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches; }

  function init() {
    if (inited || initFailed) return inited;
    if (typeof THREE === 'undefined' || !THREE.STLLoader || !THREE.OrbitControls) {
      initFailed = true; store().dispatch('viewer3d/set', { status: 'error', error: 'The 3D library did not load.' });
      return false;
    }
    try {
      scene = new THREE.Scene();   /* transparent: the navy stage gradient is CSS (--stage tokens) */
      camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100000);
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setClearColor(0x000000, 0);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      wrap.appendChild(renderer.domElement);
      controls = new THREE.OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true; controls.dampingFactor = 0.08;
      scene.add(new THREE.HemisphereLight(new THREE.Color(token('--ink-2')), new THREE.Color(token('--bg')), 0.45));
      var key = new THREE.DirectionalLight(new THREE.Color(token('--ink')), 0.7); key.position.set(1, 1, 1); scene.add(key);
      var rim = new THREE.DirectionalLight(new THREE.Color(token('--ink-2')), 0.25); rim.position.set(-1, 0.4, -0.8); scene.add(rim);
      envTex = makeEnv();
      if (envTex) scene.environment = envTex;
      camera.position.set(120, 90, 160);
      inited = true;
      new ResizeObserver(function () { needResize = true; }).observe(wrap);
      resize(); loop();
    } catch (e) {
      initFailed = true; inited = false;
      store().dispatch('viewer3d/set', { status: 'error', error: 'WebGL is not available in this browser.' });
      return false;
    }
    return true;
  }
  /* Soft studio reflections for the metallic look: a small room of dim walls and bright panels, prefiltered once. */
  function makeEnv() {
    try {
      var env = new THREE.Scene();
      var room = new THREE.Mesh(new THREE.BoxGeometry(20, 20, 20), new THREE.MeshBasicMaterial({ color: new THREE.Color(token('--stage-env')), side: THREE.BackSide }));
      env.add(room);
      [[0, 9.5, 0, 12, 0.4, 12, 3.2], [-9.5, 2, 3, 0.4, 8, 10, 1.6], [9.5, 0, -2, 0.4, 6, 8, 1.2], [0, -4, 9.5, 14, 6, 0.4, 0.9]].forEach(function (p) {
        var m = new THREE.Mesh(new THREE.BoxGeometry(p[3], p[4], p[5]), new THREE.MeshBasicMaterial({ color: new THREE.Color(p[6], p[6], p[6]) }));
        m.position.set(p[0], p[1], p[2]); env.add(m);
      });
      var pm = new THREE.PMREMGenerator(renderer), t = pm.fromScene(env, 0.04).texture; pm.dispose();
      return t;
    } catch (e) { return null; }
  }
  function drawTriad() {
    if (!triad || !mesh) return;
    var g = triad.getContext('2d'), w = triad.width, hh = triad.height, c = w / 2, L = w * 0.36, q = camera.quaternion.clone().invert();
    g.clearRect(0, 0, w, hh); g.lineWidth = 2; g.lineCap = 'round'; g.font = '600 11px ' + (token('--sans') || 'sans-serif'); g.textAlign = 'center'; g.textBaseline = 'middle';
    [['X', new THREE.Vector3(1, 0, 0), '--err-text'], ['Y', new THREE.Vector3(0, 1, 0), '--ok-text'], ['Z', new THREE.Vector3(0, 0, 1), '--accent-text']].map(function (a) {
      var v = a[1].clone().applyQuaternion(q); return { n: a[0], x: v.x, y: v.y, z: v.z, col: token(a[2]) };
    }).sort(function (a, b) { return a.z - b.z; }).forEach(function (a) {
      var x = c + a.x * L, y = c - a.y * L;
      g.strokeStyle = a.col; g.fillStyle = a.col; g.beginPath(); g.moveTo(c, c); g.lineTo(x, y); g.stroke();
      g.fillText(a.n, c + a.x * (L + 9), c - a.y * (L + 9));
    });
  }
  function dolly(f) {
    if (!mesh) return;
    anim = null;
    var off = camera.position.clone().sub(controls.target), len = Math.min(radius * 40, Math.max(radius * 0.3, off.length() * f));
    camera.position.copy(controls.target).add(off.setLength(len));
  }
  function setPan(on) {
    panMode = !!on;
    controls.mouseButtons.LEFT = panMode ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE;
    controls.mouseButtons.RIGHT = panMode ? THREE.MOUSE.ROTATE : THREE.MOUSE.PAN;
    wrap.style.cursor = panMode ? 'move' : '';
    var b = document.querySelector('#stl-bar [data-act="pan"]'); if (b) b.setAttribute('aria-pressed', String(panMode));
  }
  function setWire(on) {
    wire = !!on;
    if (mesh) mesh.material.wireframe = wire;
    var b = document.querySelector('#stl-bar [data-act="wire"]');
    if (b) { b.setAttribute('aria-pressed', String(wire)); b.title = wire ? 'Display mode: wireframe (click for shaded)' : 'Display mode: shaded (click for wireframe)'; }
  }
  function resize() {
    if (!inited) return;
    var w = wrap.clientWidth || 1, hh = wrap.clientHeight || 1;
    renderer.setSize(w, hh, false); camera.aspect = w / hh; camera.updateProjectionMatrix();
  }
  function loop() {
    requestAnimationFrame(loop);
    if (document.hidden || !wrap.offsetParent) return;
    if (needResize) { resize(); needResize = false; }
    if (anim) {
      var t = Math.min(1, (performance.now() - anim.t0) / anim.ms), k = 1 - Math.pow(1 - t, 3);
      camera.position.lerpVectors(anim.from, anim.to, k);
      if (t >= 1) anim = null;
    }
    controls.update();
    renderer.render(scene, camera);
    drawTriad();
  }

  function disposeMesh() {
    if (mesh) { scene.remove(mesh); mesh.geometry.dispose(); mesh.material.dispose(); mesh = null; }
    if (grid) { scene.remove(grid); if (grid.geometry) grid.geometry.dispose(); grid = null; }
  }

  function frame(geometry) {
    geometry.computeBoundingBox();
    var bb = geometry.boundingBox, c = new THREE.Vector3(), size = new THREE.Vector3();
    bb.getCenter(c); bb.getSize(size);
    geometry.translate(-c.x, -c.y, -c.z);
    geometry.computeBoundingSphere();
    var maxDim = Math.max(size.x, size.y, size.z) || 100;
    radius = (geometry.boundingSphere && geometry.boundingSphere.radius) || maxDim / 2;
    camera.near = maxDim / 100; camera.far = maxDim * 100; camera.updateProjectionMatrix();
    grid = new THREE.GridHelper(maxDim * 3, 20, new THREE.Color(token('--model-grid')), new THREE.Color(token('--model-grid-2')));
    grid.position.y = -size.y / 2; scene.add(grid);
  }

  function distance() {
    var v = camera.fov * Math.PI / 180, hf = 2 * Math.atan(Math.tan(v / 2) * (camera.aspect || 1));
    return radius / Math.sin(Math.min(v, hf) / 2) * 1.12;
  }
  function moveCamera(dir) {
    var d = new THREE.Vector3(dir[0], dir[1], dir[2]).normalize().multiplyScalar(distance());
    controls.target.set(0, 0, 0);
    if (reduced()) { camera.position.copy(d); anim = null; }
    else anim = { from: camera.position.clone(), to: d, t0: performance.now(), ms: 280 };
  }
  function setView(name) {
    if (!mesh) return;
    viewName = name; $('vp-3d-view').value = name;
    moveCamera(DIRS[name] || DIRS.Isometric);
  }
  function fitView() {
    if (!mesh) return;
    var dir = camera.position.clone().sub(controls.target);
    if (dir.lengthSq() < 1e-9) dir.set(1, 1, 1);
    moveCamera([dir.x, dir.y, dir.z]);
  }

  /* ── Target derivation from the outputs payload ──────────────────────── */
  function target(s) {
    var ctx = s.outputs.ctx, p = s.outputs.payload;
    if (!ctx || !p) return null;
    var stl = p.categories && p.categories.stl;
    if (!stl || !stl.present) return null;
    var mt = p.stl_mtime;
    var api = McA.api;
    var url = ctx.kind === 'part' ? api.partStlURL(ctx.session, ctx.part, mt) : api.runStlURL(ctx.runId, mt);
    var id = ctx.kind === 'part' ? 'p|' + ctx.session + '|' + ctx.part : 'r|' + ctx.runId;
    return { url: url, ctxId: id, source: stl.source || p.stl_source || null, mtime: mt };
  }
  function ctxId(s) {
    var c = s.outputs.ctx; if (!c) return null;
    return c.kind === 'part' ? 'p|' + c.session + '|' + c.part : 'r|' + c.runId;
  }
  function isPrevious(s, t) {
    var r = s.run, c = s.outputs.ctx;
    if (!t || !c || c.kind !== 'part' || !r || !r.startedAt || r.state === 'idle') return false;
    if (r.part !== c.part || (r.session && r.session !== c.session)) return false;
    return typeof t.mtime === 'number' && t.mtime < Math.floor(r.startedAt / 1000);
  }

  function load(t) {
    if (!init()) return;
    var seq = ++loadSeq;
    if (shownCtx !== t.ctxId) { disposeMesh(); loadedUrl = null; shownCtx = null; }
    loadingUrl = t.url; failedUrl = null;
    store().dispatch('viewer3d/set', { status: 'loading', url: t.url, error: null });
    new THREE.STLLoader().load(t.url, function (geo) {
      if (seq !== loadSeq) { geo.dispose(); return; }
      resize();
      disposeMesh();
      geo.computeVertexNormals();           // some exporters write zero normals; flat shading needs real ones
      var mat = new THREE.MeshStandardMaterial({ color: new THREE.Color(token('--model-mesh')), metalness: 0.75, roughness: 0.36, envMapIntensity: 1.0, wireframe: wire });
      mesh = new THREE.Mesh(geo, mat); scene.add(mesh); frame(geo);
      controls.target.set(0, 0, 0); viewName = 'Isometric'; $('vp-3d-view').value = viewName;
      var d = new THREE.Vector3(1.4, 1.1, 1.8).normalize().multiplyScalar(distance());
      camera.position.copy(d); controls.target.set(0, 0, 0); controls.update(); anim = null;
      loadedUrl = t.url; loadingUrl = null; shownCtx = t.ctxId;
      store().dispatch('viewer3d/set', { status: 'ready', url: t.url, error: null });
    }, undefined, function () {
      if (seq !== loadSeq) return;
      loadingUrl = null; failedUrl = t.url;
      store().dispatch('viewer3d/set', { status: 'error', url: t.url, error: 'The model file could not be loaded.' });
    });
  }

  function sync() {
    var s = store().get();
    var t = target(s);
    var cid = ctxId(s);
    if (!t) {
      loadSeq++;                           // drop any in-flight load
      if (mesh) disposeMesh();
      loadedUrl = loadingUrl = failedUrl = null; shownCtx = null;
      var vs = store().get().viewer3d;
      if (vs.status !== 'empty' || vs.url) store().dispatch('viewer3d/set', { status: 'empty', url: null, source: null, previousRun: null, error: null });
      else render();
      return;
    }
    var prev = isPrevious(s, t);
    var vs2 = s.viewer3d;
    if (vs2.source !== t.source || vs2.previousRun !== prev) store().dispatch('viewer3d/set', { source: t.source, previousRun: prev });
    if (t.url === loadedUrl && mesh) { render(); return; }
    if (t.url === loadingUrl || t.url === failedUrl) { render(); return; }
    load(t);
  }

  function retry() {
    failedUrl = null; loadedUrl = null;
    sync();
  }

  /* ── DOM state ───────────────────────────────────────────────────────── */
  function render() {
    var s = store().get(), v = s.viewer3d;
    var chip = $('vp-3d-state');
    chip.className = 'badge-c';
    var text = '';
    if (v.status === 'loading') text = 'Loading model…';
    else if (v.status === 'ready' || (v.status === 'error' && mesh)) {
      if (v.previousRun) text = 'Previous run';
      else if (v.source === 'solidworks') { text = 'Generated'; chip.classList.add('ok'); }
      else if (v.source === 'prevalidation') { text = 'Pre-validated (CadQuery)'; chip.classList.add('warn'); }
    }
    chip.textContent = text;
    chip.title = v.previousRun ? 'This model comes from before the current run. It is replaced when the new STL is ready.' : '';

    var hasMesh = !!mesh;
    emptyEl.hidden = hasMesh;
    var et = emptyEl.querySelector('.empty-t'), ed = emptyEl.querySelector('.empty-d');
    if (!hasMesh) {
      if (v.status === 'loading') { et.textContent = 'Loading model…'; ed.textContent = 'Reading the STL from the server.'; }
      else if (v.status === 'error') { et.textContent = 'No model shown'; ed.textContent = v.error || 'The model file could not be loaded.'; }
      else if (s.outputs.loading) { et.textContent = 'Checking for a model…'; ed.textContent = 'Asking the server which files exist for this part.'; }
      else { et.textContent = 'No model generated yet'; ed.textContent = 'The STL appears here after a successful SolidWorks build (needs Windows with SolidWorks).'; }
    }
    errBar.hidden = v.status !== 'error';
    errMsg.textContent = v.error || '';
    loadChip.hidden = !(v.status === 'loading' && hasMesh);
    wrap.setAttribute('aria-label', '3D model viewport. ' + (hasMesh ? (text || 'Model loaded') + '. Drag to orbit, scroll to zoom, arrow keys orbit, plus and minus zoom, 0 fits.' : 'No model generated yet.'));
    wrap.tabIndex = hasMesh ? 0 : -1;
    document.querySelectorAll('#stl-bar [data-act], #vp-3d-view').forEach(function (b) {
      b.disabled = !hasMesh;
      if (!hasMesh) b.title = 'No model generated yet';
      else if (b.getAttribute('data-act') !== 'wire') b.title = b.getAttribute('aria-label') || '';
    });
    if (triad) triad.hidden = !hasMesh;
    if (hasMesh) setWire(wire);
  }

  /* Outputs for the selected part: fetched here when nobody else has (same stale-ctx rule). */
  function ensureOutputs() {
    var s = store().get(), c = s.outputs.ctx;
    if (!c || c.kind !== 'part' || s.outputs.payload || s.outputs.loading) return;
    var key = c.session + '|' + c.part;
    if (lastOutputsFetch === key) return;
    lastOutputsFetch = key;
    fetchOutputs(c);
  }
  function fetchOutputs(c) {
    store().dispatch('outputs/loading', { ctx: c });
    McA.api.partOutputs(c.session, c.part).then(function (d) {
      store().dispatch('outputs/loaded', { ctx: c, payload: d });
    }, function (e) {
      store().dispatch('outputs/error', { ctx: c, error: (e && e.detail) || (e && e.message) || 'error' });
    });
  }

  function key(e) {
    if (!mesh) return;
    var off = camera.position.clone().sub(controls.target), sph = new THREE.Spherical().setFromVector3(off), used = true;
    var step = 0.12;
    if (e.key === 'ArrowLeft') sph.theta -= step; else if (e.key === 'ArrowRight') sph.theta += step;
    else if (e.key === 'ArrowUp') sph.phi = Math.max(0.05, sph.phi - step); else if (e.key === 'ArrowDown') sph.phi = Math.min(Math.PI - 0.05, sph.phi + step);
    else if (e.key === '+' || e.key === '=') sph.radius *= 0.85; else if (e.key === '-' || e.key === '_') sph.radius /= 0.85;
    else if (e.key === '0') { fitView(); e.preventDefault(); return; }
    else used = false;
    if (!used) return;
    e.preventDefault(); anim = null;
    camera.position.copy(controls.target).add(new THREE.Vector3().setFromSpherical(sph));
  }

  McA.viewer3d = {
    retry: retry, fit: fitView, setView: setView,
    init: function () {
      wrap = $('stl-canvas-wrap'); emptyEl = $('stl-empty');
      var body = wrap.parentNode;
      var rb = h('button', { class: 'btn secondary sm', type: 'button', text: 'Retry' });
      rb.addEventListener('click', retry);
      errMsg = h('span', { role: 'status' });
      errBar = h('div', { class: 'vp-err-bar', hidden: true }, errMsg, rb);
      loadChip = h('div', { class: 'vp-load', hidden: true, text: 'Loading new model…' });
      body.append(errBar, loadChip);

      triad = $('stl-triad');
      var tools = $('stl-bar');
      tools.addEventListener('click', function (e) {
        var b = e.target.closest('[data-act]'); if (!b || b.disabled) return;
        var a = b.getAttribute('data-act');
        if (a === 'fit') fitView(); else if (a === 'reset') setView('Isometric');
        else if (a === 'zoom-in') dolly(0.8); else if (a === 'zoom-out') dolly(1.25);
        else if (a === 'pan') setPan(!panMode); else if (a === 'wire') setWire(!wire);
      });
      $('vp-3d-view').addEventListener('change', function (e) { setView(e.target.value); });
      wrap.addEventListener('keydown', key);

      var st = store();
      st.subscribe(function (s) { return s.outputs.payload; }, sync);
      st.subscribe(function (s) { return s.outputs.ctx; }, function () { sync(); ensureOutputs(); });
      st.subscribe(function (s) { return s.outputs.loading; }, render);
      st.subscribe(function (s) { return s.viewer3d; }, render);
      st.subscribe(function (s) { return s.run.startedAt; }, sync);
      st.subscribe(function (s) { return s.run.state; }, function (v) {
        sync();
        if (v === 'idle' || v === 'queued' || v === 'running') return;
        var c = st.get().outputs.ctx, r = st.get().run;
        if (c && c.kind === 'part' && r.part === c.part) setTimeout(function () {
          var cc = st.get().outputs.ctx;
          if (cc && cc.kind === 'part' && cc.part === c.part && cc.session === c.session) fetchOutputs(cc);
        }, 800);
      });
      document.addEventListener('visibilitychange', function () { needResize = true; });
      window.addEventListener('hashchange', function () { needResize = true; });
      render(); sync(); ensureOutputs();
    }
  };
})();
