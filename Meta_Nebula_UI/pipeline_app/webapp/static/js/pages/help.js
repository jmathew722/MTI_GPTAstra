/* Help: static documentation (workflow, formats, shortcuts, tracker legend, exit codes, outputs). */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  McA.pages = McA.pages || {};
  var HTML = '' +
    '<section aria-labelledby="h-flow"><h2 id="h-flow">Workflow</h2><ol>' +
    '<li>Add a drawing on Home (PDF, image or CAD file). Nothing is run yet.</li>' +
    '<li>In the Workspace, name the part, assign view types in Part Setup, and save the part.</li>' +
    '<li>Press Run Pipeline. It extracts the geometry, resolves conflicts, builds the plan, generates the part and verifies it.</li>' +
    '<li>Review the 3D model next to the drawing, then read Pipeline Results: flags, verification and cost.</li></ol>' +
    '<p>Run Pipeline makes paid API calls. Run Demo uses a saved extraction and makes none.</p></section>' +
    '<section aria-labelledby="h-fmt"><h2 id="h-fmt">Supported drawing formats</h2>' +
    '<p>PDF, JPG, PNG, WEBP, BMP, TIFF, DWG, DXF and eDrawings (EDRW, EPRT, EASM). DWG and DXF are converted on the server. eDrawings files give a static preview only. Some browsers cannot decode TIFF; use PNG or PDF if a TIFF fails to load.</p>' +
    '<p>Multi-page PDFs: the cropper shows page 1. Other pages (up to 12) are available through Upload drawing.</p></section>' +
    '<section aria-labelledby="h-trk"><h2 id="h-trk">Pipeline tracker</h2><p>Five stages: Extraction, Resolution, Build Plan, Generation, Verification. Progress comes from the pipeline log, never from a timer.</p>' +
    '<div class="legend"><span><b>Pending</b> hollow</span><span><b>Running</b> gold ring</span><span><b>Succeeded</b> green check</span><span><b>Warning</b> amber triangle</span><span><b>Failed</b> red cross</span><span><b>Skipped</b> dashed</span></div>' +
    '<p>A completed run is not a verified part. Check the Verification verdict in the Pipeline Results bar.</p></section>' +
    '<section aria-labelledby="h-keys"><h2 id="h-keys">Keyboard shortcuts</h2><dl>' +
    '<dt><kbd>Left</kbd> <kbd>Right</kbd></dt><dd>On the splitter: move 2%. With <kbd>Shift</kbd> 10%. <kbd>Home</kbd> 20%, <kbd>End</kbd> 80%, <kbd>Enter</kbd> resets to 50%.</dd>' +
    '<dt><kbd>Up</kbd> <kbd>Down</kbd></dt><dd>On the drawer resize handle: 16 px, with <kbd>Shift</kbd> 64 px. <kbd>Enter</kbd> toggles default and maximum height.</dd>' +
    '<dt><kbd>Esc</kbd></dt><dd>Closes dialogs, menus and the expanded sidebar; restores a maximized panel.</dd>' +
    '<dt><kbd>Shift</kbd>+<kbd>Esc</kbd></dt><dd>Inside the cropper: closes the cropper overlay. Plain <kbd>Esc</kbd> clears the selection.</dd>' +
    '<dt><kbd>Arrow keys</kbd></dt><dd>Move between tabs, and between options in the part switcher.</dd></dl></section>' +
    '<section aria-labelledby="h-exit"><h2 id="h-exit">Exit codes</h2><dl>' +
    '<dt>0</dt><dd>Every part is READY.</dd><dt>8</dt><dd>At least one part is NOT READY, BLOCKED or ERROR (batch part runs).</dd>' +
    '<dt>2, 3</dt><dd>Input error (bad folder or drawing).</dd><dt>4</dt><dd>BLOCKED by the validator.</dd><dt>5</dt><dd>SolidWorks connection failed.</dd>' +
    '<dt>6</dt><dd>Build failed.</dd><dt>7</dt><dd>Built-model validation failed.</dd><dt>127</dt><dd>The server could not launch the pipeline.</dd></dl></section>' +
    '<section aria-labelledby="h-out"><h2 id="h-out">Where outputs go</h2>' +
    '<p>Run output is written next to the part on the server, then delivered to <code>UI_Output/&lt;part&gt;/</code> and <code>~/Downloads/SolidWorksModel_Parts/&lt;part&gt;/</code>. The Files section of Pipeline Results lists every file with a download link.</p>' +
    '<p>A re-run replaces the previous outputs for that part.</p></section>';
  McA.pages.help = { init: function () { document.getElementById('help-body').innerHTML = HTML; /* static trusted markup */ } };
})();
