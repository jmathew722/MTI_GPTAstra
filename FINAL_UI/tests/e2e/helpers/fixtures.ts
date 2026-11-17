import { PNG } from 'pngjs';

/** A synthetic "drawing": white sheet, black rectangle outline, a few circles. No customer data. */
export function drawingPng(w = 640, h = 480, seed = 1): Buffer {
  const png = new PNG({ width: w, height: h });
  png.data.fill(255);
  const set = (x: number, y: number) => {
    if (x < 0 || y < 0 || x >= w || y >= h) return;
    const i = (y * w + x) * 4;
    png.data[i] = 20; png.data[i + 1] = 20; png.data[i + 2] = 20; png.data[i + 3] = 255;
  };
  for (let x = 60; x < w - 60; x++) { set(x, 60); set(x, 61); set(x, h - 60); set(x, h - 61); }
  for (let y = 60; y < h - 60; y++) { set(60, y); set(61, y); set(w - 60, y); set(w - 61, y); }
  for (let k = 0; k < 3; k++) {
    const cx = 160 + k * 150 + seed * 3, cy = h / 2, r = 30;
    for (let a = 0; a < 720; a++) { const t = (a * Math.PI) / 360; set(Math.round(cx + r * Math.cos(t)), Math.round(cy + r * Math.sin(t))); }
  }
  return PNG.sync.write(png);
}

export function pngFile(name: string, seed = 1, rel?: string) {
  return { name, mimeType: 'image/png', buffer: drawingPng(640, 480, seed) };
}
