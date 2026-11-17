/* Sidebar: collapse (64/240, persisted at >=1440), overlay between 800 and 1439, off-canvas below 800. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var overlayOpen = false, menuOpen = false;
  var mqWide, mqMobile, sb, toggle, menuBtn, scrim;

  function ui() { return (McA.store.get().ui) || {}; }
  function apply() {
    var wide = mqWide.matches, mobile = mqMobile.matches;
    var rail = wide ? !!ui().sidebarCollapsed : true;
    if (wide || mobile) overlayOpen = false;
    if (!mobile) menuOpen = false;
    var overlay = !wide && !mobile && overlayOpen;
    var expanded = mobile ? menuOpen : (!rail || overlay);
    var b = document.body;
    b.setAttribute('data-sb', rail ? 'rail' : 'expanded');
    if (overlay) b.setAttribute('data-sb-overlay', 'true'); else b.removeAttribute('data-sb-overlay');
    if (menuOpen) b.setAttribute('data-sb-menu', 'open'); else b.removeAttribute('data-sb-menu');
    sb.classList.toggle('is-collapsed', !expanded);
    toggle.setAttribute('aria-expanded', String(expanded));
    toggle.setAttribute('aria-label', expanded ? 'Collapse sidebar' : 'Expand sidebar');
    menuBtn.setAttribute('aria-expanded', String(menuOpen));
    scrim.hidden = !(overlay || menuOpen);
    if (mobile) { sb.inert = !menuOpen; } else { sb.inert = false; }
  }
  function closeTransient() { if (overlayOpen || menuOpen) { overlayOpen = false; menuOpen = false; apply(); return true; } return false; }

  function newProject() {
    var s = McA.store.get();
    var has = s.intake && s.intake.items && s.intake.items.length > 0;
    var go = function () {
      McA.dom.dispatch('intake/reset');
      McA.dom.dispatch('parts/select', null);
      McA.router.go('home');
    };
    closeTransient();
    if (!has) { go(); return; }
    McA.dialog.confirm('Start a new project?', 'The drawing and views you have not saved will be discarded. A running pipeline is not affected.', 'Discard draft', true).then(function (ok) { if (ok) go(); });
  }

  McA.sidebar = {
    init: function () {
      sb = document.getElementById('sidebar'); toggle = document.getElementById('sb-toggle');
      menuBtn = document.getElementById('sb-menu'); scrim = document.getElementById('sb-scrim');
      mqWide = window.matchMedia('(min-width: 1440px)'); mqMobile = window.matchMedia('(max-width: 799.98px)');
      toggle.addEventListener('click', function () {
        if (mqMobile.matches) { menuOpen = false; apply(); menuBtn.focus(); }
        else if (mqWide.matches) McA.dom.setUi({ sidebarCollapsed: !ui().sidebarCollapsed });
        else { overlayOpen = !overlayOpen; apply(); }
      });
      menuBtn.addEventListener('click', function () { menuOpen = !menuOpen; apply(); if (menuOpen) toggle.focus(); });
      scrim.addEventListener('click', closeTransient);
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !McA.dialog.isOpen() && closeTransient()) { e.preventDefault(); (mqMobile.matches ? menuBtn : toggle).focus(); }
      });
      sb.addEventListener('click', function (e) { if (e.target.closest('a.sb-item') && !mqWide.matches) closeTransient(); });
      document.getElementById('sb-new').addEventListener('click', newProject);
      [mqWide, mqMobile].forEach(function (m) { m.addEventListener('change', apply); });
      McA.store.subscribe(function (s) { return s.ui && s.ui.sidebarCollapsed; }, apply);
      McA.store.subscribe(function (s) { var r = s.run && s.run.state; return r === 'running' || r === 'queued'; }, function (on) {
        var dot = sb.querySelector('.sb-run'); var item = dot.parentNode;
        dot.hidden = !on; item.classList.toggle('is-running', on);
        dot.setAttribute('aria-hidden', 'true');
        var lbl = item.querySelector('.sb-label'); lbl.setAttribute('data-running', on ? 'true' : 'false');
        item.setAttribute('aria-label', on ? 'Workspace, pipeline running' : 'Workspace');
      });
      apply();
    },
    reset: function () { McA.dom.setUi({ sidebarCollapsed: false }); },
  };
})();
