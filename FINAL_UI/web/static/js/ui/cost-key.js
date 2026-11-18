/* Top key-bar "Part cost" chip. Pure presentation of McA.selectors.costKey: live telemetry while a run
   is active, the pipeline ledger otherwise. Holds no prices; an unpriced part says so, it is never $0.00. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var chip, val;

  function render() {
    if (!chip) return;
    var k = McA.selectors.costKey(McA.store.get());
    /* the chip shows only the figures; the label "Part cost" is its caption */
    var shown = k.text.replace(/^Part cost\s*/, '');
    if (shown === 'unavailable') shown = 'Unavailable';
    val.textContent = shown;
    chip.setAttribute('data-state', k.state);
    chip.setAttribute('data-status', k.status);
    chip.setAttribute('data-source', k.source || 'none');
    chip.setAttribute('aria-label', k.text + '. ' + k.title);
    chip.title = k.title;
  }

  McA.costKey = {
    init: function () {
      chip = document.getElementById('hdr-cost'); val = document.getElementById('hdr-cost-v');
      if (!chip || !val) return;
      chip.setAttribute('tabindex', '0'); chip.setAttribute('role', 'group');
      ['run', 'outputs', 'parts'].forEach(function (k) { McA.store.subscribe(function (s) { return s[k]; }, render); });
      render();
    },
    render: render
  };
})();
