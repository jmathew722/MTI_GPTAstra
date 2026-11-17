import * as fs from 'fs';
import * as path from 'path';
import { WEBAPP, SNAP } from './global-setup';

// Remove every session folder and demo-run folder created while the tests ran,
// so the repo is left exactly as it was found.
export default async function globalTeardown() {
  if (!fs.existsSync(SNAP)) return;
  const snap = JSON.parse(fs.readFileSync(SNAP, 'utf8')) as { parts: string[]; runs: string[] };
  for (const [sub, keep] of [['parts', snap.parts], ['runs', snap.runs]] as const) {
    const dir = path.join(WEBAPP, sub);
    if (!fs.existsSync(dir)) continue;
    for (const name of fs.readdirSync(dir)) {
      if (!keep.includes(name)) fs.rmSync(path.join(dir, name), { recursive: true, force: true });
    }
  }
  fs.rmSync(SNAP, { force: true });
}
