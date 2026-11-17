/* Inspector: accordion (any number open), docked collapse at >=1250. Moving into the drawer is drawer.js. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  /* 'corrections' removed: that accordion moved into Pipeline Results (Solid Flow brand spec). */
  var KEYS = ['setup', 'actions', 'export'];

  function render() {
    var ui = McA.store.get().ui || {};
    var open = ui.inspectorOpen || {};
    KEYS.forEach(function (k) {
      var btn = document.getElementById('acc-btn-' + k), body = document.getElementById('acc-' + k);
      var on = !!open[k];
      btn.setAttribute('aria-expanded', String(on)); body.hidden = !on;
    });
    var collapsed = !!ui.inspectorCollapsed;
    var main = document.getElementById('ws-main');
    main.setAttribute('data-insp', collapsed ? 'collapsed' : 'open');
    var wide = window.matchMedia('(min-width: 1250px)').matches;
    document.getElementById('insp-open').hidden = !(collapsed && wide);
    document.getElementById('insp-collapse').setAttribute('aria-expanded', String(!collapsed));
  }

  McA.inspector = {
    init: function () {
      document.getElementById('inspector').addEventListener('click', function (e) {
        var b = e.target.closest('.acc-btn');
        if (b) McA.dom.dispatch('ui/inspectorSection', { id: b.closest('.acc').getAttribute('data-acc') });
      });
      document.getElementById('insp-collapse').addEventListener('click', function () {
        McA.dom.setUi({ inspectorCollapsed: true });
        document.getElementById('insp-open').focus();
      });
      document.getElementById('insp-open').addEventListener('click', function () {
        McA.dom.setUi({ inspectorCollapsed: false });
        document.getElementById('insp-collapse').focus();
      });
      McA.store.subscribe(function (s) { return s.ui && s.ui.inspectorOpen; }, render);
      McA.store.subscribe(function (s) { return s.ui && s.ui.inspectorCollapsed; }, render);
      window.matchMedia('(min-width: 1250px)').addEventListener('change', render);
      /* Must-meet specs sit in a disclosure that collapses when the selected part changes. */
      var more = document.getElementById('setup-more');
      if (more) {
        McA.store.subscribe(function (s) { return s.parts.selected; }, function () { more.open = false; document.getElementById('inspector').scrollTop = 0; });
      }
      var tb = document.getElementById('trk-tools'), mq = window.matchMedia('(min-width: 1250px)');
      var tbSync = function () { tb.hidden = mq.matches; };
      tb.addEventListener('click', function () { McA.drawer.open('tools'); });
      mq.addEventListener('change', tbSync); tbSync();
      render();
    },
    openSection: function (id) { McA.dom.dispatch('ui/inspectorSection', { id: id, open: true }); },
    reset: function () {
      McA.dom.setUi({ inspectorCollapsed: false, inspectorOpen: { setup: true, actions: true, export: true } });
    },
  };
})();
