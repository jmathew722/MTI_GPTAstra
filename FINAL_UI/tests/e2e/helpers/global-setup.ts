import * as fs from 'fs';
import * as path from 'path';

export const WEBAPP = process.env.MCAGENT_DATA ? path.resolve(process.env.MCAGENT_DATA) : path.resolve(__dirname, '../../../data');
export const SNAP = path.resolve(__dirname, '../.snapshot.json');

function ls(dir: string): string[] {
  try { return fs.readdirSync(dir); } catch { return []; }
}

export default async function globalSetup() {
  const snap = { parts: ls(path.join(WEBAPP, 'parts')), runs: ls(path.join(WEBAPP, 'runs')) };
  fs.writeFileSync(SNAP, JSON.stringify(snap));
}
