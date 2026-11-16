"use client";

/* eslint-disable react-hooks/immutability -- three.js cameras, planes and the renderer are mutable by design; R3F code updates them in place */

import * as React from "react";
import Link from "next/link";
import * as THREE from "three";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { Environment, GizmoHelper, GizmoViewport, Grid, Lightformer, Line, OrbitControls } from "@react-three/drei";
import { Bloom, EffectComposer, Vignette } from "@react-three/postprocessing";
import { Box, Expand, FileUp, Maximize2, RotateCcw, Ruler, Scan, Slice } from "lucide-react";
import { useIntro } from "@/components/shell/Providers";
import { PartGlyph } from "@/components/shell/Atmosphere";
import { DemoTag, SampleBadge, Stamp } from "@/components/shared";
import { MODEL_EXTENSIONS, loadModelFromFile, loadModelFromUrl, validateUpload, type LoadedModel } from "@/lib/cad/loaders";
import { prefersReducedMotion } from "@/lib/motion";
import type { BuildPlan, Locator } from "@/lib/schemas";
import { useSelection } from "@/lib/store";
import { toast } from "sonner";
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
const EMPTY_POINTS: THREE.Vector3[] = [];
const GOLD = new THREE.Color("#D6AF6B");

function Rig({ model, intro, apiRef, linkZoom }: { model: LoadedModel; intro: boolean; apiRef: React.RefObject<RigApi | null>; linkZoom?: number }) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const invalidate = useThree((s) => s.invalidate);
  const controls = useThree((s) => s.controls) as unknown as { target: THREE.Vector3; update: () => void } | null;
  const size = useThree((s) => s.size);
  const anim = React.useRef<{ fromP: THREE.Vector3; toP: THREE.Vector3; fromT: THREE.Vector3; toT: THREE.Vector3; t: number; dur: number } | null>(null);
  const dist = React.useCallback(
    (r: number) => {
      // fit the bounding sphere in the narrower of the two fields of view
      const v = (camera.fov * Math.PI) / 360;
      const aspect = size.height > 0 ? size.width / size.height : camera.aspect;
      const h = Math.atan(Math.tan(v) * Math.min(1, aspect));
      return (r / Math.sin(Math.min(v, h))) * 1.1;
    },
    [camera, size.width, size.height],
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

  // Keep the model framed when the pane is resized (split slider, breakpoint change).
  const lastSize = React.useRef("");
  React.useEffect(() => {
    const key = `${size.width}x${size.height}`;
    if (!controls || placed.current !== model || anim.current) {
      lastSize.current = key;
      return;
    }
    if (lastSize.current && lastSize.current !== key) {
      const dir = camera.position.clone().sub(controls.target).normalize();
      camera.position.copy(controls.target.clone().add(dir.multiplyScalar(dist(model.radius))));
      controls.update();
      invalidate();
    }
    lastSize.current = key;
  }, [size.width, size.height, camera, controls, dist, invalidate, model]);

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

/** Screen-constant text label drawn to a canvas texture (no DOM inside the WebGL tree). */
function TextSprite({ text, position, color = "#F5E6CB" }: { text: string; position: THREE.Vector3 | [number, number, number]; color?: string }) {
  const { texture, aspect } = React.useMemo(() => {
    const pad = 14;
    const font = '600 30px "JetBrains Mono", ui-monospace, monospace';
    const c = document.createElement("canvas");
    const g = c.getContext("2d") as CanvasRenderingContext2D;
    g.font = font;
    c.width = Math.ceil(g.measureText(text).width) + pad * 2;
    c.height = 52;
    g.font = font;
    g.fillStyle = "rgba(18,13,32,.94)";
    g.strokeStyle = color;
    g.lineWidth = 2;
    g.beginPath();
    g.roundRect(1, 1, c.width - 2, c.height - 2, 10);
    g.fill();
    g.stroke();
    g.fillStyle = color;
    g.textBaseline = "middle";
    g.fillText(text, pad, c.height / 2 + 1);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return { texture: t, aspect: c.width / c.height };
  }, [text, color]);
  React.useEffect(() => () => texture.dispose(), [texture]);
  const h = 0.024;
  return (
    <sprite position={position} scale={[h * aspect, h, 1]} renderOrder={10}>
      <spriteMaterial map={texture} sizeAttenuation={false} depthTest={false} transparent toneMapped={false} />
    </sprite>
  );
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
      {label && <TextSprite text={label} position={[r + 3, r + 3, z + 2]} color={color === "#D6AF6B" ? "#F5E6CB" : color} />}
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
        <HoleMarker key={`m${i}`} l={{ kind: "hole", position: [e.x, e.y, model.center.z], radius: e.r, depth: thickness }} color="#FF6680" />
      ))}
      {diff.extra.map((l, i) => (
        <HoleMarker key={`x${i}`} l={l} color="#FF9A3D" opacity={0.9} />
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
          <TextSprite text={`${measure[0].distanceTo(measure[1]).toFixed(3)} ${plan?.units ?? "units"}`} position={measure[0].clone().lerp(measure[1], 0.5)} />
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
  // Loading state is derived from what has been loaded, so nothing is set synchronously in an effect.
  const [remote, setRemote] = React.useState<{ url: string; model: LoadedModel } | null>(null);
  const [failure, setFailure] = React.useState<{ url: string; message: string } | null>(null);
  const [localFile, setLocalFile] = React.useState<{ forUrl: string | null | undefined; name: string; model: LoadedModel } | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [section, setSection] = React.useState({ on: false, offset: 0 });
  const [measuring, setMeasuring] = React.useState(false);
  const [measured, setMeasured] = React.useState<{ model: LoadedModel | null; points: THREE.Vector3[] }>({ model: null, points: [] });

  const local = localFile && localFile.forUrl === modelUrl ? localFile : null;
  const model = local?.model ?? (remote && remote.url === modelUrl ? remote.model : null);
  const error = !model && failure && failure.url === (modelUrl ?? "") ? failure.message : null;
  const state: "idle" | "loading" | "ready" | "error" = busy ? "loading" : model ? "ready" : error ? "error" : modelUrl ? "loading" : "idle";
  const measure = measured.model === model ? measured.points : EMPTY_POINTS;

  React.useEffect(() => {
    if (!modelUrl) return;
    let alive = true;
    loadModelFromUrl(modelUrl)
      .then((m) => {
        if (alive) setRemote({ url: modelUrl, model: m });
      })
      .catch((e: unknown) => {
        if (alive) setFailure({ url: modelUrl, message: e instanceof Error ? e.message : String(e) });
      });
    return () => {
      alive = false;
    };
  }, [modelUrl]);

  const onFile = async (file?: File) => {
    if (!file) return;
    const report = (message: string) => {
      // with a model already on screen, keep it and say what went wrong; otherwise show the error state
      if (model) toast.error(message);
      else setFailure({ url: modelUrl ?? "", message });
    };
    const bad = validateUpload(file, MODEL_EXTENSIONS);
    if (bad) return report(bad);
    setBusy(true);
    try {
      const m = await loadModelFromFile(file);
      setLocalFile({ forUrl: modelUrl, name: file.name, model: m });
      setSection({ on: false, offset: 0 });
    } catch (e) {
      report(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
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
            onMeasure={(p) => setMeasured({ model, points: measure.length >= 2 ? [p] : [...measure, p] })}
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
              setMeasured({ model, points: [] });
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
          {showDiff && expected && (
            <>
              <Stamp tone="danger">Red ring: on the drawing, not modeled</Stamp>
              <Stamp tone="warn">Orange ring: modeled, not at a drawing position</Stamp>
            </>
          )}
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
