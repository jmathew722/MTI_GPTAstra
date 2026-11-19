/* McA.recording: the "SolidWorks recording" section of Pipeline Results and the "Record pipeline run" run option.
   The pipeline records only the SolidWorks window during the native build (pipeline/solidworks_recorder.py); this file shows what the
   server validated: a player with speed control and feature chapters, or the exact reason there is no video. All text goes through
   textContent; the video URL comes only from api.js builders. What to say in each state is decided by McA.recordingview (pure). */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var RV = McA.recordingview;
  var h = function () { return McA.dom.h.apply(null, arguments); };
  var speed = 1;                 // remembered between renders (the results pane is rebuilt on every refresh)
  var kept = { key: '', node: null };   // the player is reused for the same recording, so a refresh keeps the playback position

  function tone(t) { return ['ok', 'warn', 'err', 'steel'].indexOf(t) === -1 ? 'steel' : t; }

  function player(ctx, rec, d) {
    var key = ctx.session + '|' + ctx.part + '|' + rec.generation_key;
    if (kept.key === key && kept.node) return kept.node;
    var src = McA.api.recordingVideoURL(ctx.session, ctx.part, rec.generation_key);
    var vid = h('video', { class: 'rec-video', controls: true, preload: 'metadata', playsinline: true, 'aria-label': 'Recording of the SolidWorks build' });
    if (rec.has_poster) vid.setAttribute('poster', McA.api.recordingPosterURL(ctx.session, ctx.part, rec.generation_key));
    vid.src = src;
    vid.playbackRate = speed;

    var chapters = rec.chapters || [], items = [];
    var list = h('ol', { class: 'rec-chapters', 'aria-label': 'Features in this recording' });
    chapters.forEach(function (c, i) {
      var b = h('button', { type: 'button', class: 'rec-chap' },
        h('span', { class: 'rec-chap-l', text: c.label || c.id }), h('span', { class: 'rec-chap-t mono', text: RV.fmtDuration(c.t) }));
      b.addEventListener('click', function () {
        vid.currentTime = RV.seekTime(c, vid.duration || rec.duration_s || 0);
        var p = vid.play(); if (p && p.catch) p.catch(function () { /* the person can press play */ });
      });
      items.push(b);
      list.append(h('li', null, b));
    });
    function mark() {
      var at = RV.chapterAt(chapters, vid.currentTime || 0);
      items.forEach(function (b, i) { if (i === at) b.setAttribute('aria-current', 'true'); else b.removeAttribute('aria-current'); });
    }
    vid.addEventListener('timeupdate', mark);
    vid.addEventListener('seeked', mark);
    vid.addEventListener('error', function () {
      if (!node.querySelector('.rec-vid-err')) node.prepend(h('div', { class: 'banner is-err rec-vid-err', role: 'alert' }, McA.icons.get('warn', 18),
        h('span', { text: 'The video could not be loaded. Use Download to open it in another player.' })));
    });

    var speeds = h('div', { class: 'seg-c rec-speed', role: 'group', 'aria-label': 'Playback speed' });
    RV.SPEEDS.forEach(function (sp) {
      var b = h('button', { type: 'button', text: sp + 'x', 'aria-pressed': String(sp === speed), class: sp === speed ? 'on' : '' });
      b.addEventListener('click', function () {
        speed = RV.speedOf(sp); vid.playbackRate = speed;
        speeds.querySelectorAll('button').forEach(function (x) { var on = x === b; x.className = on ? 'on' : ''; x.setAttribute('aria-pressed', String(on)); });
      });
      speeds.append(b);
    });
    var dl = h('button', { type: 'button', class: 'btn ghost sm', 'aria-label': 'Download the recording' }, McA.icons.get('download', 14), h('span', { text: 'Download' }));
    dl.addEventListener('click', function () { McA.util.downloadURL(src + (src.indexOf('?') === -1 ? '?' : '&') + 'download=true', ctx.part + '_solidworks_recording' + (rec.media_type === 'video/webm' ? '.webm' : '.mp4')); });

    var node = h('div', { class: 'rec-wrap' }, vid,
      h('div', { class: 'rec-bar' }, speeds, h('span', { class: 'rec-facts mono', text: RV.facts(rec) }), dl),
      chapters.length ? h('div', null, h('h3', { class: 'sub-h', text: 'Jump to a feature' }), list) : h('p', { class: 'rsec-note hint', text: 'No feature markers were recorded.' }));
    kept = { key: key, node: node };
    return node;
  }

  /** Results section renderer: (body, tools, d). */
  function renderPanel(body, tools, d) {
    var rec = ((d.payload && d.payload.categories) || {}).recording || null, info = RV.describe(rec), ctx = d.ctx;
    body.append(h('div', { class: 'banner rec-state is-' + tone(info.tone), role: 'status', 'data-state': info.kind },
      McA.icons.get(info.tone === 'err' ? 'warn' : 'info', 18),
      h('span', null, h('b', { text: info.title }), info.detail ? ' ' + info.detail : '')));
    if (!info.playable) { kept = { key: '', node: null }; return; }
    if (!ctx || ctx.kind !== 'part') { body.append(h('p', { class: 'rsec-note hint', text: 'Recordings are saved with a part. Open the part to play it.' })); return; }
    body.append(player(ctx, rec, d));
  }

  /** Run-options checkbox: enabled only when recording can work here. cap: capability payload or null. */
  function applyCheckbox(cap, ctx) {
    var box = document.getElementById('record-run'), hint = document.getElementById('record-hint');
    if (!box) return;
    var st = RV.checkbox(cap, ctx);
    box.disabled = st.disabled;
    if (st.disabled && !(cap && cap.available)) box.checked = false;       // never leave a ticked box that cannot record
    if (hint) hint.textContent = st.hint;
  }

  McA.recording = { renderPanel: renderPanel, applyCheckbox: applyCheckbox };
})();
