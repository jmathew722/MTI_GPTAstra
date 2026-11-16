import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";

export const MODEL_EXTENSIONS = ["stl", "step", "stp", "iges", "igs", "brep"] as const;
export const DRAWING_EXTENSIONS = ["pdf", "png", "jpg", "jpeg", "dxf", "dwg"] as const;
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
export const MAX_FOLDER_FILES = 200;

export type ModelFormat = "stl" | "step" | "iges" | "brep";

export interface LoadedModel {
  geometry: THREE.BufferGeometry;
  format: ModelFormat;
  triangles: number;
  size: THREE.Vector3;
  center: THREE.Vector3;
  radius: number;
}

export function extOf(name: string): string {
  return name.split(".").pop()?.toLowerCase() ?? "";
}

export function formatOf(name: string): ModelFormat | null {
  const e = extOf(name);
  if (e === "stl") return "stl";
  if (e === "step" || e === "stp") return "step";
  if (e === "iges" || e === "igs") return "iges";
  if (e === "brep") return "brep";
  return null;
}

/** Returns an error message, or null when the file is acceptable. */
export function validateUpload(file: { name: string; size: number }, allowed: readonly string[]): string | null {
  if (!allowed.includes(extOf(file.name))) return `${file.name}: unsupported type. Allowed: ${allowed.map((e) => `.${e}`).join(", ")}.`;
  if (file.size > MAX_UPLOAD_BYTES) return `${file.name}: larger than 50 MB.`;
  if (file.size === 0) return `${file.name}: the file is empty.`;
  return null;
}

function finish(geometry: THREE.BufferGeometry, format: ModelFormat): LoadedModel {
  if (!geometry.attributes.normal) geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  const box = geometry.boundingBox as THREE.Box3;
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const triangles = geometry.index ? geometry.index.count / 3 : geometry.attributes.position.count / 3;
  if (!triangles || !Number.isFinite(size.x)) throw new Error("The file contains no geometry.");
  return { geometry, format, triangles, size, center, radius: (geometry.boundingSphere as THREE.Sphere).radius };
}

export function parseStl(buffer: ArrayBuffer): LoadedModel {
  return finish(new STLLoader().parse(buffer), "stl");
}

let worker: Worker | null = null;
let seq = 0;

interface OcctMesh {
  position: Float32Array;
  normal: Float32Array | null;
  index: Uint32Array;
}

/** STEP / IGES / BREP through occt-import-js in a worker (public/occt-worker.js). */
export function parseOcct(buffer: ArrayBuffer, format: Exclude<ModelFormat, "stl">): Promise<LoadedModel> {
  worker ??= new Worker("/occt-worker.js");
  const id = ++seq;
  const w = worker;
  return new Promise((resolve, reject) => {
    const onMessage = (e: MessageEvent<{ id: number; ok: boolean; meshes?: OcctMesh[]; error?: string }>) => {
      if (e.data.id !== id) return;
      w.removeEventListener("message", onMessage);
      if (!e.data.ok || !e.data.meshes) return reject(new Error(e.data.error ?? "Import failed."));
      try {
        const parts = e.data.meshes.map((m) => {
          const g = new THREE.BufferGeometry();
          g.setAttribute("position", new THREE.BufferAttribute(m.position, 3));
          if (m.normal) g.setAttribute("normal", new THREE.BufferAttribute(m.normal, 3));
          g.setIndex(new THREE.BufferAttribute(m.index, 1));
          if (!m.normal) g.computeVertexNormals();
          return g;
        });
        if (!parts.length) throw new Error("The file contains no solid bodies.");
        const merged = parts.length === 1 ? parts[0] : mergeGeometries(parts, false);
        if (!merged) throw new Error("The bodies in this file could not be merged for display.");
        resolve(finish(merged, format));
      } catch (err) {
        reject(err instanceof Error ? err : new Error(String(err)));
      }
    };
    w.addEventListener("message", onMessage);
    w.postMessage({ id, buffer, format }, [buffer]);
  });
}

export async function loadModelFromUrl(url: string): Promise<LoadedModel> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Could not fetch the model (${res.status}).`);
  const buffer = await res.arrayBuffer();
  const format = formatOf(url.split("?")[0]) ?? "stl";
  return format === "stl" ? parseStl(buffer) : parseOcct(buffer, format);
}

export async function loadModelFromFile(file: File): Promise<LoadedModel> {
  const format = formatOf(file.name);
  if (!format) throw new Error("Unsupported model file.");
  const buffer = await file.arrayBuffer();
  return format === "stl" ? parseStl(buffer) : parseOcct(buffer, format);
}
