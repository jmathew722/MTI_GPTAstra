/* McA.cropper: the focus overlay. The photoapp iframe (#photoapp) is created once in index.html and is
   never reloaded or removed; the overlay is only shown and hidden, so queued crops survive.
   Communication stays exactly as in bridge.js: hookCadIntake at boot, collect, sendImage, and one
   message listener for cad-open and src-open (ARCH 10). */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var $ = function (id) { return document.getElementById(id); };
  var h = function () { return McA.dom.h.apply(null, arguments); };
  var store = function () { return McA.store; };

  var HINT = {
    crop: 'Crop each orthographic view, then pull the queued crops into Part Setup.',
    mark: 'Highlight dimension regions before extraction. Color = feature group (a hole and its X and Y dimensions share one color).'
  };
  var opener = null, wasOpen = false, loadBtn = null;
  var INERT = ['sidebar', 'main', 'sb-scrim'];

  function iframe() { return $('photoapp'); }
  function stem(name) { return String(name || 'drawing').replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9_-]+/g, '_'); }

  function open(mode, from) {
    opener = from || document.activeElement;
    store().dispatch('ui/set', { focusMode: mode === 'mark' ? 'mark' : 'crop' });
  }
  function close(expandSetup) {
    if (expandSetup) McA.dom.dispatch('ui/inspectorSection', { id: 'setup', open: true });
    store().dispatch('ui/set', { focusMode: null });
  }

  function render() {
    var s = store().get(), mode = s.ui.focusMode, isOpen = !!mode;
    var focus = $('focus');
    focus.hidden = !isOpen;
    INERT.forEach(function (id) { var n = $(id); if (n) { if (isOpen) n.setAttribute('inert', ''); else n.removeAttribute('inert'); } });
    if (!isOpen) {
      if (wasOpen && opener && document.contains(opener) && opener.focus) opener.focus();
      wasOpen = false; return;
    }
    $('crop-view').hidden = mode !== 'crop';
    $('mark-view').hidden = mode !== 'mark';
    [['crop', 'crop-mode-crop'], ['mark', 'crop-mode-mark']].forEach(function (p) {
      var b = $(p[1]), on = mode === p[0];
      b.setAttribute('aria-selected', String(on)); b.classList.toggle('on', on); b.tabIndex = on ? 0 : -1;
    });
    $('focus-title').textContent = mode === 'mark' ? 'Mark regions' : 'Crop views';
    $('crop-mode-hint').textContent = HINT[mode];
    var it = s.intake, sel = s.parts.selected;
    $('focus-file').textContent = (it.originalFile && it.originalFile.name) || (it.source ? it.stem : '') || (sel ? sel.part : '');
    loadBtn.hidden = !(mode === 'crop' && it.source);
    $('mark-save-state').hidden = mode !== 'mark';
    $('pull-crops-btn').hidden = mode !== 'crop';
    if (mode === 'mark' && McA.markup && McA.markup.onShow) McA.markup.onShow();
    if (!wasOpen) {
      wasOpen = true;
      var t = $(mode === 'mark' ? 'crop-mode-mark' : 'crop-mode-crop'); if (t) t.focus();
    }
  }

  function sendToCropper() {
    var it = store().get().intake;
    if (!it.source) return;
    var name = (it.stem || 'drawing') + '.png';
    store().dispatch('intake/update', { patch: { expectEcho: name } });
    window.MTIBridge.sendImage(iframe(), it.source, name).then(function () {
      McA.toast.show('Loaded the drawing into the cropper.', 'ok');
    }, function (e) { McA.toast.show('Could not load the drawing into the cropper: ' + e.message, 'err'); });
  }

  /* Messages from the cropper frame (bridge.js): cad-open and src-open. */
  function onMessage(ev) {
    var d = ev.data;
    if (!d || !d.__mti) return;
    var fr = iframe();
    if (!fr || ev.source !== fr.contentWindow) return;
    var st = store();
    if (d.__mti === 'cad-open' && d.buf) {
      var f = new File([d.buf], d.name, { type: 'application/octet-stream' });
      McA.intake.loadCad(f, stem(d.name), '', !st.get().intake.items.length)
        .catch(function (e) { McA.toast.show('Could not convert ' + d.name + ': ' + ((e && (e.detail || e.message)) || 'error'), 'err'); });
      return;
    }
    if (d.__mti === 'src-open' && d.dataURL) {
      var it = st.get().intake;
      if (it.expectEcho && d.name === it.expectEcho) { st.dispatch('intake/update', { patch: { expectEcho: false } }); return; }
      var sname = stem(d.name);
      if (!(it.source && it.stem === sname)) {
        var ext = (String(d.name).split('.').pop() || '').toLowerCase();
        var patch = { source: d.dataURL, stem: sname, originalFile: null, format: ext === 'pdf' ? 'PDF' : 'Image (' + ext.toUpperCase() + ')', previewOverride: true };
        if (!String(it.nameDraft || '').trim()) patch.nameDraft = sname;
        st.dispatch('intake/update', { patch: patch });
      } else {
        st.dispatch('intake/update', { patch: { previewOverride: true } });
      }
    }
  }

  function hookIframeKeys() {
    var fr = iframe();
    function attach() {
      try {
        var doc = fr.contentDocument;
        if (!doc || doc.__mcaEsc) return;
        doc.__mcaEsc = true;
        doc.addEventListener('keydown', function (e) { if (e.key === 'Escape' && e.shiftKey) { e.preventDefault(); close(false); } });
      } catch (e) { /* frame not reachable */ }
    }
    fr.addEventListener('load', attach); attach();
  }

  McA.cropper = {
    open: open, close: close,
    init: function () {
      var fr = iframe();
      if (window.MTIBridge && fr) window.MTIBridge.hookCadIntake(fr);
      window.addEventListener('message', onMessage);
      if (fr) hookIframeKeys();

      loadBtn = h('button', { class: 'btn secondary', type: 'button', text: 'Load this drawing into the cropper', hidden: true });
      loadBtn.addEventListener('click', sendToCropper);
      $('pull-crops-btn').before(loadBtn);

      $('focus-close').addEventListener('click', function () { close(false); });
      $('pull-crops-btn').addEventListener('click', function () { McA.intake.pullCrops(); });
      $('crop-mode-crop').addEventListener('click', function () { store().dispatch('ui/set', { focusMode: 'crop' }); });
      $('crop-mode-mark').addEventListener('click', function () { store().dispatch('ui/set', { focusMode: 'mark' }); });
      $('focus').querySelector('.seg-c').addEventListener('keydown', function (e) {
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
        e.preventDefault();
        var m = e.key === 'ArrowLeft' ? 'crop' : 'mark';
        store().dispatch('ui/set', { focusMode: m });
        $(m === 'crop' ? 'crop-mode-crop' : 'crop-mode-mark').focus();
      });
      document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape' || !store().get().ui.focusMode || McA.dialog.isOpen()) return;
        e.preventDefault(); close(false);
      });

      /* Entry points. */
      var mark = $('mark-regions-btn'), crop = $('open-cropper-btn');
      crop.addEventListener('click', function () { open('crop', crop); });
      mark.addEventListener('click', function () { open('mark', mark); });

      store().subscribe(function (s) { return s.ui.focusMode; }, render);
      store().subscribe(function (s) { return s.intake.source; }, render);
      store().subscribe(function (s) { return s.intake.originalFile; }, render);
      render();
    }
  };
})();
