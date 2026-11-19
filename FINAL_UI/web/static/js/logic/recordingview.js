/* McA.recordingview: PURE logic for "Record Pipeline Run" (no DOM, no fetch). The pipeline records only the SolidWorks window
   during the native build; the server validates the manifest and puts a summary at payload.categories.recording.
   This file decides what the Results section says in each state, what the run-options checkbox does, and which chapter
   is playing. It never invents a recording: a state with no video says why. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).recordingview = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var SPEEDS = [1, 2, 4];

  /* What each failure code means to a person (the manifest's own reason is the fallback). */
  var CODE_TEXT = {
    REC_UNAVAILABLE: 'Recording needs Windows.',
    REC_NO_WINDOW: 'The SolidWorks window was not found, so nothing was recorded.',
    REC_ENCODER_MISSING: 'No video encoder is installed on this machine.',
    REC_CAPTURE_BLACK: 'The SolidWorks window captured as black. Keep SolidWorks open and not minimized, then run again.',
    REC_NO_FRAMES: 'No frames were captured. Keep SolidWorks visible during the build, then run again.',
    REC_COVERED: 'Some frames are missing because another window covered SolidWorks. Those frames were dropped, never recorded.',
    REC_LIMIT_REACHED: 'The recording reached its time or size limit and stopped. The build itself was not affected.',
    REC_WRITE_FAILED: 'The video file could not be written.',
    REC_NOT_REACHED: 'The run never reached the SolidWorks build, so there was nothing to record.',
    REC_INTERRUPTED: 'The run ended before the recording was finished.'
  };

  function codeText(code, fallback) { return CODE_TEXT[code] || fallback || ''; }

  function fmtDuration(sec) {
    var n = Math.max(0, Math.round(Number(sec) || 0)), m = Math.floor(n / 60), s = n % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }
  function fmtBytes(n) {
    n = Number(n) || 0;
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(0) + ' KB';
    return (n / 1048576).toFixed(1) + ' MB';
  }

  /** The Results section's state. kind: none | recording | ready | partial | failed | skipped | stale | interrupted.
      playable = there is a video to play. tone: ok | warn | err | steel. */
  function describe(rec) {
    if (!rec || !rec.present || rec.status === 'none') {
      return { kind: 'none', tone: 'steel', playable: false, title: 'Not recorded',
               detail: 'Tick "Record pipeline run" in Run options before running to record the SolidWorks build.' };
    }
    var st = rec.status, why = codeText(rec.code, rec.reason);
    if (st === 'recording') {
      return { kind: 'recording', tone: 'steel', playable: false, title: 'Recording the SolidWorks build',
               detail: 'The video appears here when the SolidWorks stage finishes.' };
    }
    if (st === 'stale') {
      return { kind: 'stale', tone: 'warn', playable: false, title: 'Recording is from a different drawing',
               detail: 'This drawing changed after the recording was made, so the old video is not shown. Run the part again with recording on.' };
    }
    if (st === 'interrupted') {
      return { kind: 'interrupted', tone: 'warn', playable: false, title: 'Recording was interrupted', detail: why };
    }
    if (st === 'skipped') {
      return { kind: 'skipped', tone: 'steel', playable: false, title: 'Nothing to record', detail: why || codeText('REC_NOT_REACHED') };
    }
    if (st === 'failed' || !rec.has_video) {
      return { kind: 'failed', tone: 'err', playable: false, title: 'Recording failed', detail: why || 'No video was produced.' };
    }
    if (st === 'partial') {
      return { kind: 'partial', tone: 'warn', playable: true, title: 'Recorded, with gaps', detail: why };
    }
    return { kind: 'ready', tone: 'ok', playable: true, title: 'Recorded', detail: '' };
  }

  /** One line of facts under the player: "0:33 · 1520×856 · 1.0 MB · 5 features". */
  function facts(rec) {
    if (!rec) return '';
    var out = [];
    if (rec.duration_s) out.push(fmtDuration(rec.duration_s));
    if (rec.width && rec.height) out.push(rec.width + '×' + rec.height);
    if (rec.bytes) out.push(fmtBytes(rec.bytes));
    var n = (rec.chapters || []).length;
    if (n) out.push(n + ' feature' + (n === 1 ? '' : 's'));
    if (rec.dropped_frames) out.push(rec.dropped_frames + ' dropped');
    return out.join(' · ');
  }

  /** Index of the chapter playing at time t (the last one that started at or before t), or -1 before the first. */
  function chapterAt(chapters, t) {
    var idx = -1;
    for (var i = 0; i < (chapters || []).length; i++) {
      if (typeof chapters[i].t === 'number' && chapters[i].t <= t + 0.05) idx = i;
    }
    return idx;
  }

  /** Seek target for a chapter: a hair before it starts, never negative, never past the end. */
  function seekTime(chapter, duration) {
    var t = Math.max(0, (chapter && typeof chapter.t === 'number' ? chapter.t : 0) - 0.3);
    return duration > 0 ? Math.min(t, Math.max(0, duration - 0.1)) : t;
  }

  /** Playback speed selection: only the offered speeds; anything else falls back to 1x. */
  function speedOf(v) { v = Number(v); return SPEEDS.indexOf(v) === -1 ? 1 : v; }

  /** The run-options checkbox. cap: GET /api/recording/capability or null (not loaded yet).
      ctx: {reachable, running}. Returns {disabled, reason, hint}. */
  function checkbox(cap, ctx) {
    ctx = ctx || {};
    var base = 'Records only the SolidWorks window during the build and saves it to this part’s results. Keep SolidWorks visible.';
    if (!ctx.reachable) return { disabled: true, reason: 'Server unreachable.', hint: 'Not available: the server is unreachable.' };
    if (!cap) return { disabled: true, reason: 'Checking whether recording is available.', hint: 'Checking whether recording is available.' };
    if (!cap.available) {
      var r = cap.reason || 'Recording is not available on this machine.';
      return { disabled: true, reason: r, hint: 'Not available: ' + r };
    }
    return { disabled: !!ctx.running, reason: ctx.running ? 'A run is in progress.' : '', hint: base };
  }

  /** Whether the run request should carry record=true: the box is ticked AND recording is available here. (A batch keeps the
      box ticked but locked while it runs, so "a run is in progress" must not switch recording off for later parts.) */
  function shouldRecord(checked, cap) { return !!checked && !!cap && !!cap.available; }

  return { SPEEDS: SPEEDS, CODE_TEXT: CODE_TEXT, codeText: codeText, fmtDuration: fmtDuration, fmtBytes: fmtBytes,
           describe: describe, facts: facts, chapterAt: chapterAt, seekTime: seekTime, speedOf: speedOf,
           checkbox: checkbox, shouldRecord: shouldRecord };
});
