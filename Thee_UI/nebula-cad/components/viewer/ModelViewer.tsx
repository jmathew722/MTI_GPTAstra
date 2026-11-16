"use client";

import * as React from "react";
import Link from "next/link";
import * as THREE from "three";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { Environment, GizmoHelper, GizmoViewport, Grid, Html, Lightformer, Line, OrbitControls } from "@react-three/drei";
import { Bloom, EffectComposer, Vignette } from "@react-three/postprocessing";
import { Box, Expand, FileUp, Maximize2, RotateCcw, Ruler, Scan, Slice } from "lucide-react";
import { useIntro } from "@/components/shell/Providers";
import { PartGlyph } from "@/components/shell/Atmosphere";
import { DemoTag, SampleBadge, Stamp } from "@/components/shared";
import { MODEL_EXTENSIONS, loadModelFromFile, loadModelFromUrl, validateUpload, type LoadedModel } from "@/lib/cad/loaders";
import { prefersReducedMotion } from "@/lib/motion";
import type { BuildPlan, Locator } from "@/lib/schemas";
import { useSelection } from "@/lib/store";
import { cn } from "@/lib/utils";

export interface ExpectedHole {
  x: number;
  y: number;
  r: number;
}

interface RigApi {
  fit: () => void;
  reset: () => void;
  view: (name: "front" | "top" | "iso") => void;
  focus: (p: THREE.Vector3, r: number) => void;
}

const ISO = new THREE.Vector3(0.9, -1.15, 0.85).normalize();
const GOLD = new THREE.Color("#D6AF6B");

function Rig({ model, intro, apiRef, linkZoom }: { model: LoadedModel; intro: boolean; apiRef: React.RefObject<RigApi | null>; linkZoom?: number }) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const invalidate = useThree((s) => s.invalidate);
  const controls = useThree((s) => s.controls) as unknown as { target: THREE.Vector3; update: () => void } | null;
  const anim = React.useRef<{ fromP: THREE.Vector3; toP: THREE.Vector3; fromT: THREE.Vector3; toT: THREE.Vector3; t: number; dur: number } | null>(null);
  const dist = React.useCallback(
    (r: number) => {
      // fit the bounding sphere in the narrower of the two fields of view
      const v = (camera.fov * Math.PI) / 360;
      const h = Math.atan(Math.tan(v) * Math.min(1, camera.aspect));
      return (r / Math.sin(Math.min(v, h))) * 1.08;
    },
    [camera],
  );

  const go = React.useCallback(
    (toP: THREE.Vector3, toT: THREE.Vector3, dur = 0.65) => {
      anim.current = {
        fromP: camera.position.clone(),
        toP,
        fromT: controls ? controls.target.clone() : model.center.clone(),
        toT,
        t: 0,
        dur: prefersReducedMotion() ? 0.001 : dur,
      };
      invalidate();
    },
    [camera, controls, invalidate, model.center],
  );

  React.useImperativeHandle(
    apiRef,
    () => ({
      fit: () => {
        const dir = camera.position.clone().sub(controls ? controls.target : model.center).normalize();
        go(model.center.clone().add(dir.multiplyScalar(dist(model.radius))), model.center.clone());
      },
      reset: () => go(model.center.clone().add(ISO.clone().multiplyScalar(dist(model.radius))), model.center.clone()),
      view: (name) => {
        const d = name === "front" ? new THREE.Vector3(0, 0.0001, 1) : name === "top" ? new THREE.Vector3(0, -1, 0.0001) : ISO.clone();
        go(model.center.clone().add(d.normalize().multiplyScalar(dist(model.radius))), model.center.clone());
      },
      focus: (p, r) => {
        const dir = camera.position.clone().sub(controls ? controls.target : model.center).normalize();
        go(p.clone().add(dir.multiplyScalar(dist(Math.max(r * 3.2, model.radius * 0.35)))), p.clone());
      },
    }),
    [camera, controls, dist, go, model],
  );

  // First placement: a slow ease-in on the session's first load, otherwise immediate.
  const placed = React.useRef<LoadedModel | null>(null);
  React.useEffect(() => {
    if (!controls || placed.current === model) return;
    placed.current = model;
    const home = model.center.clone().add(ISO.clone().multiplyScalar(dist(model.radius)));
    camera.near = Math.max(0.01, model.radius / 200);
    camera.far = model.radius * 80;
    camera.updateProjectionMatrix();
    if (intro && !prefersReducedMotion()) {
      camera.position.copy(model.center.clone().add(ISO.clone().multiplyScalar(dist(model.radius) * 1.7)));
      controls.target.copy(model.center);
      go(home, model.center.clone(), 1.6);
    } else {
      camera.position.copy(home);
      controls.target.copy(model.center);
      controls.update();
      invalidate();
    }
  }, [camera, controls, dist, go, intro, invalidate, model]);

  // Linked zoom: the drawing's zoom factor sets the camera distance along the current view direction.
  React.useEffect(() => {
    if (linkZoom === undefined || !controls || anim.current) return;
    const dir = camera.position.clone().sub(controls.target).normalize();
    camera.position.copy(controls.target.clone().add(dir.multiplyScalar(dist(model.radius) / linkZoom)));
    controls.update();
    invalidate();
  }, [linkZoom, camera, controls, dist, invalidate, model.radius]);

  useFrame((_, dt) => {
    const a = anim.current;
    if (!a) return;
    a.t = Math.min(1, a.t + dt / a.dur);
    const e = 1 - Math.pow(1 - a.t, 3);
    camera.position.lerpVectors(a.fromP, a.toP, e);
    if (controls) {
      controls.target.lerpVectors(a.fromT, a.toT, e);
      controls.update();
    }
    if (a.t >= 1) anim.current = null;
    else invalidate();
  });
  return null;
}

function HoleMarker({ l, color, opacity = 1, label }: { l: Locator; color: string; opacity?: number; label?: string }) {
  const r = (l.radius ?? 2) + 0.9;
  const z = (l.depth ?? 0) / 2 + 0.15;
  return (
    <group position={[l.position[0], l.position[1], l.position[2]]}>
      {[z, -z].map((zz) => (
        <mesh key={zz} position={[0, 0, zz]}>
          <torusGeometry args={[r, 0.42, 10, 48]} />
          <meshStandardMaterial color={color} emissive={color} emissiveIntensity={2.4} toneMapped={false} transparent opacity={opacity} />
        </mesh>
      ))}
      {label && (
        <Html position={[r + 2, r + 2, z]} zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
          <div className="num whitespace-nowrap rounded-md border border-gold/60 bg-[#120d20]/95 px-1.5 py-0.5 text-[11px] font-medium text-gold-hi shadow-lg">{label}</div>
        </Html>
      )}
    </group>
  );
}

function Scene({
  model,
  plan,
  expected,
  showDiff,
  section,
  measuring,
  onMeasure,
  measure,
  rigRef,
  intro,
  linkZoom,
}: {
  model: LoadedModel;
  plan?: BuildPlan | null;
  expected?: ExpectedHole[];
  showDiff: boolean;
  section: { on: boolean; offset: number };
  measuring: boolean;
  onMeasure: (p: THREE.Vector3) => void;
  measure: THREE.Vector3[];
  rigRef: React.RefObject<RigApi | null>;
  intro: boolean;
  linkZoom?: number;
}) {
  const featureId = useSelection((s) => s.featureId);
  const tick = useSelection((s) => s.tick);
  const invalidate = useThree((s) => s.invalidate);
  const gl = useThree((s) => s.gl);
  const edges = React.useMemo(() => new THREE.EdgesGeometry(model.geometry, 28), [model.geometry]);
  const plane = React.useMemo(() => new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0), []);
  React.useEffect(() => {
    gl.localClippingEnabled = true;
  }, [gl]);
  React.useEffect(() => {
    plane.constant = model.center.x + section.offset;
    invalidate();
  }, [plane, section.offset, section.on, model.center.x, invalidate]);
  React.useEffect(() => () => edges.dispose(), [edges]);

  const selected = React.useMemo(() => (featureId && plan ? plan.operations.filter((o) => o.featureId === featureId) : []), [featureId, plan]);
  const locators = React.useMemo(() => {
    // the pattern operation already lists every instance; otherwise use the seed's locators
    const withMost = [...selected].sort((a, b) => (b.locators?.length ?? 0) - (a.locators?.length ?? 0))[0];
    return withMost?.locators ?? [];
  }, [selected]);
  const bodySelected = locators.some((l) => l.kind === "body");
  const holeLocs = locators.filter((l) => l.kind === "hole");

  // Smooth camera move to the selected feature.
  React.useEffect(() => {
    if (!holeLocs.length && !bodySelected) return;
    if (bodySelected || holeLocs.length > 1) rigRef.current?.fit();
    else {
      const l = holeLocs[0];
      rigRef.current?.focus(new THREE.Vector3(...l.position), l.radius ?? 4);
    }
    invalidate();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run only when a selection is made
  }, [tick, featureId]);

  const modeledHoles = React.useMemo(
    () => (plan?.operations ?? []).flatMap((o) => (o.type === "pattern" || o.type === "hole" ? (o.locators ?? []) : [])).filter((l) => l.kind === "hole"),
    [plan],
  );
  const diff = React.useMemo(() => {
    if (!showDiff || !expected) return { missing: [] as ExpectedHole[], extra: [] as Locator[] };
    const near = (ax: number, ay: number, bx: number, by: number, tol: number) => Math.hypot(ax - bx, ay - by) <= tol;
    const missing = expected.filter((e) => !modeledHoles.some((m) => near(e.x, e.y, m.position[0], m.position[1], Math.max(0.5, e.r * 0.5))));
    const seen = new Set<string>();
    const extra = modeledHoles.filter((m) => {
      const key = `${m.position[0].toFixed(2)},${m.position[1].toFixed(2)}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return !expected.some((e) => near(e.x, e.y, m.position[0], m.position[1], Math.max(0.5, e.r * 0.5)));
    });
    return { missing, extra };
  }, [showDiff, expected, modeledHoles]);
  const thickness = plan?.thickness ?? model.size.z;

  const onDown = (e: ThreeEvent<PointerEvent>) => {
    if (!measuring) return;
    e.stopPropagation();
    onMeasure(e.point.clone());
  };
  const clip = section.on ? [plane] : [];
  const floor = model.center.z - model.size.z / 2 - Math.max(0.6, model.radius * 0.02);

  return (
    <>
      <ambientLight intensity={0.35} />
      <directionalLight position={[model.radius * 2, -model.radius * 2, model.radius * 3]} intensity={1.6} color="#e9e6ff" />
      <directionalLight position={[-model.radius * 3, model.radius * 2.5, model.radius * 0.6]} intensity={3.2} color="#D6AF6B" />
      <directionalLight position={[model.radius, model.radius * 3, -model.radius * 2]} intensity={0.9} color="#A67CFF" />
      <Environment resolution={256} frames={1}>
        <color attach="background" args={["#07050d"]} />
        <Lightformer form="rect" intensity={3} color="#ffffff" position={[0, 6, 4]} scale={[10, 2, 1]} />
        <Lightformer form="rect" intensity={5} color="#D6AF6B" position={[-7, 1, -2]} rotation={[0, Math.PI / 2, 0]} scale={[8, 1.6, 1]} />
        <Lightformer form="rect" intensity={2} color="#A67CFF" position={[7, -1, 2]} rotation={[0, -Math.PI / 2, 0]} scale={[8, 2, 1]} />
        <Lightformer form="ring" intensity={1.5} color="#cfc9e6" position={[0, -6, 3]} scale={5} />
      </Environment>

      <mesh geometry={model.geometry} onPointerDown={onDown}>
        <meshStandardMaterial color="#b6b1c6" metalness={0.92} roughness={0.34} envMapIntensity={1.15} clippingPlanes={clip} side={section.on ? THREE.DoubleSide : THREE.FrontSide} />
      </mesh>
      <lineSegments geometry={edges}>
        <lineBasicMaterial
          color={bodySelected ? GOLD : "#E9D9B8"}
          transparent
          opacity={bodySelected ? 1 : 0.34}
          toneMapped={!bodySelected}
          clippingPlanes={clip}
        />
      </lineSegments>

      {holeLocs.map((l, i) => (
        <HoleMarker
          key={`${featureId}-${i}`}
          l={l}
          color="#D6AF6B"
          label={i === 0 && l.radius ? `Ø${(l.radius * 2).toFixed(3)} ${plan?.units ?? ""}${holeLocs.length > 1 ? ` × ${holeLocs.length}` : ""}` : undefined}
        />
      ))}
      {diff.missing.map((e, i) => (
        <HoleMarker key={`m${i}`} l={{ kind: "hole", position: [e.x, e.y, model.center.z], radius: e.r, depth: thickness }} color="#FF6680" label={i === 0 ? `on drawing, not modeled × ${diff.missing.length}` : undefined} />
      ))}
      {diff.extra.map((l, i) => (
        <HoleMarker key={`x${i}`} l={l} color="#FF9A3D" opacity={0.9} label={i === 0 ? `modeled, not at a drawing position × ${diff.extra.length}` : undefined} />
      ))}

      {measure.map((p, i) => (
        <mesh key={i} position={p}>
          <sphereGeometry args={[Math.max(0.5, model.radius * 0.012), 16, 16]} />
          <meshBasicMaterial color="#F5E6CB" toneMapped={false} />
        </mesh>
      ))}
      {measure.length === 2 && (
        <>
          <Line points={[measure[0], measure[1]]} color="#F5E6CB" lineWidth={1.5} dashed={false} />
          <Html position={measure[0].clone().lerp(measure[1], 0.5)} zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
            <div className="num -translate-x-1/2 whitespace-nowrap rounded-md border border-gold/70 bg-[#120d20]/95 px-2 py-0.5 text-xs font-semibold text-gold-hi">
              {measure[0].distanceTo(measure[1]).toFixed(3)} {plan?.units ?? "units"}
            </div>
          </Html>
        </>
      )}

      <Grid
        position={[model.center.x, model.center.y, floor]}
        rotation={[Math.PI / 2, 0, 0]}
        args={[10, 10]}
        infiniteGrid
        cellSize={Math.max(1, Math.round(model.radius / 10))}
        sectionSize={Math.max(5, Math.round(model.radius / 10) * 5)}
        cellColor="#3a2c66"
        sectionColor="#5a4396"
        cellThickness={0.6}
        sectionThickness={1}
        fadeDistance={model.radius * 9}
        fadeStrength={1.6}
      />
      <OrbitControls makeDefault enableDamping dampingFactor={0.12} minDistance={model.radius * 0.3} maxDistance={model.radius * 14} />
      <Rig model={model} intro={intro} apiRef={rigRef} linkZoom={linkZoom} />
      <GizmoHelper alignment="bottom-left" margin={[58, 58]}>
        <GizmoViewport axisColors={["#FF6680", "#D6AF6B", "#A67CFF"]} labelColor="#0B0814" />
      </GizmoHelper>
      <EffectComposer multisampling={4}>
        <Bloom mipmapBlur luminanceThreshold={1} luminanceSmoothing={0.2} intensity={0.75} />
        <Vignette eskil={false} offset={0.22} darkness={0.62} />
      </EffectComposer>
    </>
  );
}

type TbProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string; pressed?: boolean };
function Tb({ label, pressed, className, children, ...rest }: TbProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      className={cn("btn btn-icon btn-sm glass-raised rounded-lg border-line text-muted-foreground hover:text-text", className)}
      {...rest}
    >
      {children}
    </button>
  );
}

export interface ModelViewerProps {
  modelUrl?: string | null;
  fileName?: string;
  plan?: BuildPlan | null;
  expected?: ExpectedHole[];
  showDiff?: boolean;
  specKey?: string | null;
  isSample?: boolean;
  fullHref?: string;
  allowLoad?: boolean;
  compact?: boolean;
  /** drawing zoom factor to mirror (Compare: Link zoom) */
  linkZoom?: number;
  className?: string;
}

export default function ModelViewer({ modelUrl, fileName, plan, expected, showDiff = false, specKey, isSample, fullHref, allowLoad = true, compact, linkZoom, className }: ModelViewerProps) {
  const intro = useIntro();
  const wrap = React.useRef<HTMLDivElement>(null);
  const input = React.useRef<HTMLInputElement>(null);
  const rig = React.useRef<RigApi | null>(null);
  const [model, setModel] = React.useState<LoadedModel | null>(null);
  const [local, setLocal] = React.useState<{ name: string } | null>(null);
  const [state, setState] = React.useState<"idle" | "loading" | "ready" | "error">("idle");
  const [error, setError] = React.useState<string | null>(null);
  const [section, setSection] = React.useState({ on: false, offset: 0 });
  const [measuring, setMeasuring] = React.useState(false);
  const [measure, setMeasure] = React.useState<THREE.Vector3[]>([]);

  React.useEffect(() => {
    let alive = true;
    setLocal(null);
    setMeasure([]);
    if (!modelUrl) {
      setModel(null);
      setState("idle");
      return;
    }
    setState("loading");
    loadModelFromUrl(modelUrl)
      .then((m) => {
        if (!alive) return;
        setModel(m);
        setState("ready");
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : String(e));
        setState("error");
      });
    return () => {
      alive = false;
    };
  }, [modelUrl]);

  const onFile = async (file?: File) => {
    if (!file) return;
    const bad = validateUpload(file, MODEL_EXTENSIONS);
    if (bad) {
      setError(bad);
      setState("error");
      return;
    }
    setState("loading");
    try {
      const m = await loadModelFromFile(file);
      setModel(m);
      setLocal({ name: file.name });
      setMeasure([]);
      setSection({ on: false, offset: 0 });
      setState("ready");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setState("error");
    }
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "f" || e.key === "F") rig.current?.fit();
    else if (e.key === "r" || e.key === "R") rig.current?.reset();
    else return;
    e.stopPropagation();
  };
  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void wrap.current?.requestFullscreen?.();
  };
  const showPlan = local ? null : plan;
  const name = local?.name ?? fileName;

  return (
    <div
      ref={wrap}
      tabIndex={0}
      onKeyDown={onKey}
      role="group"
      aria-label={`3D model viewer${name ? `: ${name}` : ""}. Drag to orbit, scroll to zoom. Press F to fit, R to reset.`}
      className={cn("well @container relative isolate min-h-[240px] overflow-hidden bg-[radial-gradient(80%_70%_at_50%_45%,#1a1232_0%,#07050d_70%)]", className)}
    >
      {state === "ready" && model ? (
        <Canvas
          frameloop="demand"
          dpr={[1, 2]}
          camera={{ fov: 32, up: [0, 0, 1], position: [200, -260, 190] }}
          gl={{ antialias: true, powerPreference: "high-performance" }}
          className={cn("!absolute inset-0", measuring && "cursor-crosshair")}
          aria-hidden
        >
          <Scene
            model={model}
            plan={showPlan}
            expected={local ? undefined : expected}
            showDiff={showDiff}
            section={section}
            measuring={measuring}
            measure={measure}
            onMeasure={(p) => setMeasure((prev) => (prev.length >= 2 ? [p] : [...prev, p]))}
            rigRef={rig}
            intro={intro}
            linkZoom={linkZoom}
          />
        </Canvas>
      ) : (
        <div className="absolute inset-0 grid place-items-center p-6 text-center">
          {state === "loading" ? (
            <div role="status" className="flex flex-col items-center gap-3">
              <div className="skel size-24 rounded-2xl" />
              <span className="text-sm text-muted-foreground">Loading model…</span>
            </div>
          ) : state === "error" ? (
            <div role="alert" className="max-w-sm rounded-xl border border-danger/50 bg-danger/10 p-4 text-left">
              <p className="text-sm font-semibold text-danger">The model could not be displayed</p>
              <p className="mt-1 text-[13px] text-text/90">{error}</p>
              {allowLoad && (
                <button type="button" className="btn btn-sm btn-ghost mt-3" onClick={() => input.current?.click()}>
                  <FileUp className="size-3.5" aria-hidden /> Load another file
                </button>
              )}
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3">
              <PartGlyph specKey={specKey} className="size-28 opacity-70" />
              <Stamp tone="dashed">Static preview</Stamp>
              <p className="max-w-[40ch] text-[13px] text-muted-foreground">
                No model has been built for this project, so there is nothing to orbit. Load an STL or STEP file to inspect it here.
              </p>
              {allowLoad && (
                <button type="button" className="btn btn-sm btn-outline" onClick={() => input.current?.click()}>
                  <FileUp className="size-4" aria-hidden /> Load STL / STEP
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* toolbar */}
      {state === "ready" && model && (
        <div className="absolute right-2 top-2 z-10 flex flex-wrap items-center justify-end gap-1.5" role="toolbar" aria-label="Viewer tools">
          <Tb label="Fit model (F)" onClick={() => rig.current?.fit()}>
            <Scan className="size-4" aria-hidden />
          </Tb>
          <Tb label="Reset camera (R)" onClick={() => rig.current?.reset()}>
            <RotateCcw className="size-4" aria-hidden />
          </Tb>
          {!compact && (
            <>
              <Tb label="Front view" onClick={() => rig.current?.view("front")} className="hidden w-auto px-2 text-xs font-semibold @md:inline-flex">
                Front
              </Tb>
              <Tb label="Top view" onClick={() => rig.current?.view("top")} className="hidden w-auto px-2 text-xs font-semibold @md:inline-flex">
                Top
              </Tb>
              <Tb label="Isometric view" onClick={() => rig.current?.view("iso")}>
                <Box className="size-4" aria-hidden />
              </Tb>
            </>
          )}
          <Tb label="Section plane" pressed={section.on} onClick={() => setSection((s) => ({ ...s, on: !s.on }))}>
            <Slice className="size-4" aria-hidden />
          </Tb>
          <Tb
            label="Measure distance between two points"
            pressed={measuring}
            onClick={() => {
              setMeasuring((m) => !m);
              setMeasure([]);
            }}
          >
            <Ruler className="size-4" aria-hidden />
          </Tb>
          {allowLoad && (
            <Tb label="Load a local STL, STEP, IGES or BREP file" onClick={() => input.current?.click()}>
              <FileUp className="size-4" aria-hidden />
            </Tb>
          )}
          {fullHref && (
            <Link href={fullHref} aria-label="Open in the full-screen viewer" title="Open in the full-screen viewer" className="btn btn-icon btn-sm glass-raised rounded-lg border-line text-muted-foreground hover:text-text">
              <Expand className="size-4" aria-hidden />
            </Link>
          )}
          <Tb label="Toggle fullscreen" onClick={toggleFullscreen}>
            <Maximize2 className="size-4" aria-hidden />
          </Tb>
        </div>
      )}

      {state === "ready" && section.on && model && (
        <label className="glass-raised absolute left-1/2 top-2 z-10 flex -translate-x-1/2 items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground">
          Section X
          <input
            type="range"
            min={-model.size.x / 2}
            max={model.size.x / 2}
            step={model.size.x / 200}
            value={section.offset}
            onChange={(e) => setSection({ on: true, offset: Number(e.target.value) })}
            className="w-32 accent-[#D6AF6B]"
            aria-label="Section plane position along X"
          />
          <span className="num w-14 text-right text-text">{section.offset.toFixed(1)}</span>
        </label>
      )}
      {state === "ready" && measuring && (
        <div className="glass-raised absolute bottom-12 left-1/2 z-10 -translate-x-1/2 px-3 py-1.5 text-xs text-text" role="status">
          {measure.length === 0 ? "Click the first point on the model." : measure.length === 1 ? "Click the second point." : "Distance shown. Click again to start over."}
        </div>
      )}

      {/* info strip */}
      {state === "ready" && model && (
        <div className="pointer-events-none absolute inset-x-2 bottom-2 z-10 flex flex-wrap items-center justify-end gap-1.5">
          {showDiff && expected && <Stamp tone="danger">Diff: red = on drawing, not modeled</Stamp>}
          <span className="num rounded-md border border-line bg-[#0d0919]/85 px-1.5 py-0.5 text-[11px] text-muted-foreground">
            <span className="hidden @md:inline">{name ? `${name} · ` : ""}</span>
            {model.format.toUpperCase()} · {Math.round(model.triangles).toLocaleString("en-US")} tris · {model.size.x.toFixed(1)} × {model.size.y.toFixed(1)} × {model.size.z.toFixed(1)}
            {plan && !local ? ` ${plan.units}` : ""}
          </span>
          {local ? <Stamp tone="violet">Local file</Stamp> : isSample ? <SampleBadge /> : null}
          {local && plan && <DemoTag title="Feature highlights are hidden: a local file has no build plan." />}
        </div>
      )}

      <input
        ref={input}
        type="file"
        accept={MODEL_EXTENSIONS.map((e) => `.${e}`).join(",")}
        className="sr-only"
        tabIndex={-1}
        aria-label="Load a local model file"
        onChange={(e) => {
          void onFile(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
    </div>
  );
}
