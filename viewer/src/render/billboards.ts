// Labels and badges as instanced screen-space quads from one canvas atlas: one draw call for all
// of them. Text uses the browser's system UI font through Canvas 2D, so no font file ships with
// the viewer (no font licensing question; works offline in the single-file demo).
import { truncateWords } from "../model/text";
import * as THREE from "three";

const ATLAS = 2048;
const FONT = "600 22px system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
const PAD = 6;

interface Rect {
  u: number;
  v: number;
  w: number;
  h: number;
}

export interface Billboard {
  key: string; // atlas entry: "label:<text>" | "badge:<glyph>:<bg>:<fg>"
  at: THREE.Vector3; // world anchor
  offsetPx: [number, number]; // from the anchor, px (x right, y up)
  scale?: number; // on-screen size multiplier
  opacity?: number;
  dim?: number; // P6.1: blend toward the background by this factor (opaque "dim the rest")
}

export class Atlas {
  readonly canvas: HTMLCanvasElement;
  readonly ctx: CanvasRenderingContext2D;
  readonly texture: THREE.CanvasTexture;
  private readonly rects = new Map<string, Rect>();
  private x = 0;
  private y = 0;
  private rowH = 0;

  constructor(
    private readonly textColor: () => { text: string; halo: string },
    private readonly statusColor: (status: string) => string = () => "#888",
  ) {
    this.canvas = document.createElement("canvas");
    this.canvas.width = this.canvas.height = ATLAS;
    this.ctx = this.canvas.getContext("2d")!;
    this.texture = new THREE.CanvasTexture(this.canvas);
    this.texture.colorSpace = THREE.SRGBColorSpace;
    this.texture.minFilter = THREE.LinearFilter;
    this.texture.generateMipmaps = false;
  }

  reset(): void {
    this.rects.clear();
    this.ctx.clearRect(0, 0, ATLAS, ATLAS);
    this.x = this.y = this.rowH = 0;
    this.texture.needsUpdate = true;
  }

  private alloc(w: number, h: number): Rect | null {
    if (this.x + w > ATLAS) {
      this.x = 0;
      this.y += this.rowH;
      this.rowH = 0;
    }
    if (this.y + h > ATLAS) return null; // full: the caller resets on the next rebuild
    const r = { u: this.x, v: this.y, w, h };
    this.x += w;
    this.rowH = Math.max(this.rowH, h);
    return r;
  }

  get(key: string): Rect | null {
    const hit = this.rects.get(key);
    if (hit) return hit;
    const c = this.ctx;
    c.font = FONT;
    let r: Rect | null;
    if (key.startsWith("rollup:")) {
      // a stacked bar of the statuses inside a collapsed glyph (a modifier, glyph grammar §7)
      const parts = key.slice(7).split(",").filter(Boolean).map((p) => p.split(":") as [string, string]);
      const total = parts.reduce((s, [, n]) => s + Number(n), 0) || 1;
      r = this.alloc(96, 14);
      if (!r) return null;
      c.fillStyle = this.textColor().halo;
      c.fillRect(r.u, r.v, 96, 14);
      let x = r.u + 2;
      for (const [status, n] of parts) {
        const w = Math.max(3, (92 * Number(n)) / total);
        c.fillStyle = this.statusColor(status);
        c.fillRect(x, r.v + 3, w - 1, 8);
        x += w;
      }
    } else if (key.startsWith("label:")) {
      const text = truncateWords(key.slice(6), 48);
      const w = Math.ceil(c.measureText(text).width) + PAD * 2;
      r = this.alloc(w, 32);
      if (!r) return null;
      const { text: fg, halo } = this.textColor();
      c.lineJoin = "round";
      c.lineWidth = 5;
      c.strokeStyle = halo;
      c.fillStyle = fg;
      c.textBaseline = "middle";
      c.strokeText(text, r.u + PAD, r.v + 16);
      c.fillText(text, r.u + PAD, r.v + 16);
    } else {
      const [, glyph = "?", bg = "#888", fg = "#000", shape = "round"] = key.split("\u0001");
      const tw = Math.ceil(c.measureText(glyph).width);
      const w = Math.max(32, tw + 16);
      r = this.alloc(w, 32);
      if (!r) return null;
      c.fillStyle = bg;
      c.beginPath();
      if (shape === "triangle") {
        c.moveTo(r.u + w / 2, r.v + 2);
        c.lineTo(r.u + w - 2, r.v + 30);
        c.lineTo(r.u + 2, r.v + 30);
      } else c.roundRect(r.u + 2, r.v + 2, w - 4, 28, 14);
      c.fill();
      c.fillStyle = fg;
      c.textAlign = "center";
      c.textBaseline = "middle";
      c.fillText(glyph, r.u + w / 2, r.v + (shape === "triangle" ? 20 : 16));
      c.textAlign = "start";
    }
    this.rects.set(key, r);
    this.texture.needsUpdate = true;
    return r;
  }
}

export function badgeKey(glyph: string, bg: string, fg: string, shape: "round" | "triangle" = "round"): string {
  return ["badge", glyph, bg, fg, shape].join("\u0001");
}

const vert = /* glsl */ `
attribute vec3 anchor;
attribute vec2 offsetPx;
attribute vec2 sizePx;
attribute vec4 uvRect;
attribute float opacity;
attribute float dim;
uniform vec2 viewport;
varying vec2 vUv;
varying float vOpacity;
varying float vDim;
void main() {
  vec4 p = projectionMatrix * modelViewMatrix * vec4(anchor, 1.0);
  vec2 px = (position.xy - vec2(0.5, 0.0)) * sizePx + offsetPx;   // bottom-centre anchored
  p.xy += px / (viewport * 0.5) * p.w;
  p.z -= 0.001 * p.w;
  gl_Position = p;
  vUv = uvRect.xy + position.xy * uvRect.zw;
  vOpacity = opacity;
  vDim = dim;
}`;
const frag = /* glsl */ `
uniform sampler2D atlas;
uniform vec3 background;
varying vec2 vUv;
varying float vOpacity;
varying float vDim;
void main() {
  vec4 c = texture2D(atlas, vUv);
  if (c.a < 0.02) discard;
  gl_FragColor = vec4(mix(c.rgb, background, vDim), c.a * vOpacity);
}`;

export class BillboardSet {
  readonly mesh: THREE.Mesh;
  private readonly material: THREE.ShaderMaterial;

  constructor(private readonly atlas: Atlas, renderOrder = 10) {
    this.material = new THREE.ShaderMaterial({
      vertexShader: vert,
      fragmentShader: frag,
      transparent: true,
      depthTest: false,
      depthWrite: false,
      uniforms: {
        viewport: { value: new THREE.Vector2(1, 1) },
        atlas: { value: atlas.texture },
        background: { value: new THREE.Color(0, 0, 0) },
      },
    });
    this.mesh = new THREE.Mesh(new THREE.InstancedBufferGeometry(), this.material);
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = renderOrder;
  }

  set(items: Billboard[]): void {
    const quad = new THREE.InstancedBufferGeometry();
    quad.setAttribute("position", new THREE.Float32BufferAttribute([0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0], 3));
    quad.setIndex([0, 1, 2, 0, 2, 3]);
    const anchor: number[] = [], off: number[] = [], size: number[] = [], uv: number[] = [], op: number[] = [], dim: number[] = [];
    for (const b of items) {
      const r = this.atlas.get(b.key);
      if (!r) continue;
      const s = (b.scale ?? 1) * 0.5; // atlas is drawn at 2× for crisp text
      anchor.push(b.at.x, b.at.y, b.at.z);
      off.push(b.offsetPx[0], b.offsetPx[1]);
      size.push(r.w * s, r.h * s);
      // flipY: canvas rows go down, texture v goes up
      uv.push(r.u / ATLAS, 1 - (r.v + r.h) / ATLAS, r.w / ATLAS, r.h / ATLAS);
      op.push(b.opacity ?? 1);
      dim.push(b.dim ?? 0);
    }
    quad.setAttribute("anchor", new THREE.InstancedBufferAttribute(new Float32Array(anchor), 3));
    quad.setAttribute("offsetPx", new THREE.InstancedBufferAttribute(new Float32Array(off), 2));
    quad.setAttribute("sizePx", new THREE.InstancedBufferAttribute(new Float32Array(size), 2));
    quad.setAttribute("uvRect", new THREE.InstancedBufferAttribute(new Float32Array(uv), 4));
    quad.setAttribute("opacity", new THREE.InstancedBufferAttribute(new Float32Array(op), 1));
    quad.setAttribute("dim", new THREE.InstancedBufferAttribute(new Float32Array(dim), 1));
    quad.instanceCount = anchor.length / 3;
    this.mesh.geometry.dispose();
    this.mesh.geometry = quad;
  }

  setBackground(color: string): void {
    (this.material.uniforms.background!.value as THREE.Color).set(color);
  }

  update(viewportW: number, viewportH: number): void {
    this.material.uniforms.viewport!.value.set(viewportW, viewportH);
  }
}
