import * as fs from 'fs';
import * as path from 'path';

export const WEBAPP = path.resolve(__dirname, '../../pipeline_app/webapp');
export const SNAP = path.resolve(__dirname, '../.snapshot.json');

function ls(dir: string): string[] {
  try { return fs.readdirSync(dir); } catch { return []; }
}

export default async function globalSetup() {
  const snap = { parts: ls(path.join(WEBAPP, 'parts')), runs: ls(path.join(WEBAPP, 'runs')) };
  fs.writeFileSync(SNAP, JSON.stringify(snap));
}
