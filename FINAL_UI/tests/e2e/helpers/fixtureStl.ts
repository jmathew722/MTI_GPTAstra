/** Hand-made synthetic test mesh (base plate with rounded ends, boss, two ribs). Not CAD output; used only for viewer verification. */
type V = [number, number, number];
export function bracketStl(): string {
  const tris: V[][] = [];
  const tri = (a: V, b: V, c: V) => tris.push([a, b, c]);
  const quad = (a: V, b: V, c: V, d: V) => { tri(a, b, c); tri(a, c, d); };
  const cyl = (cx: number, cz: number, r: number, y0: number, y1: number, n = 48, cap = true) => {
    for (let i = 0; i < n; i++) {
      const t0 = (i / n) * 2 * Math.PI, t1 = ((i + 1) / n) * 2 * Math.PI;
      const p0: V = [cx + r * Math.cos(t0), y0, cz + r * Math.sin(t0)], p1: V = [cx + r * Math.cos(t1), y0, cz + r * Math.sin(t1)];
      const q0: V = [p0[0], y1, p0[2]], q1: V = [p1[0], y1, p1[2]];
      quad(p0, q0, q1, p1);
      if (cap) { tri([cx, y1, cz], q1, q0); tri([cx, y0, cz], p0, p1); }
    }
  };
  const box = (x0: number, x1: number, y0: number, y1: number, z0: number, z1: number) => {
    const p = (x: number, y: number, z: number): V => [x, y, z];
    quad(p(x0, y0, z0), p(x1, y0, z0), p(x1, y1, z0), p(x0, y1, z0)); quad(p(x1, y0, z1), p(x0, y0, z1), p(x0, y1, z1), p(x1, y1, z1));
    quad(p(x0, y0, z1), p(x0, y0, z0), p(x0, y1, z0), p(x0, y1, z1)); quad(p(x1, y0, z0), p(x1, y0, z1), p(x1, y1, z1), p(x1, y1, z0));
    quad(p(x0, y1, z0), p(x1, y1, z0), p(x1, y1, z1), p(x0, y1, z1)); quad(p(x0, y0, z1), p(x1, y0, z1), p(x1, y0, z0), p(x0, y0, z0));
  };
  box(-50, 50, 0, 12, -22, 22);       // plate
  cyl(-50, 0, 22, 0, 12); cyl(50, 0, 22, 0, 12);   // rounded ends
  cyl(0, 0, 18, 12, 40);              // boss
  box(-30, 30, 12, 26, -4, 4);        // rib
  const out = ['solid fixture'];
  for (const t of tris) {
    out.push('facet normal 0 0 0', ' outer loop');
    for (const v of t) out.push(`  vertex ${v[0]} ${v[1]} ${v[2]}`);
    out.push(' endloop', 'endfacet');
  }
  out.push('endsolid fixture');
  return out.join('\n');
}
