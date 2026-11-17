/* McA.dialog.open({title, body, actions:[{id,label,kind}], danger, initial}) -> Promise<actionId|null>.
   Focus trap, Escape cancels (resolves null), focus returns to the opener. body: string (text) | Node. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var seq = 0;
  var FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

  function open(opts) {
    var h = McA.dom.h;
    var root = document.getElementById('dialog-root');
    var opener = document.activeElement;
    var id = 'dlg-' + (++seq);
    var actions = opts.actions || [{ id: 'ok', label: 'OK', kind: 'primary' }];
    var bodyEl = h('div', { class: 'dlg-body', id: id + '-body' });
    if (opts.body instanceof Node) bodyEl.append(opts.body);
    else if (opts.body != null) bodyEl.append(h('p', { text: String(opts.body) }));
    var foot = h('div', { class: 'dlg-foot' });
    var dlg = h('div', { class: 'dlg' + (opts.danger ? ' is-danger' : ''), role: opts.danger ? 'alertdialog' : 'dialog', 'aria-modal': 'true', 'aria-labelledby': id + '-title', 'aria-describedby': id + '-body' },
      h('h2', { class: 'dlg-title', id: id + '-title', text: opts.title || '' }), bodyEl, foot);
    var backdrop = h('div', { class: 'dlg-backdrop' }, dlg);
    var resolve;
    var p = new Promise(function (r) { resolve = r; });
    function close(val) {
      document.removeEventListener('keydown', onKey, true);
      backdrop.remove();
      if (opener && opener.focus && document.contains(opener)) opener.focus();
      resolve(val);
    }
    actions.forEach(function (a) {
      var kind = a.kind === 'danger' ? 'danger' : a.kind === 'primary' ? '' : 'secondary';
      var b = h('button', { type: 'button', class: 'btn ' + kind, text: a.label, 'data-action': a.id });
      if (a.disabled) b.disabled = true;
      b.addEventListener('click', function () { close(a.id); });
      foot.append(b);
    });
    function onKey(e) {
      if (!backdrop.isConnected) return;
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(null); return; }
      if (e.key !== 'Tab') return;
      var f = Array.prototype.filter.call(dlg.querySelectorAll(FOCUSABLE), function (n) { return n.offsetParent !== null; });
      if (!f.length) { e.preventDefault(); return; }
      var first = f[0], last = f[f.length - 1];
      if (!dlg.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
      else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
    backdrop.addEventListener('mousedown', function (e) { if (e.target === backdrop) close(null); });
    document.addEventListener('keydown', onKey, true);
    root.append(backdrop);
    var init = (opts.initial && dlg.querySelector(opts.initial)) || foot.querySelector('.btn:not(.secondary)') || foot.lastElementChild;
    if (init) init.focus();
    p.element = dlg;
    return p;
  }
  McA.dialog = {
    open: open,
    confirm: function (title, text, okLabel, danger) {
      return open({ title: title, body: text, danger: !!danger, actions: [{ id: 'cancel', label: 'Cancel' }, { id: 'ok', label: okLabel || 'Confirm', kind: danger ? 'danger' : 'primary' }] })
        .then(function (r) { return r === 'ok'; });
    },
    isOpen: function () { return !!document.querySelector('#dialog-root .dlg'); },
  };
})();
