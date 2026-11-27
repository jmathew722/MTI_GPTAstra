/* 3D -> 2D setup rail (v7). Owns: Drawing template, Part selection, Reference drawing, Advanced settings, Runtime & cost, Run controls and Export.
   The page (pages/reverse.js) passes its shared state `S`, element refs `R` and a few callbacks through McA.reverseRail.init(ctx).
   Rules: every control is real (no placeholder), a capability the backend lacks is shown disabled with the reason, nothing is invented, file inputs are created
   once and never re-created (a re-render or poll never detaches an open file picker), accordions only flip `hidden` + aria-expanded (no re-render, no state loss),
   and nothing here ever opens a panel on a poll tick. Presentation rules live in logic/referenceview.js and logic/reverseview.js. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var C, S, R;
  var h = function () { return McA.dom.h.apply(null, arguments); };
  var V = function () { return McA.reverseview; };
  var F = function () { return McA.referenceview; };
  var icon = function (n, s) { return McA.icons.get(n, s || 16); };
  var $ = function (id) { return document.getElementById(id); };
  var refByFile = (typeof WeakMap !== 'undefined') ? new WeakMap() : null;
  var raw = [];                       // everything chosen, before the recursive filter
  var inputs = {};                    // persistent file inputs
  var stageTimer = null, exportTok = 0, refTarget = null;
  var ACC_KEY = 'mcagent.rv.acc';

  /* ───────────────────────── state helpers ───────────────────────── */
  function loadAcc() {
    var d = { tpl: false, ref: false, adv: false, rt: false, prov: false };
    try { var v = JSON.parse(sessionStorage.getItem(ACC_KEY) || 'null'); if (v && typeof v === 'object') Object.keys(d).forEach(function (k) { if (typeof v[k] === 'boolean') d[k] = v[k]; }); } catch (e) { /* storage unavailable */ }
    return d;
  }
  function saveAcc() { try { sessionStorage.setItem(ACC_KEY, JSON.stringify(S.acc)); } catch (e) { /* ignore */ } }
  function setAcc(key, on) {
    S.acc[key] = !!on; saveAcc();
    var b = $('rv-acc-' + key + '-btn'), body = $('rv-acc-' + key + '-body');
    if (b) b.setAttribute('aria-expanded', String(!!on));
    if (body) body.hidden = !on;
    if (b && b.parentNode) b.parentNode.setAttribute('data-open', String(!!on));
  }
  function refOf(it) {
    var r = refByFile && it.file ? refByFile.get(it.file) : null;
    if (!r) { r = { override: false, source: 'auto', upload: null, artifactId: '', confirmed: false, lookup: null, looking: false, err: '', uploading: false }; if (refByFile && it.file) refByFile.set(it.file, r); }
    return r;
  }
  /** Rows for the selected parts (key = position in the staged upload). `all` = every picked part, otherwise only the checked ones. */
  function rowsFor(all) {
    var out = [];
    S.picked.forEach(function (it, idx) {
      if (!all && it.on === false) return;
      var r = refOf(it), eff = r.override ? r.source : (S.refSource === 'upload' ? 'upload' : 'auto');
      out.push({ key: 'p' + idx, name: it.name, item: it, source: eff, upload: r.upload, artifactId: r.artifactId, confirmed: r.confirmed, lookup: r.lookup, looking: r.looking, ref: r });
    });
    return out;
  }
  function selectedPicked(all) { return S.picked.filter(function (i) { return all || i.on !== false; }); }
  function capsOk(k) { return !!(S.caps && S.caps[k]); }
  function accordion(key, title, summary, bodyNodes, opts) {
    opts = opts || {};
    var open = !!S.acc[key], id = 'rv-acc-' + key;
    var btn = h('button', { class: 'rv-acc-h', type: 'button', id: id + '-btn', 'aria-expanded': String(open), 'aria-controls': id + '-body', 'data-acc': key },
      h('span', { class: 'rv-acc-t', text: title }), h('span', { class: 'rv-acc-s', id: id + '-sum', text: summary || '', title: summary || '' }),
      opts.action ? h('span', { class: 'rv-acc-a', text: opts.action }) : icon('chevron-down', 16));
    var body = h('div', { class: 'rv-acc-b', id: id + '-body', role: 'region', 'aria-labelledby': id + '-btn' }, bodyNodes);
    body.hidden = !open;
    btn.addEventListener('click', function () { setAcc(key, btn.getAttribute('aria-expanded') !== 'true'); });
    return h('section', { class: 'rv-acc', 'data-open': String(open), 'data-acc-root': key, id: id }, btn, body);
  }
  function tip(text) { return h('span', { class: 'rv-help', tabindex: '0', role: 'img', 'aria-label': text, title: text }, icon('info', 14)); }
  function note(t, cls) { return h('p', { class: 'reason' + (cls ? ' ' + cls : ''), text: t }); }

  /* ───────────────────────── render ───────────────────────── */
  function render() {
    if (!R.railScroll) return;
    var ae = document.activeElement, focusId = ae && R.railScroll.contains(ae) ? ae.id : '', keep = R.railScroll.scrollTop;
    var b = R.railScroll; b.replaceChildren();
    S.provSig = C.part() ? JSON.stringify([C.part().part_id, C.part().reference || null]) : '';
    b.append(templateSection(), partsSection(), referenceSection(), advancedSection(), runtimeSection());
    R.railScroll.scrollTop = keep;
    if (focusId) { var n = $(focusId); if (n && !n.disabled) n.focus({ preventScroll: true }); }
    renderRunButtons(); renderExport();
  }

  /* ---- A. template */
  function templateSection() {
    var tpl = S.templates.filter(function (t) { return t.id === S.templateId; })[0];
    var st = tpl ? V().templateStatus(tpl) : null;
    var running = S.task && S.task.state === 'running';
    var body = [];
    if (S.tplErr) body.push(C.banner('err', S.tplErr));
    if (!S.templates.length && !S.tplErr) body.push(note('No template is available yet. Generate the default template (it is validated in SOLIDWORKS).'));
    var list = h('div', { class: 'rv-tpls', role: 'radiogroup', 'aria-label': 'Drawing template' });
    S.templates.forEach(function (t) {
      var ts = V().templateStatus(t), id = 'rv-tpl-' + t.id;
      var radio = h('input', { type: 'radio', name: 'rv-tpl', id: id, value: t.id, disabled: t.available === false ? true : null, onchange: function () { S.templateId = t.id; render(); } });
      radio.checked = S.templateId === t.id;
      list.append(h('div', { class: 'rv-tpl' + (S.templateId === t.id ? ' is-sel' : '') }, h('label', { class: 'chk rv-tpl-l', for: id }, radio, h('span', { class: 'rv-tpl-n', text: t.name || t.id })),
        h('div', { class: 'rv-tpl-m' }, h('span', { class: 'badge-c', text: V().sourceWord(t.source) }), h('span', { class: 'badge-c rv-badge', 'data-tone': ts.tone }, icon(ts.icon, 13), h('span', { text: ts.label })),
          t.paper ? h('span', { class: 'reason', text: typeof t.paper === 'string' ? t.paper : (t.paper.paper_size !== undefined ? 'Paper ' + t.paper.paper_size : '') }) : null,
          t.has_preview ? h('a', { class: 'linkbtn', href: '/api/reverse/templates/' + encodeURIComponent(t.id) + '/preview', target: '_blank', rel: 'noopener', text: 'Preview' }) : null),
        t.validation && t.validation.errors && t.validation.errors.length ? h('p', { class: 'reason rv-tpl-err', text: t.validation.errors.join('; ') }) : null));
    });
    body.push(list);
    var upBtn = h('button', { class: 'btn secondary sm', type: 'button', id: 'rv-tpl-upload', disabled: running ? true : null, title: running ? 'A template task is running.' : 'Upload a .drwdot template; SOLIDWORKS validates it', onclick: function () { inputs.tpl.click(); } }, icon('upload', 14), 'Upload .drwdot');
    var gen = h('button', { class: 'btn secondary sm', type: 'button', id: 'rv-tpl-generate', disabled: running ? true : null, title: running ? 'A template task is running.' : 'Create the default ANSI B template in SOLIDWORKS (takes a few minutes)', onclick: function () {
      S.tplErr = ''; C.API.generateTemplate('solidflow-ansi-b').then(function (r) { S.task = r.task; C.loadTemplates(); }, function (e) { S.tplErr = C.errText(e); render(); });
    } }, icon('layers', 14), 'Generate default');
    body.push(h('div', { class: 'rv-row' }, upBtn, gen));
    if (S.task) body.push(h('p', { class: 'reason rv-task', role: 'status', 'data-state': S.task.state, text: S.task.state === 'running' ? (S.task.label || 'Working') + '... (uses the CAD worker; this can take several minutes)' : S.task.state === 'done' ? 'Template ready.' : 'Template task failed: ' + (S.task.error || 'unknown error') }));
    var cur = tpl ? (tpl.name || tpl.id) : (S.templates.length ? 'None selected' : 'None available');
    var sec = accordion('tpl', 'Drawing template', cur, body, { action: S.acc.tpl ? 'Done' : 'Change' });
    sec.querySelector('.rv-acc-h').title = st ? st.label : '';
    return sec;
  }

  /* ---- B. parts */
  function partsSection() {
    var pk = h('section', { class: 'rv-fs', 'aria-labelledby': 'rv-parts-t' });
    pk.append(h('h3', { class: 'rv-fs-t', id: 'rv-parts-t', text: 'Part selection' }));
    pk.append(h('div', { class: 'rv-row' },
      h('button', { class: 'btn secondary sm', type: 'button', id: 'rv-pick-files', onclick: function () { inputs.files.click(); } }, icon('file-up', 14), 'Choose SLDPRT'),
      h('button', { class: 'btn secondary sm', type: 'button', id: 'rv-pick-dir', onclick: function () { inputs.dir.click(); } }, icon('folder-up', 14), 'Choose folder')));
    var rec = h('input', { type: 'checkbox', id: 'rv-rec', onchange: function () { S.recursive = rec.checked; refilterPicked(); } }); rec.checked = S.recursive;
    pk.append(h('label', { class: 'chk rv-rec-l', for: 'rv-rec' }, rec, h('span', { text: 'Include subfolders' }), tip('Applies to a chosen folder. A browser cannot read a folder path, so the chosen files are uploaded to the server (500 MB each).')));
    if (S.picked.length) {
      pk.append(h('p', { class: 'reason rv-pk-sum', id: 'rv-pk-sum', role: 'status', text: V().pickedSummary(S.picked, S.ignored || 0) }));
      pk.append(h('ul', { class: 'rv-picked', 'aria-label': 'Selected parts' }, S.picked.map(function (it, idx) {
        var cb = h('input', { type: 'checkbox', id: 'rv-pk-' + idx, onchange: function () { it.on = cb.checked; renderRunButtons(); renderReferenceLine(); } }); cb.checked = it.on !== false;
        return h('li', null, h('label', { class: 'chk', for: 'rv-pk-' + idx }, cb, h('span', { class: 'rv-pk-n', title: it.rel || it.name, text: it.name })),
          it.dup ? h('span', { class: 'badge-c warn', title: it.dup + ' files share this name; they run as separate parts', text: 'Duplicate name' }) : null,
          h('button', { class: 'ibtn', type: 'button', id: 'rv-pk-x-' + idx, 'aria-label': 'Remove ' + it.name, onclick: function () { S.picked.splice(idx, 1); S.picked = V().markDuplicates(S.picked); onPicksChanged(); render(); } }, icon('x', 14)));
      })));
      pk.append(h('button', { class: 'btn ghost sm', type: 'button', id: 'rv-pk-clear', text: 'Clear list', onclick: function () { S.picked = []; raw = []; S.ignored = 0; onPicksChanged(); render(); } }));
    } else pk.append(h('p', { class: 'reason rv-pk-sum', id: 'rv-pk-sum', role: 'status', text: S.ignored ? S.ignored + ' file(s) were ignored because they are not .SLDPRT parts.' : 'No parts chosen.' }));
    return pk;
  }

  /* ---- C. reference */
  function segmented(id, label, items, current, onPick) {
    var wrap = h('div', { class: 'seg-c rv-seg-c', role: 'radiogroup', 'aria-label': label, id: id });
    items.forEach(function (it, i) {
      var b = h('button', { type: 'button', role: 'radio', id: id + '-' + it.value, 'aria-checked': String(current === it.value), tabindex: current === it.value ? '0' : '-1', class: current === it.value ? 'on' : '', 'aria-disabled': it.disabled ? 'true' : null, title: it.title || '',
        onclick: function () { if (it.disabled) return; onPick(it.value); },
        onkeydown: function (e) {
          var k = e.key, n = k === 'ArrowRight' || k === 'ArrowDown' ? i + 1 : k === 'ArrowLeft' || k === 'ArrowUp' ? i - 1 : -1;
          if (n < 0) return; e.preventDefault();
          for (var t = 0; t < items.length; t++) { n = (n + items.length) % items.length; if (!items[n].disabled) break; n += (k === 'ArrowRight' || k === 'ArrowDown') ? 1 : -1; }
          if (!items[n].disabled) { onPick(items[n].value); var nb = $(id + '-' + items[n].value); if (nb) nb.focus(); }      /* focus follows the selection (radio group behaviour) */
        }, text: it.label });
      wrap.append(b);
    });
    return wrap;
  }
  function referenceSection() {
    var rows = rowsFor(false), match = S.refMode === 'match';
    var body = [];
    var caps = S.caps;
    body.push(segmented('rv-ref-mode', 'Reference mode', [{ value: 'standard', label: 'Standard', title: 'Generate the standard layout; no reference drawing is used.' },
      { value: 'match', label: 'Match reference', disabled: !capsOk('reference'), title: capsOk('reference') ? 'Match the layout and annotations of an existing 2D drawing.' : 'Reference matching is not available in this backend build.' }], S.refMode, setMode));
    if (caps && !capsOk('reference')) body.push(note('Reference matching is not available in this backend build; Standard runs are unaffected.', 'is-warn'));
    if (!match) body.push(note('Standard layout. No reference drawing is used.'));
    else {
      body.push(segmented('rv-ref-source', 'Reference source', [
        { value: 'auto', label: 'Auto-find', disabled: !capsOk('candidates'), title: capsOk('candidates') ? 'Look for the original drawing in saved 2D to 3D runs.' : 'Saved-source lookup is not available in this backend build.' },
        { value: 'upload', label: 'Upload PDF', disabled: !capsOk('upload'), title: capsOk('upload') ? 'Upload the reference drawing (PDF, up to 50 MB, 20 pages) for each part.' : 'Reference upload is not available in this backend build.' },
        { value: 'saved', label: 'Select saved source', disabled: !capsOk('candidates'), title: capsOk('candidates') ? 'Choose a saved source from history for each part.' : 'Saved-source lookup is not available in this backend build.' }], S.refSource, setSource));
      var line = h('div', { class: 'rv-ref-line' }, h('p', { class: 'reason rv-ref-status', id: 'rv-ref-status', role: 'status', text: F().referenceLine({ mode: 'match', rows: rows }) }),
        h('div', { class: 'rv-row' },
          h('button', { class: 'btn ghost sm', type: 'button', id: 'rv-ref-refind', text: 'Find again', disabled: !S.picked.length || !capsOk('candidates') ? true : null, title: !S.picked.length ? 'Choose parts first.' : 'Look up saved sources again', onclick: function () { forceRestage(); } }),
          h('button', { class: 'btn ghost sm', type: 'button', id: 'rv-ref-clear', text: 'Clear', disabled: !S.picked.length ? true : null, title: 'Remove the choices made here and go back to the default source', onclick: clearRefs })));
      body.push(line);
      if (S.stageErr) body.push(C.banner('err', S.stageErr));
      if (!rows.length) body.push(note('Choose parts to find their reference drawings.'));
      else body.push(h('ul', { class: 'rv-rrows', 'aria-label': 'Reference per part' }, rows.map(rowNode)));
    }
    body.push(provenanceNode());
    var sum = match ? F().referenceLine({ mode: 'match', rows: rows }) : 'Standard';
    var sec = accordion('ref', 'Reference drawing', sum, body);
    return sec;
  }
  function renderReferenceLine() {
    var n = $('rv-ref-status'), s = $('rv-acc-ref-sum'), rows = rowsFor(false);
    var t = S.refMode === 'match' ? F().referenceLine({ mode: 'match', rows: rows }) : 'Standard';
    if (n) n.textContent = t;
    if (s) { s.textContent = t; s.title = t; }
  }
  function rowNode(r) {
    var res = F().rowResolution(r), it = r.item, ref = r.ref, lk = r.lookup;
    var li = h('li', { class: 'rv-rrow', 'data-key': r.key, 'data-status': res.status });
    var ic = { ready: 'check', standard: 'dash', checking: 'spinner', unknown: 'recent', needs_confirmation: 'warn', unmatched: 'warn' }[res.status] || 'info';
    li.append(h('div', { class: 'rv-rrow-n', title: r.name, text: r.name }),
      h('div', { class: 'rv-rrow-s', 'data-tone': res.status }, h('span', { class: res.status === 'checking' ? 'rv-spin' : '' }, icon(ic, 14)), h('span', { class: 'rv-rrow-l', text: res.label })));
    if (res.note) li.append(note(res.note));
    var cands = (lk && lk.candidates) || [];
    if (cands.length && capsOk('candidates')) {
      var sel = h('select', { class: 'input-c rv-rrow-sel', id: 'rv-rsel-' + r.key, 'aria-label': 'Saved source for ' + r.name, onchange: function () {
        ref.override = true; ref.confirmed = false; ref.err = '';
        if (!sel.value) { ref.source = 'auto'; ref.override = false; ref.artifactId = ''; } else { ref.source = 'artifact'; ref.artifactId = sel.value; }
        render();
      } }, h('option', { value: '', text: lk.selected ? 'Auto-matched (change...)' : 'Choose a saved source...' }));
      cands.forEach(function (c) { sel.append(h('option', { value: c.artifact_id, text: F().candidateLine(c) + (c.needs_confirmation ? ' (needs confirmation)' : '') })); });
      sel.value = r.source === 'artifact' ? r.artifactId : '';
      li.append(sel);
      if (res.status === 'needs_confirmation' && r.source === 'artifact') {
        li.append(h('button', { class: 'btn secondary sm', type: 'button', id: 'rv-rconf-' + r.key, text: 'Confirm this source', disabled: ref.confirming ? true : null, onclick: function () { confirmRow(r); } }));
      }
      var cand = cands.filter(function (c) { return c.artifact_id === (r.source === 'artifact' ? r.artifactId : (lk.selected && lk.selected.artifact_id)); })[0];
      if (cand && cand.reasons && cand.reasons.length) li.append(note('Why: ' + cand.reasons.join('; ')));
    }
    if (ref.err) li.append(h('p', { class: 'reason rv-rrow-err', role: 'alert', text: ref.err }));
    var acts = h('div', { class: 'rv-rrow-a' });
    acts.append(h('button', { class: 'btn ghost sm', type: 'button', id: 'rv-rup-' + r.key, disabled: !capsOk('upload') || ref.uploading ? true : null, title: capsOk('upload') ? 'Upload a reference PDF for this part only (overrides the lookup)' : 'Reference upload is not available in this backend build.',
      onclick: function () { refTarget = it; inputs.ref.click(); } }, icon('upload', 13), ref.uploading ? 'Uploading...' : (r.source === 'upload' && r.upload ? 'Replace PDF' : 'Upload PDF')));
    if (r.source !== 'none') acts.append(h('button', { class: 'btn ghost sm', type: 'button', id: 'rv-rstd-' + r.key, text: 'Use Standard', title: 'Run only this part in Standard layout (explicit choice)', onclick: function () { ref.override = true; ref.source = 'none'; ref.err = ''; render(); } }));
    if (ref.override) acts.append(h('button', { class: 'btn ghost sm', type: 'button', id: 'rv-rreset-' + r.key, text: 'Reset', title: 'Go back to the default source for this part', onclick: function () { ref.override = false; ref.source = 'auto'; ref.upload = null; ref.artifactId = ''; ref.confirmed = false; ref.err = ''; render(); } }));
    li.append(acts);
    return li;
  }
  /** What the selected finished part used (job_view part.reference): provenance and extraction details. Collapsed until the user opens it. */
  function provenanceNode() {
    var p = C.part(), ref = p && p.reference, rows = F().provenanceRows(ref);
    var body = [];
    if (!rows.length) body.push(note(p ? 'No reference was used for the selected part.' : 'Select a part from a run to see what reference it used.'));
    else {
      body.push(h('dl', { class: 'rv-kv rv-prov-kv' }, rows.map(function (x) { return [h('dt', { text: x[0] }), h('dd', { text: x[1] })]; })));
      (ref.warnings || []).forEach(function (w) { body.push(h('p', { class: 'reason is-warn', text: w })); });
    }
    return accordion('prov', 'Provenance and extraction', p && rows.length ? F().refStatusInfo(ref).label : 'Selected part', body);
  }

  function renderProvenance() {
    var old = $('rv-acc-prov'); if (!old) return;
    var p = C.part(), sig = p ? JSON.stringify([p.part_id, p.reference || null]) : '';
    if (sig === S.provSig) return;
    S.provSig = sig;
    old.replaceWith(provenanceNode());
  }

  /* ---- D. advanced */
  function advancedSection() {
    var body = [];
    var cfg = h('input', { class: 'input-c', id: 'rv-cfg', type: 'text', maxlength: '80', placeholder: 'Active configuration', value: S.config, oninput: function () { S.config = cfg.value; } });
    body.push(h('div', { class: 'fld' }, h('label', { for: 'rv-cfg', text: 'Configuration (blank = active saved one)' }), cfg));
    var ps = h('select', { class: 'input-c', id: 'rv-prof', onchange: function () { S.profile = ps.value; render(); } });
    if (!S.profiles.length) ps.append(h('option', { value: S.profile, text: 'Profiles unavailable' }));
    S.profiles.forEach(function (p) { ps.append(h('option', { value: p.id, text: p.id.replace(/_/g, ' ') })); });
    ps.value = S.profile;
    var cur = S.profiles.filter(function (p) { return p.id === S.profile; })[0];
    body.push(h('div', { class: 'fld' }, h('label', { for: 'rv-prof', text: 'Drawing profile (projection, units, paper)' }), ps));
    if (cur) body.push(note(cur.projection.replace(/_/g, ' ') + ' projection, ' + cur.units + ', ' + cur.paper));
    var sf = h('details', { class: 'rv-sf' }, h('summary', { text: 'Run a folder on the server' }));
    var sfIn = h('input', { class: 'input-c', id: 'rv-sf-in', type: 'text', placeholder: 'Absolute path inside an authorized folder', 'aria-label': 'Server folder', autocomplete: 'off' });
    var matchOn = S.refMode === 'match';
    var sfBtn = h('button', { class: 'btn secondary sm', type: 'button', id: 'rv-sf-run', text: 'Run folder', onclick: function () { runFolder(sfIn.value); } });
    function sfState() { sfBtn.disabled = !sfIn.value.trim() || matchOn; sfBtn.title = matchOn ? 'Reference matching needs parts chosen in this browser. Switch to Standard to run a server folder.' : (!sfIn.value.trim() ? 'Enter a folder path first.' : ''); }
    sfIn.addEventListener('input', sfState); sfState();
    sf.append(note('Only folders the server operator authorized (SOLIDFLOW_REVERSE_ROOTS) are accepted; anything else is refused.'), sfIn, sfBtn);
    if (S.serverFolderOpen) sf.open = true;
    sf.addEventListener('toggle', function () { S.serverFolderOpen = sf.open; });
    body.push(sf);
    body.push(note('Each run is stored with the app data under outputs/3d-to-2d/<run>/<part>/. Nothing is written into your part folder.'));
    return accordion('adv', 'Advanced settings', 'Configuration, profile, server folder', body);
  }

  /* ---- E. runtime and cost */
  function runtimeTexts() {
    var j = S.job, n = selectedPicked(false).length || S.picked.length || 1;
    var haveEst = S.estimate && S.estimateN === n;
    var est = haveEst ? V().estimateText(S.estimate) : (S.estimateFail ? 'unavailable' : 'checking...');
    var cs = F().costSummary(j, est, S.refMode);
    return { n: n, est: 'Estimated for ' + n + ' part' + (n === 1 ? '' : 's') + ': ' + est, measured: j ? 'Measured this run: ' + (V().runtimeText(j.parts) || 'Not measured yet') : '', openai: cs.openai,
      sum: (haveEst ? V().estimateText(S.estimate).split(' (')[0] : (S.estimateFail ? 'Estimate unavailable' : 'Estimate pending')) + ' · ' + (S.refMode === 'match' ? 'OpenAI may be used' : (S.job && /\$[0-9]/.test(cs.openai) ? 'OpenAI used in last run' : 'no OpenAI')) };
  }
  function runtimeSection() {
    var t = runtimeTexts();
    var body = [
      h('div', { class: 'rv-cost' }, h('h4', { class: 'rv-cost-h', text: 'Local CAD time (no token cost)' }), h('p', { class: 'reason', id: 'rv-est', text: t.est }),
        h('p', { class: 'reason', id: 'rv-measured', text: t.measured, hidden: t.measured ? null : true })),
      h('div', { class: 'rv-cost' }, h('h4', { class: 'rv-cost-h', text: 'OpenAI (reference extraction only)' }), h('p', { class: 'reason', id: 'rv-openai', text: t.openai }))
    ];
    return accordion('rt', 'Runtime and cost', t.sum, body);
  }
  /** In-place refresh of the runtime / cost lines (job polled, estimate arrived): no re-render, so an open accordion and the focus are untouched. */
  function renderRuntime() {
    var t = runtimeTexts(), set = function (id, txt, hide) { var e = $(id); if (e) { e.textContent = txt; if (hide !== undefined) e.hidden = hide; } };
    set('rv-est', t.est); set('rv-measured', t.measured, !t.measured); set('rv-openai', t.openai);
    var s = $('rv-acc-rt-sum'); if (s) { s.textContent = t.sum; s.title = t.sum; }
  }

  /* ───────────────────────── run controls (foot) ───────────────────────── */
  function renderRunButtons() {
    if (!R.runSel) return;
    var tpl = S.templates.filter(function (t) { return t.id === S.templateId; })[0];
    var base = { templateId: S.templateId, templateReason: S.templateId ? V().templateBlock(tpl) : '', taskRunning: !!(S.task && S.task.state === 'running'), submitting: S.submitting };
    var rs = V().runBlock(Object.assign({ count: selectedPicked(false).length }, base)), ra = V().runBlock(Object.assign({ count: S.picked.length }, base));
    var rb = F().referenceRunBlock({ mode: S.refMode, rows: rowsFor(false), caps: S.caps }), rbAll = F().referenceRunBlock({ mode: S.refMode, rows: rowsFor(true), caps: S.caps });
    if (!rs && rb.reason) rs = rb.reason;
    if (!ra && rbAll.reason) ra = rbAll.reason;
    R.runSel.disabled = !!rs; R.runSel.title = rs || 'Run the checked parts'; R.runAll.disabled = !!ra; R.runAll.title = ra || 'Run every chosen part';
    R.runWhy.textContent = rs && ra ? rs : (rs && !ra ? 'Run selected: ' + rs : '');
    R.runWhy.hidden = !R.runWhy.textContent;
    var n = selectedPicked(false).length || S.picked.length || 1;
    if (!(S.estimate && S.estimateN === n)) {
      var want = n; C.API.estimate(n).then(function (e) { S.estimate = e; S.estimateN = want; S.estimateFail = false; updateEstimate(); }, function () { S.estimate = null; S.estimateN = want; S.estimateFail = true; updateEstimate(); });
    }
    var j = S.job, active = j && V().isActive(j.summary_state);
    R.runLive.hidden = !active; R.runLive.textContent = active ? V().progressText(j.progress, j.summary_state) : '';
  }
  function updateEstimate() { renderRuntime(); }

  /* ───────────────────────── export (foot) ───────────────────────── */
  function renderExport() {
    var box = R.exportBox; if (!box) return;
    var p = C.part(), v = F().exportView(S.exportInfo, S.ack, S.exportBusy);
    box.replaceChildren();
    var hd = h('div', { class: 'rv-exp-h' }, h('h3', { class: 'rv-fs-t', id: 'rv-exp-t', text: 'Export' }));
    if (p && v.ready) hd.append(h('span', { class: 'badge-c rv-badge rv-draft', 'data-tone': v.status.tone, id: 'rv-exp-status', title: v.status.reasons.join(' ') }, icon(v.status.tone === 'red' ? 'x' : v.status.tone === 'amber' ? 'warn' : 'info', 13), h('span', { text: v.status.label })));
    box.append(hd);
    if (S.exportErr) box.append(h('p', { class: 'reason is-warn', role: 'status', text: 'Export status unavailable: ' + S.exportErr }));
    var row = h('div', { class: 'rv-exp-b', role: 'group', 'aria-labelledby': 'rv-exp-t' });
    v.buttons.forEach(function (b) {
      var ic = b.kind === 'zip' ? 'files' : 'download';
      row.append(h('button', { class: 'btn secondary sm', type: 'button', id: 'rv-exp-' + b.kind, 'data-kind': b.kind, disabled: b.enabled ? null : true, title: b.enabled ? b.label + (b.filename ? ' (' + b.filename + ')' : '') : b.reason,
        onclick: function () { doExport(b.kind); } }, icon(ic, 14), b.label));
    });
    box.append(row);
    if (v.ready && v.needsAck && v.any) {
      var cb = h('input', { type: 'checkbox', id: 'rv-exp-ack', 'aria-describedby': 'rv-exp-why', onchange: function () { S.ack = cb.checked; renderExport(); } }); cb.checked = !!S.ack;
      box.append(h('label', { class: 'chk rv-exp-ack', for: 'rv-exp-ack' }, cb, h('span', { text: 'I understand this is an unapproved draft for engineering review, not approved for manufacture.' })));
      box.append(h('p', { class: 'reason', id: 'rv-exp-why', text: v.status.reasons.join(' ') }));
    } else if (v.ready) box.append(h('p', { class: 'reason', id: 'rv-exp-why', hidden: v.any ? true : null, text: v.any ? 'PRELIMINARY / FOR REVIEW. Not approved for manufacture.' : (v.buttons.map(function (b) { return b.reason; }).filter(Boolean)[0] || 'Nothing to export yet.') }));
    else box.append(h('p', { class: 'reason', id: 'rv-exp-why', text: 'Select a part from a run to export its drawing.' }));
  }
  function refreshExport() {
    var p = C.part(), j = S.job, key = F().exportKey(j, p);
    if (key === S.exportKey) return;
    S.exportKey = key; S.ack = false; S.exportInfo = null; S.exportErr = '';
    renderExport();
    if (!key) return;
    var tok = ++exportTok, jid = j.job_id, pid = p.part_id;
    C.API.exportInfo(jid, pid).then(function (info) { if (tok !== exportTok || S.exportKey !== key) return; S.exportInfo = info; renderExport(); },
      function (e) { if (tok !== exportTok || S.exportKey !== key) return; S.exportErr = C.errText(e); renderExport(); });
  }
  function filenameFrom(cd, fallback) {
    var m = /filename\*=UTF-8''([^;]+)/i.exec(cd || '') || /filename="?([^";]+)"?/i.exec(cd || '');
    var n = m ? decodeURIComponent(m[1]) : fallback;
    return String(n || fallback || 'drawing').replace(/[\\/:*?"<>|\x00-\x1f]+/g, '_').slice(0, 120);
  }
  function doExport(kind) {
    var v = F().exportView(S.exportInfo, S.ack, S.exportBusy), b = v.buttons.filter(function (x) { return x.kind === kind; })[0];
    if (!b || !b.enabled) return;
    var j = S.job, p = C.part(); if (!j || !p) return;
    var jid = j.job_id, pid = p.part_id, key = S.exportKey, st = v.status;
    var q = [];
    if (kind !== 'zip') q.push('expect=' + (b.bytes || 0));
    if (st.requires_ack) q.push('ack=1');
    var url = '/api/reverse/jobs/' + encodeURIComponent(jid) + '/parts/' + encodeURIComponent(pid) + '/export/' + kind + (q.length ? '?' + q.join('&') : '');
    S.exportBusy = true; renderExport();
    fetch(url).then(function (res) {
      if (res.ok) return res.blob().then(function (blob) { return { blob: blob, name: filenameFrom(res.headers.get('content-disposition'), b.filename) }; });
      return res.text().then(function (t) { var d = ''; try { d = JSON.parse(t).detail; } catch (e) { /* not json */ } throw new Error(d || ('HTTP ' + res.status)); });
    }).then(function (r) {
      var href = URL.createObjectURL(r.blob), a = document.createElement('a');
      a.href = href; a.download = r.name; a.rel = 'noopener'; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(href); }, 4000);
      C.toast('Downloaded ' + r.name + '. ' + st.label + '.', 'ok');
    }).catch(function (e) {
      C.toast('Export failed for ' + p.name + ': ' + ((e && e.message) || 'unknown error'), 'err');
      if (S.exportKey === key) { S.exportKey = ''; refreshExport(); }          // the files may have changed: re-read what really exists
    }).then(function () { S.exportBusy = false; renderExport(); });
  }

  /* ───────────────────────── reference flow: stage, lookup, confirm, upload ───────────────────────── */
  function fingerprint() { return S.picked.map(function (it) { return it.name + '|' + (it.file && it.file.size) + '|' + (it.file && it.file.lastModified); }).join(';'); }
  function setMode(m) {
    if (m === S.refMode) return;
    S.refMode = m;
    if (m === 'match') { setAcc('ref', true); if (S.picked.length) scheduleStage(0); }
    render();
  }
  function setSource(s) {
    S.refSource = s;
    if (s !== 'upload' && S.picked.length && !(S.stage && S.stage.id)) scheduleStage(0);
    render();
  }
  function clearRefs() {
    S.picked.forEach(function (it) { var r = refOf(it); r.override = false; r.source = 'auto'; r.upload = null; r.artifactId = ''; r.confirmed = false; r.err = ''; });
    render();
  }
  function onPicksChanged() {
    if (S.refMode === 'match') scheduleStage(350);
    S.estimate = null;
  }
  function scheduleStage(ms) { clearTimeout(stageTimer); if (!S.picked.length || !capsOk('candidates')) return; stageTimer = setTimeout(function () { ensureStage(); }, ms); }
  function forceRestage() { if (S.stage && S.stage.id) dropStage(S.stage.id); S.stage = null; ensureStage(); }
  function dropStage(id) { C.API.dropStage(id).catch(function () { /* expired already */ }); }
  /** Upload the chosen parts once so the server can look their references up (and run from the same copies). Resolves with the stage or null. */
  function ensureStage() {
    if (!S.picked.length) return Promise.resolve(null);
    var fp = fingerprint();
    if (S.stage && S.stage.fp === fp && !S.stage.err) return S.stage.promise || Promise.resolve(S.stage);
    if (S.stage && S.stage.id) dropStage(S.stage.id);
    var st = { fp: fp, id: '', err: '' };
    S.stage = st; S.stageErr = '';
    var fd = new FormData();
    S.picked.forEach(function (i) { fd.append('files', i.file, i.name); });
    if (S.config.trim()) fd.append('config', S.config.trim());
    S.picked.forEach(function (it) { var r = refOf(it); r.looking = true; r.lookup = null; });
    render();
    st.promise = C.API.stage(fd).then(function (r) {
      if (S.stage !== st) { dropStage(r.stage_id); return null; }
      st.id = r.stage_id; return lookupAll(st).then(function () { return st; });
    }).catch(function (e) {
      st.err = C.errText(e); if (S.stage === st) { S.stageErr = st.err; S.picked.forEach(function (it) { refOf(it).looking = false; }); render(); }
      return null;
    });
    return st.promise;
  }
  function lookupAll(st) {
    S.picked.forEach(function (it) { refOf(it).looking = true; });
    render();
    return C.API.candidates({ stage_id: st.id }).then(function (res) {
      if (S.stage !== st) return;
      var byKey = {}; (res.rows || []).forEach(function (r) { byKey[r.key] = r; });
      S.picked.forEach(function (it, idx) {
        var r = refOf(it), row = byKey['p' + idx];
        r.looking = false; r.lookup = row ? { selected: row.selected || null, candidates: row.candidates || [], error: row.error || '' } : { selected: null, candidates: [], error: '' };
        if (r.source === 'artifact' && !r.lookup.candidates.some(function (c) { return c.artifact_id === r.artifactId; })) { r.source = 'auto'; r.override = false; r.artifactId = ''; r.confirmed = false; }
      });
      render();
    }, function (e) {
      S.picked.forEach(function (it) { refOf(it).looking = false; });
      if (e && e.status === 404) { S.stage = null; S.stageErr = 'The part selection expired on the server. Press Find again.'; } else S.stageErr = C.errText(e);
      render();
    });
  }
  function confirmRow(r) {
    var st = S.stage; if (!st || !st.id) return;
    r.ref.confirming = true; render();
    C.API.confirm({ stage_id: st.id, key: r.key, artifact_id: r.artifactId }).then(function () {
      r.ref.confirming = false; r.ref.confirmed = true; r.ref.err = ''; C.toast('Reference confirmed for ' + r.name, 'ok'); render();
    }, function (e) { r.ref.confirming = false; r.ref.err = C.errText(e); render(); });
  }
  function uploadRef(file) {
    var it = refTarget; refTarget = null;
    if (!it || !file) return;
    var r = refOf(it);
    if (!/\.pdf$/i.test(file.name)) { r.err = 'Only PDF files are accepted as a reference drawing.'; render(); return; }
    if (file.size > 50 * 1024 * 1024) { r.err = 'That PDF is larger than 50 MB.'; render(); return; }
    r.uploading = true; r.err = ''; render();
    C.API.uploadReference(file).then(function (u) {
      r.uploading = false; r.override = true; r.source = 'upload'; r.upload = { upload_id: u.upload_id, filename: u.filename || file.name, pages: u.pages, sha256: u.sha256 };
      C.toast('Reference PDF uploaded for ' + it.name, 'ok'); render();
    }, function (e) { r.uploading = false; r.err = C.errText(e); render(); });
  }

  /* ───────────────────────── part picking ───────────────────────── */
  function addPicked(files, fromFolder) {
    files.forEach(function (f) { raw.push({ file: f, name: f.name, rel: fromFolder ? (f.webkitRelativePath || f.name) : '' }); });
    refilterPicked();
  }
  function refilterPicked() {
    var seen = {};
    var ok = V().filterPicked(raw.map(function (r) { return { name: r.name, rel: r.rel, file: r.file }; }), S.recursive).filter(function (i) { var k = (i.rel || '') + '|' + i.name + '|' + (i.file && i.file.size) + '|' + (i.file && i.file.lastModified); if (seen[k]) return false; seen[k] = 1; return true; });
    S.ignored = raw.filter(function (r) { return !V().isSldprt(r.name) || /^~\$/.test(r.name); }).length;
    var prevOff = {}; S.picked.forEach(function (i) { if (i.on === false) prevOff[(i.rel || '') + '|' + i.name] = true; });
    S.picked = V().markDuplicates(ok.map(function (i) { i.on = !prevOff[(i.rel || '') + '|' + i.name]; return i; }));
    onPicksChanged(); render();
  }

  /* ───────────────────────── submit ───────────────────────── */
  function runPicked(all) {
    var items = selectedPicked(all);
    if (!items.length || S.submitting) return;
    if (S.refMode === 'match') { runMatch(all, items); return; }
    var fd = new FormData();
    items.forEach(function (i) { fd.append('files', i.file, i.name); });
    fd.append('template_id', S.templateId); fd.append('profile', S.profile); if (S.config.trim()) fd.append('config', S.config.trim());
    S.submitting = true; S.submitErr = ''; renderRunButtons(); C.renderNotice();
    C.API.submit(fd).then(afterSubmit, submitFail);
  }
  function runMatch(all, items) {
    var rows = rowsFor(all), blk = F().referenceRunBlock({ mode: 'match', rows: rows, caps: S.caps });
    if (blk.reason) { S.submitErr = blk.reason; if (blk.actionable.length) setAcc('ref', true); C.renderNotice(); return; }
    S.submitting = true; S.submitErr = ''; renderRunButtons(); C.renderNotice();
    ensureStage().then(function (st) {
      if (!st || !st.id) throw { detail: S.stageErr || 'The parts could not be sent to the server.' };
      var rows2 = rowsFor(all), blk2 = F().referenceRunBlock({ mode: 'match', rows: rows2, caps: S.caps });
      if (blk2.reason) { setAcc('ref', true); throw { detail: blk2.reason }; }
      var body = { stage_id: st.id, keys: rows2.map(function (r) { return r.key; }), template_id: S.templateId, profile: S.profile, config: S.config.trim(), reference: F().buildReferencePayload('match', rows2) };
      return C.API.submitFolder(body);
    }).then(function (r) { S.stage = null; afterSubmit(r); }, function (e) {
      if (e && e.status === 404) { S.stage = null; e = { detail: 'The part selection expired on the server. Press Run again to re-send the parts.' }; }
      if (e && e.status === 409) setAcc('ref', true);
      submitFail(e);
    });
  }
  function runFolder(path) {
    if (!path.trim() || S.submitting || S.refMode === 'match') return;
    S.submitting = true; S.submitErr = ''; renderRunButtons();
    C.API.submitFolder({ folder: path.trim(), recursive: S.recursive, template_id: S.templateId, profile: S.profile, config: S.config.trim() }).then(afterSubmit, submitFail);
  }
  function afterSubmit(r) {
    S.submitting = false;
    S.sessionJobs.push(r.job_id);
    S.notice = r.rejected && r.rejected.length ? r.rejected.length + ' file(s) were not run: ' + r.rejected.map(function (x) { return x.reason; }).join(' ') : null;
    raw = []; S.picked = []; S.ignored = 0; S.stage = null;
    C.announce('Run started with ' + r.parts.length + ' part(s)');
    render();
    S.jobId = ''; S.job = null;
    return C.refreshJobs().then(function () { return C.selectJob(r.job_id, ''); });
  }
  function submitFail(e) { S.submitting = false; S.notice = null; S.submitErr = C.errText(e); render(); C.renderNotice(); }

  /* ───────────────────────── init ───────────────────────── */
  function init(ctx) {
    C = ctx; S = ctx.S; R = ctx.R;
    S.acc = loadAcc(); S.refMode = 'standard'; S.refSource = 'auto'; S.stage = null; S.caps = null; S.ack = false; S.exportInfo = null; S.exportKey = ''; S.exportBusy = false;
    inputs.files = h('input', { type: 'file', id: 'rv-files', class: 'dz-input', multiple: true, accept: '.sldprt,.SLDPRT', tabindex: '-1', 'aria-label': 'SLDPRT files', onchange: function () { addPicked(Array.prototype.slice.call(inputs.files.files), false); inputs.files.value = ''; } });
    inputs.dir = h('input', { type: 'file', id: 'rv-dir', class: 'dz-input', multiple: true, webkitdirectory: true, tabindex: '-1', 'aria-label': 'Folder of parts', onchange: function () { addPicked(Array.prototype.slice.call(inputs.dir.files), true); inputs.dir.value = ''; } });
    inputs.ref = h('input', { type: 'file', id: 'rv-ref-file', class: 'dz-input', accept: '.pdf,application/pdf', tabindex: '-1', 'aria-label': 'Reference PDF', onchange: function () { var f = inputs.ref.files && inputs.ref.files[0]; inputs.ref.value = ''; uploadRef(f); } });
    inputs.tpl = h('input', { type: 'file', id: 'rv-tpl-file', class: 'dz-input', accept: '.drwdot', tabindex: '-1', 'aria-label': 'Drawing template file', onchange: function () {
      var f = inputs.tpl.files && inputs.tpl.files[0]; inputs.tpl.value = '';
      if (!f) return;
      if (!/\.drwdot$/i.test(f.name)) { S.tplErr = 'Only .drwdot templates are accepted.'; render(); return; }
      S.tplErr = '';
      C.API.uploadTemplate(f).then(function (r) { S.task = r.task; C.announce('Template validation started'); C.loadTemplates(); }, function (e) { S.tplErr = C.errText(e); render(); });
    } });
    R.railInputs = h('div', { class: 'rv-inputs', 'aria-hidden': 'true' }, inputs.files, inputs.dir, inputs.ref, inputs.tpl);
    R.railScroll = h('div', { class: 'rv-setup-scroll', id: 'rv-setup-scroll' });
    R.runSel = h('button', { class: 'btn gold', type: 'button', id: 'rv-run-sel', 'aria-describedby': 'rv-run-why', onclick: function () { runPicked(false); } }, icon('play', 16), 'Run selected');
    R.runAll = h('button', { class: 'btn secondary', type: 'button', id: 'rv-run-all', 'aria-describedby': 'rv-run-why', onclick: function () { runPicked(true); } }, icon('play-all', 16), 'Run all');
    R.runWhy = h('p', { class: 'reason', id: 'rv-run-why', role: 'status' });
    R.runLive = h('p', { class: 'reason rv-run-live', id: 'rv-run-live', role: 'status', hidden: true });
    R.exportBox = h('section', { class: 'rv-export', id: 'rv-export', 'aria-labelledby': 'rv-exp-t' });
    R.railFoot = h('div', { class: 'rv-setup-foot' },
      h('div', { class: 'rv-run' }, h('div', { class: 'rv-row rv-run-row' }, R.runSel, R.runAll), R.runWhy, R.runLive), R.exportBox);
    return { scroll: R.railScroll, foot: R.railFoot, inputs: R.railInputs };
  }

  McA.reverseRail = { init: init, render: render, renderProvenance: renderProvenance, renderRuntime: renderRuntime, renderRunButtons: renderRunButtons, renderExport: renderExport, refreshExport: refreshExport, setAcc: setAcc, openReference: function () { setAcc('ref', true); },
    _internals: { rowsFor: rowsFor, ensureStage: ensureStage, state: function () { return { raw: raw.length }; } } };
})();
