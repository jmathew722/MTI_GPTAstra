import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import { APIRequestContext } from '@playwright/test';
import { bracketStl } from './fixtureStl';
import { pngFile } from './fixtures';

/** Where the server under test writes part outputs. The suite never writes into the real FINAL_OUTPUTs: start the server with
 *  MCAGENT_FINAL_OUTPUTS pointing at a temp folder and export the same variable for the tests. */
export const FINAL = process.env.MCAGENT_FINAL_OUTPUTS ? path.resolve(process.env.MCAGENT_FINAL_OUTPUTS) : '';
export const uniq = (p: string) => `${p}${Date.now().toString(36)}${Math.floor(Math.random() * 1e3)}`;

export type Kind = 'verified' | 'notspec' | 'legacy' | 'ambiguous' | 'unpriced';

const DEMO_SNAP = { catalog_id: 'solidflow-demo', source: 'demo', path: 'solidflow-demo.json', sha256: '', currency: 'USD', price_basis: 'synthetic_demo_usd_per_kg', entries: 3, rejected: 0, files: [] as string[] };

/** Creates a saved part through the real API, then writes the material files the pipeline would have written. */
export async function seedMaterialPart(request: APIRequestContext, name: string, kind: Kind, session?: string, demoSha = ''): Promise<string> {
  if (!FINAL) throw new Error('MCAGENT_FINAL_OUTPUTS must be set (same value as the server) so fixtures never touch the real outputs.');
  const sid = session || (await (await request.post('/api/session')).json()).session as string;
  const png = pngFile('drawing.png', 2);
  const up = await request.post('/api/parts', { multipart: { session: sid, part: name, source: png, original: { name: 'drawing.png', mimeType: 'image/png', buffer: png.buffer } } });
  if (!up.ok()) throw new Error('part upload failed: ' + (await up.text()));
  const out = path.join(FINAL, name);
  fs.mkdirSync(out, { recursive: true });
  const w = (f: string, o: unknown) => fs.writeFileSync(path.join(out, f), JSON.stringify(o, null, 2));
  if (kind === 'legacy') {                                 // built before the upgrade: an extraction and a STL, no material files
    fs.writeFileSync(path.join(out, `${name}_ir.STL`), bracketStl());
    w(`${name}_extraction.json`, { material: 'Steel', features: [] });
    return sid;
  }
  const snap = Object.assign({}, DEMO_SNAP, { sha256: demoSha });
  const stl = bracketStl();
  fs.writeFileSync(path.join(out, `${name}_ir.STL`), stl);
  fs.writeFileSync(path.join(out, `${name}_ir.SLDPRT`), 'x');
  const sha = crypto.createHash('sha256').update(fs.readFileSync(path.join(out, `${name}_ir.STL`))).digest('hex');
  const ev = [{ page: 1, region: 'title_block', quote: 'MATERIAL: STEEL' }];
  const base = (status: string, extra: any) => Object.assign({ status, label: 'Generic carbon steel', selection_source: 'drawing', review_required: false, review_reasons: [], suggestions: [], standard_candidates: [], override: null, catalogs: [snap],
    drawing: { status: 'specified', raw_text: 'STEEL', normalized_candidate: 'steel', evidence: ev, confidence: 0.95, alternatives: [] },
    chosen: { material_id: 'demo-steel', label: 'Generic carbon steel', catalog_id: 'solidflow-demo', catalog_source: 'demo', catalog_sha256: demoSha, density_kg_m3: 7850, price_per_kg: 1.5, currency: 'USD', price_basis: 'synthetic_demo_usd_per_kg', sw_material_name: 'Generic carbon steel', appearance: { color: '#A5ABB4', metalness: 0.8, roughness: 0.35 } } }, extra);
  if (kind === 'verified' || kind === 'unpriced') {
    w('material_resolution.json', base('assigned_verified', {}));
    w('material_native.json', { status: 'assigned_verified', requested: { name: 'Generic carbon steel', database: 'C:\\hidden\\server\\path\\solidflow-demo.sldmat' }, actual: { name: 'Generic carbon steel', database: 'C:\\hidden\\server\\path\\solidflow-demo.sldmat' }, density_kg_m3: 7850, density_ok: true, mass: { volume_m3: 0.000084, mass_kg: 0.6594 }, errors: [], config: 'Default' });
    if (kind === 'verified') w('material_costing.json', { available: true, reason: null, mass_kg: 0.6594, net_material_cost: 0.9891, stock_cost: null, currency: 'USD', label: 'Illustrative material estimate \u2014 not a supplier quote', display: { mass: '0.6594 kg', volume: '84 cm\u00b3', net_material_cost: '0.99 USD' }, inputs: { price_per_kg: 1.5 }, warnings: [], excludes: 'Material only: excludes machining, labour, scrap/waste (unless a yield is set), shipping, tax and purchase minimums.' });
    else w('material_costing.json', { available: false, reason: 'The catalog has no price for this material, so the cost is unavailable (not $0).', mass_kg: 0.6594, net_material_cost: null, currency: 'USD', label: 'Material estimate from the catalog price', display: { mass: '0.6594 kg' }, inputs: {}, warnings: [], excludes: 'Material only.' });
    w('appearance.json', { schema_version: 1, artifact: `${name}_ir.STL`, artifact_sha256: sha, job_id: 'j1', verified: true, material_id: 'demo-steel', material_label: 'Generic carbon steel', status: 'assigned_verified', color: '#A5ABB4', metalness: 0.8, roughness: 0.35, source: 'catalog', caption: 'Illustrative appearance, not a finish specification.' });
  } else if (kind === 'notspec') {
    w('material_resolution.json', { status: 'not_specified', label: 'No material specified on drawing', selection_source: null, chosen: null, review_required: false, review_reasons: [], suggestions: [], standard_candidates: [], override: null, catalogs: [snap],
      drawing: { status: 'not_specified', raw_text: '', normalized_candidate: '', evidence: [], alternatives: [] } });
    w('material_native.json', { status: 'not_specified', note: 'No native material step ran.' });
    w('material_costing.json', { available: false, reason: 'No material is verified on the native part, so the cost is unavailable.', net_material_cost: null, currency: 'USD', label: 'Material estimate from the catalog price', display: {}, inputs: {}, warnings: [], excludes: 'Material only.' });
    w('appearance.json', { schema_version: 1, artifact: `${name}_ir.STL`, artifact_sha256: sha, verified: false, material_id: null, status: 'not_specified', color: '#9AA0A8', metalness: 0.2, roughness: 0.6, source: 'neutral', caption: 'Preview only: the material is not verified on the native part, so the model is shown in neutral grey.' });
  } else {
    w('material_resolution.json', base('ambiguous', { chosen: null, label: 'Steel or aluminium', review_required: true, review_reasons: ['The drawing names more than one material; no single material is applied over it.'],
      suggestions: [{ id: 'demo-steel', label: 'Generic carbon steel', catalog_id: 'solidflow-demo', source: 'demo', similarity: 0.7, different_grade: false, different_temper_or_condition: false, auto_assignable: false }],
      drawing: { status: 'ambiguous', raw_text: 'STEEL / ALUMINIUM', normalized_candidate: 'steel', evidence: [{ page: 1, region: 'notes', quote: 'STEEL / ALUMINIUM' }], alternatives: ['aluminium'] } }));
    w('material_native.json', { status: 'ambiguous', note: 'No native material step ran.' });
    w('appearance.json', { schema_version: 1, artifact: `${name}_ir.STL`, artifact_sha256: sha, verified: false, material_id: null, status: 'ambiguous', color: '#9AA0A8', metalness: 0.2, roughness: 0.6, source: 'neutral', caption: 'Preview only.' });
  }
  return sid;
}

/** Replace the STL after the sidecar was written, so the sidecar's hash no longer matches (simulates a re-run). */
export function replaceStl(name: string) {
  const f = path.join(FINAL, name, `${name}_ir.STL`);
  fs.writeFileSync(f, bracketStl().replace('solid fixture', 'solid changed') + '\n');
}

export function writeLibrary(dir: string, ids = ['co-6061', 'co-304']) {
  fs.mkdirSync(dir, { recursive: true });
  const mats = ids.map((id, i) => ({ id, label: id === 'co-6061' ? '6061-T6 Aluminium' : 'Stainless 304', aliases: [id], density_kg_m3: 2700 + i * 5300, price_per_kg: 4 + i }));
  mats.push({ id: 'co-bad', label: 'Bad density', aliases: [], density_kg_m3: -5, price_per_kg: 1 } as any);
  fs.writeFileSync(path.join(dir, 'materials.json'), JSON.stringify({ schema_version: 1, catalog_id: 'co', label: 'Acme library', currency: 'USD', price_basis: 'quote_2026', materials: mats }));
  return dir;
}
