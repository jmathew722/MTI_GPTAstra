v8 test fixtures (labelled, never presented as real drawings).

multipage: ``ring_2page.pdf`` = the ring drawing's page twice (byte-identical page content), so page 2's extraction IS the page-1 extraction. The cache entry is
seeded from the real, paid ring extraction with ZERO new model calls. It exercises sheet order / count / per-sheet size, scale, geometry, notes and per-page
verification. It does not test that a *different* second page reads correctly (that needs a real multi-page drawing and a paid read per page).
