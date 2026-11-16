/* Classic worker: loads occt-import-js (LGPL-2.1, WASM build of OpenCASCADE) and triangulates
   a STEP / IGES / BREP file off the main thread. Files never leave the browser. */
importScripts("/occt-import-js.js");
let occtPromise = null;
self.onmessage = async (e) => {
  const { id, buffer, format } = e.data;
  try {
    occtPromise = occtPromise || occtimportjs({ locateFile: () => "/occt-import-js.wasm" });
    const occt = await occtPromise;
    const bytes = new Uint8Array(buffer);
    const result =
      format === "iges" ? occt.ReadIgesFile(bytes, null) : format === "brep" ? occt.ReadBrepFile(bytes, null) : occt.ReadStepFile(bytes, null);
    if (!result || !result.success) throw new Error("The file could not be read as " + format.toUpperCase() + ".");
    const meshes = result.meshes.map((m) => ({
      name: m.name || "",
      color: m.color || null,
      position: new Float32Array(m.attributes.position.array),
      normal: m.attributes.normal ? new Float32Array(m.attributes.normal.array) : null,
      index: new Uint32Array(m.index.array),
    }));
    const transfer = [];
    for (const m of meshes) {
      transfer.push(m.position.buffer, m.index.buffer);
      if (m.normal) transfer.push(m.normal.buffer);
    }
    self.postMessage({ id, ok: true, meshes }, transfer);
  } catch (err) {
    self.postMessage({ id, ok: false, error: String((err && err.message) || err) });
  }
};
