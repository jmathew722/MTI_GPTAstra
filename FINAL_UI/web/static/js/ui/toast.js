/* McA.toast.show(text, kind) - kind: info | ok | warn | err. Mirrors into the live regions. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var h = function () { return McA.dom.h.apply(null, arguments); };
  function announce(text, kind) {
    var live = document.getElementById(kind === 'err' ? 'alert-live' : 'status-live');
    if (!live) return;
    live.textContent = '';
    setTimeout(function () { live.textContent = text; }, 30);
  }
  McA.toast = {
    show: function (text, kind, opts) {
      kind = kind || 'info';
      var root = document.getElementById('toast-root');
      if (!root) return null;
      var icon = { ok: 'check', warn: 'warn', err: 'x', info: 'info' }[kind] || 'info';
      var close = h('button', { class: 'ibtn toast-x', type: 'button', 'aria-label': 'Dismiss notification' });
      close.append(McA.icons.get('x', 14));
      var t = h('div', { class: 'toast is-' + kind }, h('span', { class: 'toast-ic' }, McA.icons.get(icon, 16)), h('span', { class: 'toast-t', text: text }), close);
      var timer;
      function remove() { clearTimeout(timer); t.classList.add('is-leaving'); setTimeout(function () { t.remove(); }, 180); }
      close.addEventListener('click', remove);
      root.append(t);
      announce(text, kind);
      var ms = (opts && opts.ms) || (kind === 'err' ? 9000 : 5000);
      timer = setTimeout(remove, ms);
      return { dismiss: remove };
    },
    announce: announce,
  };
})();
