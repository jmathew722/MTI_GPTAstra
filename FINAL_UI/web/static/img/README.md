# Logo asset

`solidflow-logo.svg` is the Solid Flow logo: an original design (drawing -> arrow ->
machined part -> wordmark), built directly in this app's own palette (design-tokens.css:
violet #9B8AFB, gold #D6AF6B, ink #F2F2F4) and font stack (Segoe UI). It is a plain-text
SVG, so it is crisp at any size with no raster artifacts and no build step.

Served at `/static/img/solidflow-logo.svg`, referenced from `web/index.html`'s
`.home-logo`. The `onerror` fallback there (`#home-logo-fallback`, a plain text
"SolidFlow" wordmark) only fires if this file is ever missing or fails to load.

To use a different mark instead, replace this file (or point the `<img src>` at a new
one) -- no other code needs to change.
