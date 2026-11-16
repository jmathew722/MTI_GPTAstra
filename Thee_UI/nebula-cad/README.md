# 2D to 3D CAD

Front end for the MTI 2D drawing to SolidWorks part pipeline. See `../docs/` for architecture, design spec, API contract and QA checklist.

## Run

```bash
cd Thee_UI/nebula-cad
npm install
npm run dev            # http://localhost:3000  (sample-data mode)
npm run build && npm run start
npm run typecheck && npm run lint
npm test               # Vitest: cost, rubric (hard-fail cap), gating, seed schema
npm run e2e            # Playwright + axe on every route, loud-failure flow (builds and starts the app)
npm run shots          # screenshots at 1440x900, 1024x768, 390x844 into ../docs/screenshots (app must be running)
npm run gen:samples    # regenerate the synthetic sample drawings (PDF) and models (STL)
```

First time only: `npx playwright install chromium`.

## Connect the real pipeline

Create `.env.local` (never committed):

```
NEXT_PUBLIC_API_MODE=http
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8092/api
```

The service must implement `../docs/API_CONTRACT.md`. Every response is validated against the Zod schemas in `lib/schemas`.
