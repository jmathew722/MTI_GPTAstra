# Logo asset

Drop the approved Solid Flow logo here as:

    solidflow-logo.png

The Home page (`web/index.html`, `.home-logo`) already references this exact path and falls
back to a plain text "SolidFlow" wordmark when the file is absent (`onerror` handler), so
nothing breaks either way. No resizing/recreating is done to the file you drop in here --
it is served as-is via `/static/img/solidflow-logo.png`.
