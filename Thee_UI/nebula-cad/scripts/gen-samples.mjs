// Generates the synthetic sample assets. No customer data is involved.
//   public/samples/<key>.pdf   a 2D drawing (vector PDF written by hand, no dependency)
//   public/samples/<key>.stl   the "generated model" (binary STL via three.js)
//   lib/data/generated/<key>.json   callout regions, drawing registration, mesh stats
// Run: npm run gen:samples
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as THREE from "three";
import { STLExporter } from "three/examples/jsm/exporters/STLExporter.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const specs = JSON.parse(fs.readFileSync(path.join(root, "lib/data/part-specs.json"), "utf8"));
const outPublic = path.join(root, "public/samples");
const outData = path.join(root, "lib/data/generated");
fs.mkdirSync(outPublic, { recursive: true });
fs.mkdirSync(outData, { recursive: true });

export function holePositions(h) {
  if (h.pattern === "circle") {
    return Array.from({ length: h.count }, (_, i) => {
      const a = Math.PI / 2 + (i * 2 * Math.PI) / h.count;
      return [(h.bc / 2) * Math.cos(a), (h.bc / 2) * Math.sin(a)];
    });
  }
  const x = h.px / 2;
  const y = h.py / 2;
  return [
    [-x, -y],
    [x, -y],
    [x, y],
    [-x, y],
  ];
}

// ---------------------------------------------------------------- STL
function buildStl(spec) {
  const shape = new THREE.Shape();
  if (spec.outline.kind === "circle") {
    shape.absarc(0, 0, spec.outline.diameter / 2, 0, Math.PI * 2, false);
  } else {
    const w = spec.outline.width / 2;
    const h = spec.outline.height / 2;
    shape.moveTo(-w, -h);
    shape.lineTo(w, -h);
    shape.lineTo(w, h);
    shape.lineTo(-w, h);
    shape.closePath();
  }
  const addHole = (x, y, d) => {
    const p = new THREE.Path();
    p.absarc(x, y, d / 2, 0, Math.PI * 2, true);
    shape.holes.push(p);
  };
  addHole(0, 0, spec.bore);
  for (const [x, y] of holePositions(spec.modelHoles)) addHole(x, y, spec.modelHoles.diameter);
  const geo = new THREE.ExtrudeGeometry(shape, { depth: spec.thickness, bevelEnabled: false, curveSegments: 40 });
  geo.translate(0, 0, -spec.thickness / 2);
  const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial());
  const data = new STLExporter().parse(mesh, { binary: true });
  return { buffer: Buffer.from(data.buffer), triangles: geo.index ? geo.index.count / 3 : geo.attributes.position.count / 3 };
}

function volumeCm3(spec, holes) {
  const area =
    spec.outline.kind === "circle"
      ? Math.PI * (spec.outline.diameter / 2) ** 2
      : spec.outline.width * spec.outline.height;
  const cut = Math.PI * (spec.bore / 2) ** 2 + holes.count * Math.PI * (holes.diameter / 2) ** 2;
  return ((area - cut) * spec.thickness) / 1000;
}

// ---------------------------------------------------------------- PDF
const W = 1190.55;
const H = 841.89;
const K = 0.5522847498;

function makePdf(spec) {
  const ops = [];
  const regions = {};
  const n = (v) => Number(v.toFixed(2));
  const esc = (s) => s.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
  const stroke = (w, dash = "[] 0 d") => ops.push(`${w} w ${dash}`);
  const line = (x1, y1, x2, y2) => ops.push(`${n(x1)} ${n(y1)} m ${n(x2)} ${n(y2)} l S`);
  const rect = (x, y, w, h) => ops.push(`${n(x)} ${n(y)} ${n(w)} ${n(h)} re S`);
  const circle = (cx, cy, r) => {
    const k = r * K;
    ops.push(
      `${n(cx + r)} ${n(cy)} m ${n(cx + r)} ${n(cy + k)} ${n(cx + k)} ${n(cy + r)} ${n(cx)} ${n(cy + r)} c ` +
        `${n(cx - k)} ${n(cy + r)} ${n(cx - r)} ${n(cy + k)} ${n(cx - r)} ${n(cy)} c ` +
        `${n(cx - r)} ${n(cy - k)} ${n(cx - k)} ${n(cy - r)} ${n(cx)} ${n(cy - r)} c ` +
        `${n(cx + k)} ${n(cy - r)} ${n(cx + r)} ${n(cy - k)} ${n(cx + r)} ${n(cy)} c S`,
    );
  };
  const textW = (s, size) => s.length * size * 0.56;
  /** Draws text; when `key` is given, records its box as a normalized region (top-left origin). */
  const text = (x, y, s, size = 11, bold = false, key = null, extraLines = 0) => {
    ops.push(`BT /${bold ? "F2" : "F1"} ${size} Tf ${n(x)} ${n(y)} Td (${esc(s)}) Tj ET`);
    if (key) {
      const pad = 5;
      const w = textW(s, size) + pad * 2;
      const h = size * (1 + extraLines * 1.25) + pad * 2;
      const top = y + size + pad - 2;
      const prev = regions[key];
      const box = { page: 1, x: (x - pad) / W, y: 1 - top / H, w: w / W, h: h / H };
      if (prev) {
        const x0 = Math.min(prev.x, box.x);
        const y0 = Math.min(prev.y, box.y);
        const x1 = Math.max(prev.x + prev.w, box.x + box.w);
        const y1 = Math.max(prev.y + prev.h, box.y + box.h);
        regions[key] = { page: 1, x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
      } else regions[key] = box;
    }
  };
  const CENTER = "[14 3 3 3] 0 d";
  const HIDDEN = "[5 3] 0 d";

  // paper
  ops.push("0.957 0.945 0.918 rg 0 0 " + n(W) + " " + n(H) + " re f 0 0 0 rg 0.08 0.08 0.1 RG");
  stroke(1.4);
  rect(22, 22, W - 44, H - 44);
  stroke(0.5);
  rect(30, 30, W - 60, H - 60);

  const s = spec.scale;
  const cx = 370;
  const cy = 480;
  const od = spec.outline.kind === "circle" ? spec.outline.diameter : null;
  const halfW = (od ?? spec.outline.width) / 2;
  const halfH = (od ?? spec.outline.height) / 2;

  // ---- front view
  stroke(1.3);
  if (od) circle(cx, cy, halfW * s);
  else rect(cx - halfW * s, cy - halfH * s, 2 * halfW * s, 2 * halfH * s);
  circle(cx, cy, (spec.bore / 2) * s);
  const dh = spec.drawingHoles;
  const pos = holePositions(dh);
  for (const [x, y] of pos) circle(cx + x * s, cy + y * s, (dh.diameter / 2) * s);
  // centerlines
  stroke(0.45, CENTER);
  line(cx - halfW * s - 18, cy, cx + halfW * s + 18, cy);
  line(cx, cy - halfH * s - 18, cx, cy + halfH * s + 18);
  if (dh.pattern === "circle") circle(cx, cy, (dh.bc / 2) * s);
  for (const [x, y] of pos) {
    const r = (dh.diameter / 2) * s + 5;
    line(cx + x * s - r, cy + y * s, cx + x * s + r, cy + y * s);
    line(cx + x * s, cy + y * s - r, cx + x * s, cy + y * s + r);
  }
  stroke(0.6);
  text(cx - 30, cy - halfH * s - 46, "FRONT VIEW", 10, true);

  // ---- callouts on the front view
  const f1 = (v) => v.toFixed(1);
  // hole callout, upper left, leader to the top-left-most hole
  const hx = 62;
  const hy = cy + halfH * s + 58;
  text(hx, hy, `${dh.count}X \xD8${f1(dh.diameter)} THRU`, 13, true, "holes");
  if (dh.pattern === "circle") text(hx, hy - 17, `EQ SP ON \xD8${f1(dh.bc)} B.C.`, 11, false, "holes");
  else text(hx, hy - 17, `ON ${f1(dh.px)} X ${f1(dh.py)} PATTERN`, 11, false, "holes");
  const target = pos.reduce((best, p) => (p[1] - p[0] > best[1] - best[0] ? p : best), pos[0]);
  line(hx + 70, hy - 24, cx + target[0] * s - 2, cy + target[1] * s + (dh.diameter / 2) * s);
  // bore callout, upper right
  const bx = cx + halfW * s + 26;
  const by = cy + halfH * s + 40;
  text(bx, by, `\xD8${f1(spec.bore)} ${spec.boreNote}`, 12, true, "bore");
  text(bx, by - 15, "THRU BORE", 10, false, "bore");
  line(bx - 4, by - 6, cx + (spec.bore / 2) * s * 0.7, cy + (spec.bore / 2) * s * 0.72);
  // outer dimension(s), below
  const dy = cy - halfH * s - 22;
  line(cx - halfW * s, cy - halfH * s - 4, cx - halfW * s, dy - 6);
  line(cx + halfW * s, cy - halfH * s - 4, cx + halfW * s, dy - 6);
  line(cx - halfW * s, dy, cx + halfW * s, dy);
  if (od) text(cx + 26, dy + 5, `\xD8${f1(od)}`, 12, true, "outer");
  else {
    text(cx + 26, dy + 5, f1(spec.outline.width), 12, true, "width");
    const dx = cx - halfW * s - 30;
    line(cx - halfW * s - 4, cy - halfH * s, dx - 6, cy - halfH * s);
    line(cx - halfW * s - 4, cy + halfH * s, dx - 6, cy + halfH * s);
    line(dx, cy - halfH * s, dx, cy + halfH * s);
    text(dx - 44, cy + 14, f1(spec.outline.height), 12, true, "height");
  }

  // ---- section view (side)
  const sx = 860;
  const t = spec.thickness * s;
  stroke(1.3);
  rect(sx - t / 2, cy - halfH * s, t, 2 * halfH * s);
  stroke(0.6, HIDDEN);
  for (const sign of [-1, 1]) line(sx - t / 2, cy + (sign * spec.bore * s) / 2, sx + t / 2, cy + (sign * spec.bore * s) / 2);
  const ys = [...new Set(pos.map((p) => Number(p[1].toFixed(3))))];
  for (const y of ys)
    for (const sign of [-1, 1])
      line(sx - t / 2, cy + y * s + (sign * dh.diameter * s) / 2, sx + t / 2, cy + y * s + (sign * dh.diameter * s) / 2);
  stroke(0.45, CENTER);
  line(sx - t / 2 - 16, cy, sx + t / 2 + 16, cy);
  stroke(0.6);
  text(sx - 26, cy - halfH * s - 46, "SIDE VIEW", 10, true);
  const ty = cy + halfH * s + 24;
  line(sx - t / 2, cy + halfH * s + 4, sx - t / 2, ty + 6);
  line(sx + t / 2, cy + halfH * s + 4, sx + t / 2, ty + 6);
  line(sx - t / 2, ty, sx + t / 2, ty);
  text(sx + t / 2 + 10, ty - 4, `${f1(spec.thickness)} \xB10.1`, 12, true, "thickness");

  // ---- notes
  const nx = 720;
  const ny = 252;
  text(nx, ny, "NOTES:", 10, true);
  text(nx, ny - 16, "1. ALL DIMENSIONS IN MILLIMETERS.", 10, false, "units_note");
  text(nx, ny - 31, "2. UNLESS OTHERWISE SPECIFIED: X.X \xB10.1  \xD8 \xB10.05", 10, false, "tolerance_note");
  text(nx, ny - 46, "3. BREAK ALL SHARP EDGES 0.2 MAX.", 10, false, "edge_note");

  // ---- title block
  const tbw = 430;
  const tbh = 112;
  const tx = W - 30 - tbw;
  const tyb = 30;
  stroke(1.1);
  rect(tx, tyb, tbw, tbh);
  stroke(0.5);
  line(tx, tyb + 74, tx + tbw, tyb + 74);
  line(tx, tyb + 37, tx + tbw, tyb + 37);
  line(tx + 250, tyb, tx + 250, tyb + 74);
  text(tx + 10, tyb + 86, spec.title, 17, true);
  text(tx + 10, tyb + 56, "PART NO.", 7);
  text(tx + 10, tyb + 42, spec.partNumber, 12, true);
  text(tx + 260, tyb + 56, "REV", 7);
  text(tx + 260, tyb + 42, spec.revision, 12, true);
  text(tx + 310, tyb + 56, "SCALE", 7);
  text(tx + 310, tyb + 42, `${spec.scale.toFixed(1)}:1`, 11, true);
  text(tx + 10, tyb + 22, "MATERIAL", 7);
  text(tx + 10, tyb + 8, spec.materialNote, 11, true, "material");
  text(tx + 260, tyb + 22, "SHEET", 7);
  text(tx + 260, tyb + 8, "1 OF 1", 11, true);
  // provenance stamp so nobody mistakes this for a customer drawing
  text(44, 44, "SYNTHETIC SAMPLE DRAWING  -  GENERATED FOR NEBULA CAD DEMO DATA  -  NOT A CUSTOMER PART", 8, true);

  const content = Buffer.from(ops.join("\n"), "latin1");
  const objs = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${W} ${H}] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
  ];
  const chunks = [Buffer.from("%PDF-1.4\n%\xE2\xE3\xCF\xD3\n", "latin1")];
  const offsets = [];
  let pos0 = chunks[0].length;
  const push = (buf) => {
    chunks.push(buf);
    pos0 += buf.length;
  };
  objs.forEach((body, i) => {
    offsets.push(pos0);
    push(Buffer.from(`${i + 1} 0 obj\n${body}\nendobj\n`, "latin1"));
  });
  offsets.push(pos0);
  push(Buffer.from(`6 0 obj\n<< /Length ${content.length} >>\nstream\n`, "latin1"));
  push(content);
  push(Buffer.from("\nendstream\nendobj\n", "latin1"));
  const xref = pos0;
  let x = `xref\n0 7\n0000000000 65535 f \n`;
  for (const o of offsets) x += `${String(o).padStart(10, "0")} 00000 n \n`;
  x += `trailer\n<< /Size 7 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  push(Buffer.from(x, "latin1"));
  return {
    buffer: Buffer.concat(chunks),
    regions,
    registration: { page: 1, originX: cx / W, originY: 1 - cy / H, scale: s / W, aspect: W / H },
  };
}

for (const [key, spec] of Object.entries(specs)) {
  const stl = buildStl(spec);
  const pdf = makePdf(spec);
  fs.writeFileSync(path.join(outPublic, `${key}.stl`), stl.buffer);
  fs.writeFileSync(path.join(outPublic, `${key}.pdf`), pdf.buffer);
  const meta = {
    key,
    regions: pdf.regions,
    registration: pdf.registration,
    stl: { triangles: stl.triangles, sizeBytes: stl.buffer.length },
    pdf: { sizeBytes: pdf.buffer.length },
    modelVolumeCm3: Number(volumeCm3(spec, spec.modelHoles).toFixed(3)),
    drawingVolumeCm3: Number(volumeCm3(spec, spec.drawingHoles).toFixed(3)),
  };
  fs.writeFileSync(path.join(outData, `${key}.json`), JSON.stringify(meta, null, 2) + "\n");
  console.log(`${key}: stl ${stl.triangles} tris, pdf ${pdf.buffer.length} bytes, volume ${meta.modelVolumeCm3} cm3`);
}
