/**
 * Groups uploaded files into parts. The pipeline's input unit is one part:
 *   - a single drawing sheet (PDF, PNG, ...), or
 *   - a folder of per-view images (front, side, top, optional full/overview), the `--views-folder` layout.
 * A chosen folder is read from webkitRelativePath: <root>/<part>/<files> makes one part per sub-folder;
 * <root>/<file> makes one part per file.
 */
export interface Part {
  key: string;
  name: string;
  files: File[];
  /** true when the part is a folder of several views */
  folder: boolean;
}

const rel = (f: File) => (f as File & { webkitRelativePath?: string }).webkitRelativePath ?? "";
const stem = (n: string) => n.replace(/\.[^.]+$/, "");

export function groupParts(files: File[]): Part[] {
  const map = new Map<string, Part>();
  for (const f of files) {
    const segs = rel(f).split("/").filter(Boolean);
    let key: string;
    let name: string;
    let folder = false;
    if (segs.length >= 3) {
      key = `dir:${segs[1]}`;
      name = segs[1];
      folder = true;
    } else {
      key = `file:${f.name}:${f.size}`;
      name = stem(f.name);
    }
    const part = map.get(key);
    if (part) part.files.push(f);
    else map.set(key, { key, name, files: [f], folder });
  }
  return [...map.values()];
}
