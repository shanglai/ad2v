// The isometric map: an orthographic camera at a fixed isometric angle, instanced glyphs per base
// shape, screen-space status outlines, LOD edges between visible representatives, portals, badges
// and labels. It renders a MapModel; it never queries data or decides statuses.
import * as THREE from "three";
import type { Box, EdgeRow, StatusInfo } from "../data/types";
import { aggregateEdges, DEFAULT_GROUPS, type AggEdge, type EdgeGroup } from "../model/edges";
import {
  declutterEdges,
  EDGE_LIMIT,
  labelPriority,
  liftEdges,
  mergePortals,
  placeLabels,
  type EdgeMode,
  type LabelCand,
  type PortalIn,
  type WallSide,
} from "../model/declutter";
import { Lod, THRESHOLDS } from "../model/lod";
import { PORT_KINDS, type SceneTree } from "../model/tree";
import type { DiffEntry } from "../model/text";
import { OVERLAY_BADGES, statusColors, token, type LineStyle, type Theme } from "../theme";
import { Atlas, badgeKey, BillboardSet, type Billboard } from "./billboards";
import { RibbonSet, type Polyline } from "./ribbons";
import { bodyColor, dimmed, outlineFor } from "./style";
import { BASE_SHAPES, geometry, outline, type BaseShape } from "./shapes";

const ISO = new THREE.Vector3(1, 1, 1).normalize();
const VIEW_H = 60; // world units visible vertically at zoom 1
const STEP_MIN_PX = THRESHOLDS[1]!; // a replay step is framed at least at the label LOD (40 px)
const STEP_RING_PX = 44; // a step that cannot reach STEP_MIN_PX without losing its siblings gets a ring this tall
const STEP_MIN_INSIDE = 0.9; // re-fit when more than 10% of a step is off-screen (ADR-0050)
const FOOTPRINT = 0.82; // iso foreshortening of a ground-plane extent
const EDGE_STYLE: Record<EdgeGroup, LineStyle> = {
  calls: "solid",
  data: "dashed",
  messages: "dotted",
  exposes: "dash_dot",
  external: "solid",
  imports: "dotted",
};

export interface MapModel {
  tree: SceneTree;
  status: Map<string, StatusInfo>;
  rollups: Map<string, Record<string, number>>;
  edges: EdgeRow[];
  label: (id: string) => string;
  effective: boolean;
  suggestionNodes: Set<string>; // nodes with an open (deduplicated) suggestion
  suggestionPairs: Array<[string, string]>; // spec, code: dotted connectors
  showSuggestions: boolean;
  links: Array<{ spec: string; code: string; kind: "normative" | "suggestion" }>; // for the selection
  diff: Map<string, DiffEntry> | null;
  ghosts: Array<{ id: string; box: Box; label: string }>;
}

export interface ReplayView {
  nodes: string[]; // current step (fine or coarse), mapped to representatives by the scene
  prev: string[];
  /** P6 `path` intent: an ordered list of nodes, all outlined and joined in order (replay styling). */
  path?: string[];
}

export interface PerfStats {
  fps: number;
  frameMs: number;
  drawCalls: number;
  visibleNodes: number;
  triangles: number;
}

interface Handlers {
  hover: (id: string | null, x: number, y: number) => void;
  click: (id: string | null) => void;
  dblclick: (id: string | null) => void;
  portal: (id: string) => void;
  view: () => void;
}

export class MapScene {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera: THREE.OrthographicCamera;
  readonly target = new THREE.Vector3();
  private model: MapModel | null = null;
  private theme: Theme;
  private themeName: "dark" | "light" = "dark";
  private readonly meshes = new Map<BaseShape, THREE.InstancedMesh>();
  private ghostMesh: THREE.InstancedMesh;
  private readonly outlines = new RibbonSet({ renderOrder: 3 });
  private readonly emphasis = new RibbonSet({ soft: true, renderOrder: 2 });
  private readonly edgeSet = new RibbonSet({ renderOrder: 1 });
  private readonly overlaySet = new RibbonSet({ renderOrder: 4, depthTest: false });
  private readonly atlas: Atlas;
  private readonly billboards: BillboardSet;
  private lods = new Map<string, Lod>();
  private visKey = "";
  private selection: string | null = null;
  private emph: string[] | null = null; // P6.1: the step / path / focus nodes; the rest is dimmed
  private dimOn = true;
  private dimSet: Set<string> | null = null; // visible nodes drawn dimmed, computed once per rebuild
  private focus: string | null = null;
  private replay: ReplayView | null = null;
  private dirty = true;
  private camDist = 1000; // camera distance along the iso axis; grows with the map
  private minZoom = 0.02; // lets the home view fit the whole map, and a little more
  private movedAt = 0; // labels are re-placed once the camera has settled
  private dashT = 0;
  private flight: { from: THREE.Vector3; to: THREE.Vector3; z0: number; z1: number; t0: number; ms: number } | null =
    null;
  private readonly instanceIds = new Map<THREE.InstancedMesh, string[]>();
  private portals: Array<{ el: HTMLElement; at: THREE.Vector3; side: WallSide; stack: number }> = [];
  // P7 UX v2 (ADR-0061)
  private edgeMode: EdgeMode = "all";
  edgeLimit = EDGE_LIMIT;
  private hoverId: string | null = null;
  private prevLabels = new Set<string>();
  edgeStats = { visible: 0, hidden: 0, limited: false };
  private perf: PerfStats = { fps: 0, frameMs: 0, drawCalls: 0, visibleNodes: 0, triangles: 0 };
  private frames: number[] = [];
  reducedMotion = false;
  edgeGroups: ReadonlySet<EdgeGroup> = DEFAULT_GROUPS;

  constructor(
    private readonly container: HTMLElement,
    theme: Theme,
    private readonly on: Handlers,
  ) {
    this.theme = theme;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    container.appendChild(this.renderer.domElement);
    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -2000, 4000);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(0.6, 1.4, 0.3);
    this.scene.add(sun);
    for (const shape of BASE_SHAPES) {
      const m = new THREE.InstancedMesh(geometry(shape), new THREE.MeshLambertMaterial(), 1);
      m.count = 0;
      m.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      m.frustumCulled = false;
      this.meshes.set(shape, m);
      this.scene.add(m);
    }
    this.ghostMesh = new THREE.InstancedMesh(
      geometry("rounded_box"),
      new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false }),
      1,
    );
    this.ghostMesh.count = 0;
    this.ghostMesh.frustumCulled = false;
    this.scene.add(this.ghostMesh);
    this.atlas = new Atlas(
      () => ({ text: this.theme.text, halo: this.theme.background }),
      (s) => statusColors(this.theme, s).stroke,
    );
    this.billboards = new BillboardSet(this.atlas);
    for (const r of [this.edgeSet, this.emphasis, this.outlines, this.overlaySet]) this.scene.add(r.mesh);
    this.scene.add(this.billboards.mesh);
    this.applyTheme();
    this.bindInput();
    new ResizeObserver(() => this.resize()).observe(container);
    this.resize();
    const loop = (t: number): void => {
      this.frame(t);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  // -- public API ------------------------------------------------------------------------------
  setModel(m: MapModel, keepView = false): void {
    this.model = m;
    // keep the whole map between the near and far planes (dispatch is ~8,500 units wide)
    const ext = Math.max(0, ...m.tree.roots.map((r) => { const b = m.tree.nodes.get(r)!.box; return b.x + b.w + b.y + b.h; }));
    this.camDist = Math.max(1000, ext);
    this.camera.near = -2 * this.camDist;
    this.camera.far = 4 * this.camDist;
    this.minZoom = Math.min(0.02, (0.5 * VIEW_H) / Math.max(1, ext));
    this.lods = new Map();
    this.visKey = "";
    this.dirty = true;
    if (!keepView) this.home(true);
  }

  setTheme(theme: Theme, name: "dark" | "light"): void {
    this.theme = theme;
    this.themeName = name;
    this.applyTheme();
    this.atlas.reset();
    this.visKey = "";
    this.dirty = true;
  }

  setSelection(id: string | null): void {
    this.selection = id;
    this.visKey = "";
    this.dirty = true;
  }

  setFocus(id: string | null): void {
    this.focus = id;
    this.visKey = "";
    this.dirty = true;
  }

  setReplay(r: ReplayView | null): void {
    this.replay = r;
    this.visKey = "";
    this.dirty = true;
  }

  /** P6.1 "dim the rest" (ADR-0051): emphasize these nodes (a replay step, a path, a focus); null = none. */
  setEmphasis(ids: string[] | null): void {
    this.emph = ids && ids.length ? [...ids] : null;
    this.visKey = "";
    this.dirty = true;
  }

  setDim(on: boolean): void {
    this.dimOn = on;
    this.visKey = "";
    this.dirty = true;
  }

  get dimEnabled(): boolean {
    return this.dimOn;
  }

  /** P7: all edges, only the selection's (+ hover), or aggregated to parents below the label LOD. */
  setEdgeMode(mode: EdgeMode): void {
    this.edgeMode = mode;
    this.visKey = "";
    this.dirty = true;
  }

  get edgesMode(): EdgeMode {
    return this.edgeMode;
  }

  /** Hovering a node shows its edges when edges are decluttered (selection mode, or over the limit). */
  setHover(id: string | null): void {
    if (id === this.hoverId) return;
    this.hoverId = id;
    if (this.edgeMode === "selection" || this.edgeStats.limited) {
      this.visKey = "";
      this.dirty = true;
    }
  }

  /** Whether a visible node is drawn dimmed now (for tests and the a11y summary). */
  isDimmed(id: string): boolean {
    return this.dimSet !== null && this.dimSet.has(id);
  }

  private keepFn(): ((id: string) => boolean) | null {
    const m = this.model;
    if (!m || !this.emph || !this.dimOn) return null;
    const core = new Set<string>();
    for (const id of this.emph) {
      if (!m.tree.nodes.has(id)) continue;
      core.add(id);
      const r = this.rep(id);
      if (r !== null) core.add(r);
    }
    if (!core.size) return null;
    const anc = new Set<string>();
    for (const id of core) for (const a of m.tree.ancestors(id)) anc.add(a);
    // the step itself, what is inside it, and the containers it sits in stay at full color
    return (id) => core.has(id) || anc.has(id) || m.tree.ancestors(id).some((a) => core.has(a));
  }

  getFocus(): string | null {
    return this.focus;
  }

  stats(): PerfStats {
    return { ...this.perf };
  }

  /** Visible nodes and their LOD (for tests, the HUD and keyboard navigation). */
  visibleLods(): Map<string, Lod> {
    return new Map(this.lods);
  }

  pxPerUnit(): number {
    const h = this.renderer.domElement.clientHeight || 1;
    return (h * this.camera.zoom) / VIEW_H;
  }

  home(instant = false): void {
    const m = this.model;
    if (!m) return;
    const roots = m.tree.roots.map((r) => m.tree.nodes.get(r)!.box);
    const minX = Math.min(...roots.map((b) => b.x)), maxX = Math.max(...roots.map((b) => b.x + b.w));
    const minY = Math.min(...roots.map((b) => b.y)), maxY = Math.max(...roots.map((b) => b.y + b.h));
    this.frameBox({ x: minX, y: minY, z: 0, w: maxX - minX, h: maxY - minY, d: 1 }, instant, 0.9);
  }

  /** Frame the union of several nodes' boxes (P6 `fit` intent). */
  fit(ids: string[], instant = false, fill?: number): void {
    const boxes = ids.map((i) => this.model?.tree.nodes.get(i)?.box).filter((b): b is Box => b !== undefined);
    if (!boxes.length) return;
    const x0 = Math.min(...boxes.map((b) => b.x)), x1 = Math.max(...boxes.map((b) => b.x + b.w));
    const y0 = Math.min(...boxes.map((b) => b.y)), y1 = Math.max(...boxes.map((b) => b.y + b.h));
    const z0 = Math.min(...boxes.map((b) => b.z)), z1 = Math.max(...boxes.map((b) => b.z + b.d));
    this.frameBox({ x: x0, y: y0, z: z0, w: x1 - x0, h: y1 - y0, d: z1 - z0 }, instant, fill ?? (boxes.length === 1 ? 0.55 : 0.8));
  }

  flyTo(id: string, instant = false): void {
    const n = this.model?.tree.nodes.get(id);
    if (n) this.frameBox(n.box, instant, 0.55);
  }

  /** Keep a node inside the inner 80% of the viewport; never re-frame when it already is. */
  follow(id: string): void {
    const n = this.model?.tree.nodes.get(id);
    if (!n) return;
    const c = this.worldCenter(n.box).project(this.camera);
    if (Math.abs(c.x) > 0.8 || Math.abs(c.y) > 0.8) this.frameBox(n.box, false, -1);
  }

  /** A ground ring around a step node too small to read: its projection is >= STEP_RING_PX tall. */
  private ringFor(id: string, topOf?: Map<string, number>): THREE.Vector3[] | null {
    const n = this.model?.tree.nodes.get(id);
    if (!n) return null;
    const b = n.box;
    const el = this.renderer.domElement;
    const H = el.clientHeight || 1;
    const c = new THREE.Vector3(b.x + b.w / 2, (topOf?.get(id) ?? b.z + b.d) + 0.04, b.y + b.h / 2);
    const proj = (v: THREE.Vector3): number => ((1 - v.clone().project(this.camera).y) / 2) * H;
    const own = Math.abs(proj(new THREE.Vector3(b.x, c.y, b.y + b.h)) - proj(new THREE.Vector3(b.x + b.w, c.y, b.y)));
    if (own >= STEP_MIN_PX) return null;
    // the projected height of a unit ground circle, measured, gives the radius for STEP_RING_PX
    const ys = Array.from({ length: 16 }, (_, i) => {
      const k = (i / 16) * Math.PI * 2;
      return proj(c.clone().add(new THREE.Vector3(Math.cos(k), 0, Math.sin(k))));
    });
    const unit = Math.max(...ys) - Math.min(...ys); // the projected height of a unit ground circle
    const r = STEP_RING_PX / Math.max(unit, 1e-6);
    return Array.from({ length: 32 }, (_, i) => {
      const a = (i / 32) * Math.PI * 2;
      return new THREE.Vector3(c.x + Math.cos(a) * r, c.y, c.z + Math.sin(a) * r);
    });
  }

  /** Screen box (canvas px) of the visible representatives of `ids`: all 8 corners of each box.
   *  With `highlight`, a step drawn with a ring counts the ring (what the user actually sees). */
  screenBox(ids: string[], highlight = false): { x0: number; y0: number; x1: number; y1: number; inside: number } | null {
    const m = this.model;
    if (!m) return null;
    const reps = [...new Set(ids.map(this.rep).filter((x): x is string => x !== null))];
    if (!reps.length) return null;
    const el = this.renderer.domElement;
    const W = el.clientWidth || 1, H = el.clientHeight || 1;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const add = (v: THREE.Vector3): void => {
      const p = v.clone().project(this.camera);
      const sx = ((p.x + 1) / 2) * W, sy = ((1 - p.y) / 2) * H;
      x0 = Math.min(x0, sx); y0 = Math.min(y0, sy); x1 = Math.max(x1, sx); y1 = Math.max(y1, sy);
    };
    for (const id of reps) {
      const b = m.tree.nodes.get(id)!.box;
      for (const x of [b.x, b.x + b.w]) for (const y of [b.z, b.z + b.d]) for (const z of [b.y, b.y + b.h]) add(new THREE.Vector3(x, y, z));
      if (highlight) for (const v of this.ringFor(id) ?? []) add(v);
    }
    const area = Math.max(1e-6, (x1 - x0) * (y1 - y0));
    const ix = Math.max(0, Math.min(x1, W) - Math.max(x0, 0)), iy = Math.max(0, Math.min(y1, H) - Math.max(y0, 0));
    return { x0, y0, x1, y1, inside: Math.min(1, (ix * iy) / area) };
  }

  /**
   * P6.1 replay camera (ADR-0050). Frame a replay step (or a path) so it is on screen and readable:
   * - larger than 80% of the viewport, or more than 10% off-screen: fit it (zooming out if needed);
   * - smaller than the 40 px label LOD on its smaller side: zoom in until it reaches it, but never
   *   so far that the step's parent container stops fitting (its siblings matter); a step that still
   *   stays below label size is drawn with a readable ring (ringFor);
   * - otherwise: pan only, and only when it leaves the inner 80% (as `follow`).
   */
  frameStep(ids: string[], instant = false): void {
    const m = this.model;
    const b = this.screenBox(ids);
    if (!m || !b) return;
    const el = this.renderer.domElement;
    const W = el.clientWidth || 1, H = el.clientHeight || 1;
    const w = b.x1 - b.x0, h = b.y1 - b.y0;
    const reps = [...new Set(ids.map(this.rep).filter((x): x is string => x !== null))];
    if (w > 0.8 * W || h > 0.8 * H || b.inside < STEP_MIN_INSIDE) {
      this.fit(reps, instant || this.reducedMotion, 0.7);
      return;
    }
    const small = Math.min(w, h);
    if (small < STEP_MIN_PX) {
      let f = STEP_MIN_PX / Math.max(small, 1);
      f = Math.min(f, (0.8 * W) / Math.max(w, 1), (0.8 * H) / Math.max(h, 1));
      const parents = [...new Set(reps.map((r) => m.tree.parent(r)).filter((p): p is string => p !== null))];
      const pb = parents.length ? this.screenBox(parents) : null;
      if (pb) f = Math.min(f, W / Math.max(pb.x1 - pb.x0, 1), H / Math.max(pb.y1 - pb.y0, 1));
      if (f > 1.01) {
        const to = this.groundUnder((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2);
        this.flyTo3(to, Math.min(400, this.camera.zoom * f), instant || this.reducedMotion);
        return;
      }
    }
    const cx = (b.x0 + b.x1) / 2 / W, cy = (b.y0 + b.y1) / 2 / H;
    if (cx < 0.1 || cx > 0.9 || cy < 0.1 || cy > 0.9) {
      this.flyTo3(this.groundUnder((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2), this.camera.zoom, instant || this.reducedMotion);
    }
  }

  /** The camera target that puts the canvas point (sx, sy) at the center, at the current height. */
  private groundUnder(sx: number, sy: number): THREE.Vector3 {
    const r = this.renderer.domElement.getBoundingClientRect();
    const p = this.groundAt(r.left + sx, r.top + sy);
    const c = this.groundAt(r.left + r.width / 2, r.top + r.height / 2);
    return this.target.clone().add(p.sub(c));
  }

  private flyTo3(to: THREE.Vector3, zoom: number, instant: boolean): void {
    if (instant) {
      this.target.copy(to);
      this.camera.zoom = zoom;
      this.updateCamera();
      return;
    }
    this.flight = { from: this.target.clone(), to, z0: this.camera.zoom, z1: zoom, t0: performance.now(), ms: 450 };
  }

  screenOf(id: string): { x: number; y: number } | null {
    const n = this.model?.tree.nodes.get(id);
    if (!n) return null;
    const p = this.worldCenter(n.box).project(this.camera);
    const el = this.renderer.domElement;
    return { x: ((p.x + 1) / 2) * el.clientWidth, y: ((1 - p.y) / 2) * el.clientHeight };
  }

  // -- camera ----------------------------------------------------------------------------------
  private worldCenter(b: Box, top = true): THREE.Vector3 {
    return new THREE.Vector3(b.x + b.w / 2, top ? b.z + b.d : b.z, b.y + b.h / 2);
  }

  private frameBox(b: Box, instant: boolean, fill: number): void {
    const el = this.renderer.domElement;
    const aspect = (el.clientWidth || 1) / (el.clientHeight || 1);
    const to = new THREE.Vector3(b.x + b.w / 2, b.z + b.d / 2, b.y + b.h / 2);
    let zoom = this.camera.zoom;
    if (fill > 0) {
      // exact: project the box's corners with the camera at zoom 1 centred on the box
      const cam = this.camera.clone();
      cam.zoom = 1;
      cam.left = (-VIEW_H * aspect) / 2;
      cam.right = (VIEW_H * aspect) / 2;
      cam.top = VIEW_H / 2;
      cam.bottom = -VIEW_H / 2;
      cam.position.copy(to).addScaledVector(ISO, this.camDist);
      cam.lookAt(to);
      cam.updateProjectionMatrix();
      cam.updateMatrixWorld();
      let ex = 0, ey = 0;
      for (const x of [b.x, b.x + b.w]) for (const y of [b.z, b.z + b.d]) for (const z of [b.y, b.y + b.h]) {
        const p = new THREE.Vector3(x, y, z).project(cam);
        ex = Math.max(ex, Math.abs(p.x));
        ey = Math.max(ey, Math.abs(p.y));
      }
      zoom = Math.min(400, Math.max(this.minZoom, fill / Math.max(ex, ey, 1e-6)));
    }
    if (instant || this.reducedMotion) {
      this.target.copy(to);
      this.camera.zoom = zoom;
      this.updateCamera();
      return;
    }
    this.flight = { from: this.target.clone(), to, z0: this.camera.zoom, z1: zoom, t0: performance.now(), ms: 450 };
  }

  private updateCamera(): void {
    const el = this.renderer.domElement;
    const aspect = (el.clientWidth || 1) / (el.clientHeight || 1);
    this.camera.left = (-VIEW_H * aspect) / 2;
    this.camera.right = (VIEW_H * aspect) / 2;
    this.camera.top = VIEW_H / 2;
    this.camera.bottom = -VIEW_H / 2;
    this.camera.position.copy(this.target).addScaledVector(ISO, this.camDist);
    this.camera.lookAt(this.target);
    this.camera.updateProjectionMatrix();
    this.dirty = true;
    this.movedAt = performance.now();
    this.on.view();
  }

  private resize(): void {
    const el = this.container;
    this.renderer.setSize(el.clientWidth, el.clientHeight, true);
    this.updateCamera();
  }

  /** The ground-plane point (y = 0) under a screen position. */
  private groundAt(clientX: number, clientY: number): THREE.Vector3 {
    const el = this.renderer.domElement;
    const r = el.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, this.camera);
    const p = new THREE.Vector3();
    ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), p);
    return p;
  }

  zoomAt(clientX: number, clientY: number, factor: number): void {
    const before = this.groundAt(clientX, clientY);
    this.camera.zoom = Math.min(400, Math.max(this.minZoom, this.camera.zoom * factor));
    this.updateCamera();
    const after = this.groundAt(clientX, clientY);
    this.target.add(before.sub(after));
    this.updateCamera();
  }

  panBy(dxPx: number, dyPx: number): void {
    const el = this.renderer.domElement;
    const r = el.getBoundingClientRect();
    const a = this.groundAt(r.left + r.width / 2, r.top + r.height / 2);
    const b = this.groundAt(r.left + r.width / 2 + dxPx, r.top + r.height / 2 + dyPx);
    this.target.sub(b.sub(a));
    this.updateCamera();
  }

  private bindInput(): void {
    const el = this.renderer.domElement;
    el.tabIndex = 0;
    let drag: { x: number; y: number; moved: boolean } | null = null;
    el.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.flight = null;
      this.zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.0015));
    }, { passive: false });
    el.addEventListener("pointerdown", (e) => {
      drag = { x: e.clientX, y: e.clientY, moved: false };
      el.setPointerCapture(e.pointerId);
    });
    el.addEventListener("pointermove", (e) => {
      if (drag) {
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
        if (drag.moved) {
          this.flight = null;
          this.panBy(-dx, -dy);
          drag.x = e.clientX;
          drag.y = e.clientY;
        }
        return;
      }
      const id = this.pick(e.clientX, e.clientY);
      this.on.hover(id, e.clientX, e.clientY);
    });
    el.addEventListener("pointerup", (e) => {
      if (drag && !drag.moved) this.on.click(this.pick(e.clientX, e.clientY));
      drag = null;
    });
    el.addEventListener("pointerleave", () => this.on.hover(null, 0, 0));
    el.addEventListener("dblclick", (e) => this.on.dblclick(this.pick(e.clientX, e.clientY)));
  }

  pick(clientX: number, clientY: number): string | null {
    const el = this.renderer.domElement;
    const r = el.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, this.camera);
    const hits = ray.intersectObjects([...this.meshes.values()], false);
    let best: { id: string; depth: number } | null = null;
    for (const h of hits) {
      const ids = this.instanceIds.get(h.object as THREE.InstancedMesh);
      const id = h.instanceId !== undefined ? ids?.[h.instanceId] : undefined;
      if (!id) continue;
      const depth = this.model!.tree.nodes.get(id)!.depth;
      if (!best || depth > best.depth) best = { id, depth }; // the innermost glyph under the cursor
      if (hits.indexOf(h) > 6) break;
    }
    return best?.id ?? null;
  }

  // -- frame -----------------------------------------------------------------------------------
  private frame(t: number): void {
    if (this.flight) {
      const f = this.flight;
      const k = Math.min(1, (t - f.t0) / f.ms);
      const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      this.target.lerpVectors(f.from, f.to, e);
      this.camera.zoom = f.z0 * Math.pow(f.z1 / f.z0, e);
      this.updateCamera();
      if (k >= 1) this.flight = null;
    }
    const animating = this.replay !== null && !this.reducedMotion;
    if (animating) this.dashT += 0.6;
    if (this.dirty) this.rebuildIfNeeded();
    else if (this.movedAt && t - this.movedAt > 150) {
      this.movedAt = 0;
      if (this.model) this.rebuild(); // settled: redo label collisions and culled labels
    }
    const el = this.renderer.domElement;
    const ppu = this.pxPerUnit();
    for (const r of [this.outlines, this.emphasis, this.edgeSet]) r.update(el.clientWidth, el.clientHeight, ppu);
    this.overlaySet.update(el.clientWidth, el.clientHeight, ppu, animating ? -this.dashT : 0);
    this.billboards.update(el.clientWidth, el.clientHeight);
    this.placePortals();
    const t0 = performance.now();
    this.renderer.render(this.scene, this.camera);
    this.frames.push(t);
    while (this.frames.length > 1 && t - this.frames[0]! > 1000) this.frames.shift();
    this.perf.fps = this.frames.length > 1 ? ((this.frames.length - 1) * 1000) / (t - this.frames[0]!) : 0;
    this.perf.frameMs = performance.now() - t0;
    this.perf.drawCalls = this.renderer.info.render.calls;
    this.perf.triangles = this.renderer.info.render.triangles;
    this.perf.visibleNodes = this.lods.size;
    this.dirty = false;
  }

  private pxOf = (b: Box): number => {
    const el = this.renderer.domElement;
    const c = this.worldCenter(b, false).project(this.camera);
    const px = Math.max(b.w, b.h) * this.pxPerUnit() * FOOTPRINT;
    const mx = px / (el.clientWidth || 1), my = px / (el.clientHeight || 1);
    if (c.x < -1 - mx || c.x > 1 + mx || c.y < -1 - my * 2 || c.y > 1 + my * 2) return 0; // culled
    return px;
  };

  private rebuildIfNeeded(): void {
    const m = this.model;
    if (!m) return;
    const lods = m.tree.visible(this.pxOf, this.lods);
    const key = [...lods].map(([id, l]) => id.slice(2, 8) + l).join("");
    const same = key === this.visKey;
    this.lods = lods;
    if (!same) {
      this.visKey = key;
      this.rebuild();
    }
  }

  private rebuild(): void {
    const m = this.model!;
    const th = this.theme;
    const perShape = new Map<BaseShape, string[]>();
    for (const id of this.lods.keys()) {
      const g = m.tree.nodes.get(id)!.glyph;
      const shape = (g?.baseShape ?? "rounded_box") as BaseShape;
      const list = perShape.get(shape) ?? [];
      list.push(id);
      perShape.set(shape, list);
    }
    const mat = new THREE.Matrix4();
    const col = new THREE.Color();
    const keep = this.keepFn();
    this.dimSet = keep === null ? null : new Set([...this.lods.keys()].filter((id) => !keep(id)));
    const dim = (id: string): boolean => this.isDimmed(id);
    const lines: Polyline[] = [];
    const glow: Polyline[] = [];
    const bills: Billboard[] = [];
    const topOf = new Map<string, number>();
    for (const [shape, mesh] of this.meshes) {
      const ids = perShape.get(shape) ?? [];
      if (mesh.instanceMatrix.count < ids.length) {
        const grown = new THREE.InstancedMesh(mesh.geometry, mesh.material, Math.max(ids.length, 64));
        grown.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        grown.frustumCulled = false;
        this.scene.remove(mesh);
        this.scene.add(grown);
        this.meshes.set(shape, grown);
      }
      const im = this.meshes.get(shape)!;
      ids.forEach((id, i) => {
        const n = m.tree.nodes.get(id)!;
        const b = n.box;
        const lod = this.lods.get(id)!;
        const open = lod === Lod.Open && n.children.length > 0;
        const closedH = n.children.length ? b.d + Math.min(2.5, Math.max(0.3, Math.min(b.w, b.h) * 0.12)) : b.d;
        const h = open ? b.d : closedH;
        topOf.set(id, b.z + h);
        mat.compose(
          new THREE.Vector3(b.x + b.w / 2, b.z, b.y + b.h / 2),
          new THREE.Quaternion(),
          new THREE.Vector3(b.w, h, b.h),
        );
        im.setMatrixAt(i, mat);
        const st = m.status.get(id);
        const status = st?.status ?? "none";
        // a neutral body with a light status tint: the outline carries the status (visual tokens §1)
        col.copy(bodyColor(th, status, open));
        if (dim(id)) col.copy(dimmed(th, col));
        im.setColorAt(i, col);
      });
      im.count = ids.length;
      im.instanceMatrix.needsUpdate = true;
      if (im.instanceColor) im.instanceColor.needsUpdate = true;
      this.instanceIds.set(im, ids);
    }
    // status outlines, emphasis, badges, labels
    const glowColor = new THREE.Color(th.emphasis.color);
    for (const [id, lod] of this.lods) {
      const n = m.tree.nodes.get(id)!;
      const b = n.box;
      const st = m.status.get(id);
      const status = st?.status ?? "none";
      const y = (topOf.get(id) ?? b.z + b.d) + 0.02;
      const pts = outline(n.glyph?.baseShape ?? "rounded_box").map(
        ([px, pz]) => new THREE.Vector3(b.x + b.w / 2 + px * b.w, y, b.y + b.h / 2 + pz * b.h),
      );
      const r = outlineFor(th, this.themeName, status, lod >= Lod.Detail);
      const dm = dim(id);
      lines.push({ points: pts, closed: true, color: dm ? dimmed(th, r.color) : new THREE.Color(r.color), widthPx: r.widthPx, style: r.line });
      if (r.emphasis && !dm) {
        glow.push({ points: pts, closed: true, color: glowColor, widthPx: r.emphasis.widthPx, style: "solid", alpha: r.emphasis.alpha });
      }
      if (id === this.selection) {
        lines.push({ points: pts, closed: true, color: new THREE.Color(th.text), widthPx: 4.5, style: "solid", alpha: 0.9 });
      }
      const anchor = this.anchorOf(id, y);
      const badges: string[] = [];
      if (lod >= Lod.Silhouette) {
        if (r.badge) badges.push(badgeKey(r.badge.glyph, r.badge.bg, r.badge.fg, r.badge.shape));
        if (m.effective && st?.provenance === "llm") badges.push(badgeKey("AI", token(th, "badge.ai"), token(th, "badge.ai_text")));
        if (m.showSuggestions && m.suggestionNodes.has(id))
          badges.push(badgeKey("?", token(th, "badge.suggestion"), token(th, "badge.suggestion_text")));
        const d = m.diff?.get(id);
        if (d && d.cls !== "unchanged") {
          const key = d.cls === "added" ? "diff_added" : d.cls === "renamed" ? "diff_renamed" : "diff_transition";
          const ov = OVERLAY_BADGES[key]!;
          const glyph = d.cls === "transition" ? `${d.from}→${d.to}` : ov.glyph;
          badges.push(badgeKey(glyph, token(th, ov.color), token(th, ov.text)));
          if (d.cls === "added")
            lines.push({ points: pts, closed: true, color: new THREE.Color(token(th, "diff.added")), widthPx: 4, style: "solid", alpha: 0.85 });
        }
      }
      if (lod === Lod.Detail || (lod === Lod.Open && !n.children.length)) {
        // modifiers roll up (glyph grammar §4): an open glyph shows them on its children instead
        const mod = n.glyph?.modifiers;
        if (mod?.has_loop_risk) badges.push(badgeKey("⟳", th.severity_ramp[3]!, th.background));
        if (mod?.has_llm) badges.push(badgeKey("⬡", th.text_muted, th.background));
        if (mod?.external) badges.push(badgeKey("☁", th.text_muted, th.background));
        if (mod && mod.replicas > 1) badges.push(badgeKey(`×${mod.replicas}`, th.surface, th.text));
      }
      const bd = dm ? th.dim.factor : 0;
      badges.forEach((k, i) => bills.push({ key: k, at: anchor, offsetPx: [-10 + i * 30, 6], scale: 1, dim: bd }));
      if (lod === Lod.Silhouette && n.children.length) {
        const r = m.rollups.get(id);
        const key = r ? rollupKey(r, th) : null;
        if (key) bills.push({ key, at: anchor, offsetPx: [0, -14], scale: 1, dim: bd });
      }
    }
    this.outlines.set(lines);
    // dark: additive glow (bloom); light: a normal-blended halo (visual tokens §3–4)
    this.emphasis.material.blending = th.emphasis.kind === "glow" ? THREE.AdditiveBlending : THREE.NormalBlending;
    this.emphasis.set(glow);
    this.buildEdges(topOf);
    this.buildOverlay(topOf);
    bills.push(...this.labels(topOf));
    this.buildGhosts(bills);
    this.billboards.set(bills);
  }

  private labels(topOf: Map<string, number>): Billboard[] {
    const m = this.model!;
    const el = this.renderer.domElement;
    const W = el.clientWidth, H = el.clientHeight;
    const cand = [...this.lods]
      .filter(([id, l]) => l >= Lod.Detail || (l === Lod.Silhouette && m.tree.nodes.get(id)!.depth <= 1))
      .map(([id]) => id)
      .sort((a, b) => {
        const A = m.tree.nodes.get(a)!.box, B = m.tree.nodes.get(b)!.box;
        return B.w * B.h - A.w * A.h || (a < b ? -1 : 1);
      });
    // P7 (ADR-0061): greedy by priority (problem statuses > ports > footprint > name), screen-space
    // collision rejection, and hysteresis for labels that were shown last time
    const ppu = this.pxPerUnit();
    const cands: LabelCand[] = [];
    const where = new Map<string, { at: THREE.Vector3; text: string }>();
    for (const id of cand) {
      const n = m.tree.nodes.get(id)!;
      const text = m.label(id);
      const at = this.anchorOf(id, topOf.get(id) ?? n.box.z + n.box.d);
      const p = at.clone().project(this.camera);
      const sx = ((p.x + 1) / 2) * W, sy = ((1 - p.y) / 2) * H - 18;
      const w = Math.min(48, text.length) * 6.4 + 8, h = 16;
      const rect: [number, number, number, number] = [sx - w / 2, sy - h, sx + w / 2, sy];
      if (rect[2] < 0 || rect[0] > W || rect[3] < 0 || rect[1] > H) continue;
      const status = m.status.get(id)?.status ?? "none";
      cands.push({ id, rect, priority: labelPriority(status, PORT_KINDS.has(n.row.kind)), area: n.box.w * n.box.h * ppu * ppu, name: text });
      where.set(id, { at, text });
    }
    const placed = placeLabels(cands, this.prevLabels, 400);
    this.prevLabels = new Set(placed);
    return placed.map((id) => {
      const { at, text } = where.get(id)!;
      return { key: `label:${text}`, at, offsetPx: [0, 18] as [number, number], scale: 1, dim: this.isDimmed(id) ? this.theme.dim.factor : 0 };
    });
  }

  /** Where a node's label and badges go: its top centre, or the front-left corner of an open slab. */
  private anchorOf(id: string, y: number): THREE.Vector3 {
    const n = this.model!.tree.nodes.get(id)!;
    const b = n.box;
    if (this.lods.get(id) === Lod.Open && n.children.length) return new THREE.Vector3(b.x + 0.6, y, b.y + b.h - 0.3);
    return new THREE.Vector3(b.x + b.w / 2, y, b.y + b.h / 2);
  }

  private rep = (id: string): string | null => this.model!.tree.representative(id, this.lods);

  /** The visible node that stands for `id` at the current LOD (itself, or its nearest visible ancestor). */
  representative(id: string): string | null {
    return this.model ? this.rep(id) : null;
  }

  private arc(a: THREE.Vector3, b: THREE.Vector3, lift: number): THREE.Vector3[] {
    const pts: THREE.Vector3[] = [];
    const d = a.distanceTo(b);
    const peak = Math.max(a.y, b.y) + Math.min(12, 0.25 * d) * lift + 0.3;
    for (let i = 0; i <= 14; i++) {
      const t = i / 14;
      const p = new THREE.Vector3().lerpVectors(a, b, t);
      p.y = (1 - t) * (1 - t) * a.y + 2 * (1 - t) * t * peak + t * t * b.y;
      pts.push(p);
    }
    return pts;
  }

  private topCenter(id: string, topOf: Map<string, number>): THREE.Vector3 {
    const b = this.model!.tree.nodes.get(id)!.box;
    return new THREE.Vector3(b.x + b.w / 2, topOf.get(id) ?? b.z + b.d, b.y + b.h / 2);
  }

  private insideFocus(id: string): boolean {
    if (this.focus === null) return false;
    return id === this.focus || this.model!.tree.ancestors(id).includes(this.focus);
  }

  private buildEdges(topOf: Map<string, number>): void {
    const m = this.model!;
    const th = this.theme;
    let agg: AggEdge[] = aggregateEdges(m.edges, this.rep, this.edgeGroups);
    if (this.edgeMode === "aggregated") {
      // below the label LOD a representative is lifted to its visible parent: one ribbon per parent pair
      agg = liftEdges(agg, (id) => {
        const p = m.tree.nodes.get(id)?.row.parentId ?? null;
        return (this.lods.get(id) ?? Lod.Open) < Lod.Detail && p !== null && this.lods.has(p) ? p : id;
      });
    }
    const touching = new Set<string>();
    for (const t of [this.selection, this.hoverId]) {
      if (t === null) continue;
      touching.add(t);
      const r = this.rep(t);
      if (r !== null) touching.add(r);
    }
    for (const id of this.emph ?? []) touching.add(this.rep(id) ?? id);
    const dc = declutterEdges(agg, this.edgeMode, touching, this.edgeLimit);
    this.edgeStats = { visible: dc.edges.length, hidden: dc.hidden, limited: dc.limited };
    agg = dc.edges;
    const portalsIn: PortalIn[] = [];
    const lines: Polyline[] = [];
    const edgeColor = new THREE.Color(th.edge);
    const edgeDim = dimmed(th, th.edge);
    const colorOf = (s: string, d: string): THREE.Color => (this.isDimmed(s) || this.isDimmed(d) ? edgeDim : edgeColor);
    for (const p of this.portals) p.el.remove();
    this.portals = [];
    const focusBox = this.focus !== null ? m.tree.nodes.get(this.focus)?.box : undefined;
    for (const e of agg) {
      const a = this.topCenter(e.src, topOf), b = this.topCenter(e.dst, topOf);
      const width = Math.min(6, 1 + Math.log2(1 + e.weight) * 0.7);
      const inA = this.insideFocus(e.src), inB = this.insideFocus(e.dst);
      if (focusBox && this.lods.get(this.focus!) === Lod.Open && inA !== inB) {
        // a portal: the edge ends at a labeled stub on the focused container's wall
        const inner = inA ? a : b, outer = inA ? b : a, dest = inA ? e.dst : e.src;
        const wall = wallPoint(focusBox, inner, outer);
        lines.push({ points: this.arc(inner, wall, 0.6), closed: false, color: colorOf(e.src, e.dst), widthPx: width, style: EDGE_STYLE[e.group], alpha: 0.9 });
        portalsIn.push({ dest, label: m.label(dest), side: wallSide(focusBox, wall), at: [wall.x, wall.y, wall.z] });
        continue;
      }
      if (focusBox && !inA && !inB && this.lods.get(this.focus!) === Lod.Open) continue; // outside the room
      lines.push({ points: this.arc(a, b, 1), closed: false, color: colorOf(e.src, e.dst), widthPx: width, style: EDGE_STYLE[e.group], alpha: 0.75 });
    }
    this.edgeSet.set(lines);
    // P7: one chip per destination ("→ api ×3"), stacked per wall side
    for (const p of mergePortals(portalsIn)) this.addPortal(new THREE.Vector3(...p.at), p.dest, p.text, p.side, p.stack, p.count);
  }

  private addPortal(at: THREE.Vector3, dest: string, text: string, side: WallSide, stack: number, count: number): void {
    const el = document.createElement("button");
    el.className = "portal";
    el.textContent = text;
    el.dataset.count = String(count);
    el.title = `${count > 1 ? `${count} edges leave` : "Leaves"} this container. Click to fly to ${this.model!.label(dest)}`;
    el.addEventListener("click", (ev) => {
      ev.stopPropagation();
      this.on.portal(dest);
    });
    this.container.appendChild(el);
    this.portals.push({ el, at, side, stack });
  }

  private placePortals(): void {
    const el = this.renderer.domElement;
    for (const p of this.portals) {
      const s = p.at.clone().project(this.camera);
      p.el.style.left = `${((s.x + 1) / 2) * el.clientWidth}px`;
      p.el.style.top = `${((1 - s.y) / 2) * el.clientHeight + p.stack * 22}px`; // stacked per wall side
    }
  }

  private buildOverlay(topOf: Map<string, number>): void {
    const m = this.model!;
    const th = this.theme;
    const lines: Polyline[] = [];
    const pair = (s: string, c: string, color: string, style: LineStyle, w: number): void => {
      const rs = this.rep(s), rc = this.rep(c);
      if (rs === null || rc === null || rs === rc) return;
      const lc = this.isDimmed(rs) || this.isDimmed(rc) ? dimmed(th, color) : new THREE.Color(color);
      lines.push({ points: this.arc(this.topCenter(rs, topOf), this.topCenter(rc, topOf), 1.4), closed: false, color: lc, widthPx: w, style });
    };
    if (m.showSuggestions) for (const [s, c] of m.suggestionPairs) pair(s, c, token(th, "link.suggestion"), "dotted", 2.4);
    for (const l of m.links)
      pair(l.spec, l.code, token(th, l.kind === "normative" ? "link.normative" : "link.suggestion"), l.kind === "normative" ? "solid" : "dashed", 2.6);
    if (this.replay) {
      const hi = new THREE.Color(th.replay.highlight); // >= 3:1 on dimmed and undimmed neighbors (ADR-0051)
      const path = (this.replay.path ?? []).map(this.rep).filter((x): x is string => x !== null);
      const cur = [...new Set([...this.replay.nodes.map(this.rep).filter((x): x is string => x !== null), ...path])];
      const prev = [...new Set(this.replay.prev.map(this.rep).filter((x): x is string => x !== null))];
      for (let i = 1; i < path.length; i++)
        if (path[i] !== path[i - 1])
          lines.push({ points: this.arc(this.topCenter(path[i - 1]!, topOf), this.topCenter(path[i]!, topOf), 1.2), closed: false, color: hi, widthPx: 4, style: "dashed" });
      for (const id of cur) {
        const b = m.tree.nodes.get(id)!.box;
        const y = (topOf.get(id) ?? b.z + b.d) + 0.04;
        const pts = outline(m.tree.nodes.get(id)!.glyph?.baseShape ?? "rounded_box").map(
          ([px, pz]) => new THREE.Vector3(b.x + b.w / 2 + px * b.w * 1.08, y, b.y + b.h / 2 + pz * b.h * 1.08),
        );
        lines.push({ points: pts, closed: true, color: hi, widthPx: 5, style: "solid" });
        const ring = this.ringFor(id, topOf);  // a step below label size gets a readable ring (P6.1)
        if (ring) lines.push({ points: ring, closed: true, color: hi, widthPx: 3, style: "solid" });
      }
      if (prev.length && cur.length && prev[0] !== cur[0])
        lines.push({ points: this.arc(this.topCenter(prev[0]!, topOf), this.topCenter(cur[0]!, topOf), 1.2), closed: false, color: hi, widthPx: 4, style: "dashed" });
    }
    this.overlaySet.set(lines);
  }

  private buildGhosts(bills: Billboard[]): void {
    const m = this.model!;
    const ghosts = m.ghosts;
    const cap = Math.max(1, ghosts.length);
    if (this.ghostMesh.instanceMatrix.count < cap) {
      const g = new THREE.InstancedMesh(this.ghostMesh.geometry, this.ghostMesh.material, cap);
      g.frustumCulled = false;
      this.scene.remove(this.ghostMesh);
      this.ghostMesh = g;
      this.scene.add(g);
    }
    const mat = new THREE.Matrix4();
    const color = new THREE.Color(token(this.theme, "diff.removed"));
    (this.ghostMesh.material as THREE.MeshBasicMaterial).color = color;
    (this.ghostMesh.material as THREE.MeshBasicMaterial).opacity = Number(this.theme.diff.ghost_opacity);
    ghosts.forEach((gh, i) => {
      const b = gh.box;
      mat.compose(new THREE.Vector3(b.x + b.w / 2, b.z, b.y + b.h / 2), new THREE.Quaternion(), new THREE.Vector3(b.w, Math.max(b.d, 0.3), b.h));
      this.ghostMesh.setMatrixAt(i, mat);
      const ov = OVERLAY_BADGES.diff_removed!;
      bills.push({
        key: badgeKey(ov.glyph, token(this.theme, ov.color), token(this.theme, ov.text)),
        at: new THREE.Vector3(b.x + b.w / 2, b.z + Math.max(b.d, 0.3), b.y + b.h / 2),
        offsetPx: [0, 6],
      });
    });
    this.ghostMesh.count = ghosts.length;
    this.ghostMesh.instanceMatrix.needsUpdate = true;
  }

  private applyTheme(): void {
    this.scene.background = new THREE.Color(this.theme.background);
    this.renderer.setClearColor(this.theme.background);
    this.billboards?.setBackground(this.theme.background); // labels dim toward it (P6.1)
  }
}

function wallSide(b: Box, p: THREE.Vector3): WallSide {
  const dx = (p.x - (b.x + b.w / 2)) / (b.w || 1), dz = (p.z - (b.y + b.h / 2)) / (b.h || 1);
  return Math.abs(dx) >= Math.abs(dz) ? (dx >= 0 ? "e" : "w") : dz >= 0 ? "s" : "n";
}

function wallPoint(b: Box, inner: THREE.Vector3, outer: THREE.Vector3): THREE.Vector3 {
  const cx = b.x + b.w / 2, cz = b.y + b.h / 2;
  const dx = outer.x - cx, dz = outer.z - cz;
  const s = Math.min(Math.abs(b.w / 2 / (dx || 1e-6)), Math.abs(b.h / 2 / (dz || 1e-6)));
  return new THREE.Vector3(cx + dx * s, inner.y + 0.2, cz + dz * s);
}

function rollupKey(r: Record<string, number>, th: Theme): string | null {
  const order = ["drift", "needs_review", "missing", "orphan", "stale", "verified", "implemented", "specified"];
  const parts = order.filter((s) => (r[s] ?? 0) > 0).map((s) => `${s}:${r[s]}`);
  void th;
  return parts.length ? `rollup:${parts.join(",")}` : null;
}
