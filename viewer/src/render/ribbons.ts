// Screen-space ribbons for everything line-like: status outlines, edges, links, replay trails.
// WebGL lines are 1 px, so a line is a quad strip whose half-width is given in pixels and whose
// dash pattern is evaluated in pixels (the four patterns of the visual tokens stay distinguishable
// at every zoom). One draw call per ribbon set; rebuilt only when the visible set changes.
import * as THREE from "three";
import { DASH_PX, type LineStyle } from "../theme";

const STYLE_ID: Record<LineStyle, number> = { solid: 0, dotted: 1, dashed: 2, dash_dot: 3 };

const vert = /* glsl */ `
attribute vec3 other;      // the other end of this segment
attribute float side;      // -1 | +1
attribute float along;     // distance along the polyline, world units
attribute vec3 color;
attribute float widthPx;
attribute float style;
attribute float alpha;
uniform vec2 viewport;     // px
varying vec3 vColor;
varying float vAlong;
varying float vStyle;
varying float vAlpha;
varying float vSide;
void main() {
  vec4 a = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  vec4 b = projectionMatrix * modelViewMatrix * vec4(other, 1.0);
  vec2 sa = a.xy / a.w * viewport * 0.5;
  vec2 sb = b.xy / b.w * viewport * 0.5;
  vec2 dir = normalize(sb - sa + vec2(1e-6, 0.0));
  vec2 n = vec2(-dir.y, dir.x) * side * widthPx * 0.5;
  a.xy += n / (viewport * 0.5) * a.w;
  gl_Position = a;
  vColor = color; vAlong = along; vStyle = style; vAlpha = alpha; vSide = side;
}`;

const frag = /* glsl */ `
uniform float pxPerUnit;
uniform float dashOffset;
uniform vec4 dotted; uniform vec4 dashed; uniform vec4 dashdot;
uniform float soft;        // 1: soft edges (glow), 0: crisp
varying vec3 vColor;
varying float vAlong;
varying float vStyle;
varying float vAlpha;
varying float vSide;
float pattern(vec4 p, float d) {
  float period = p.x + p.y + p.z + p.w;
  if (period <= 0.0) return 1.0;
  float t = mod(d, period);
  if (t < p.x) return 1.0;
  if (t < p.x + p.y) return 0.0;
  if (t < p.x + p.y + p.z) return 1.0;
  return 0.0;
}
void main() {
  float d = vAlong * pxPerUnit + dashOffset;
  float on = 1.0;
  if (vStyle > 0.5 && vStyle < 1.5) on = pattern(dotted, d);
  else if (vStyle > 1.5 && vStyle < 2.5) on = pattern(dashed, d);
  else if (vStyle > 2.5) on = pattern(dashdot, d);
  if (on < 0.5) discard;
  float a = vAlpha;
  if (soft > 0.5) a *= 1.0 - smoothstep(0.0, 1.0, abs(vSide));
  gl_FragColor = vec4(vColor, a);
}`;

function vec4(p: number[]): THREE.Vector4 {
  return new THREE.Vector4(p[0] ?? 0, p[1] ?? 0, p[2] ?? 0, p[3] ?? 0);
}

export interface Polyline {
  points: THREE.Vector3[];
  closed: boolean;
  color: THREE.Color;
  widthPx: number;
  style: LineStyle;
  alpha?: number;
}

export class RibbonSet {
  readonly mesh: THREE.Mesh;
  readonly material: THREE.ShaderMaterial;

  constructor(opts: { soft?: boolean; additive?: boolean; depthTest?: boolean; renderOrder?: number } = {}) {
    this.material = new THREE.ShaderMaterial({
      vertexShader: vert,
      fragmentShader: frag,
      transparent: true,
      side: THREE.DoubleSide, // winding depends on the screen direction of each segment
      depthTest: opts.depthTest ?? true,
      depthWrite: false,
      blending: opts.additive ? THREE.AdditiveBlending : THREE.NormalBlending,
      uniforms: {
        viewport: { value: new THREE.Vector2(1, 1) },
        pxPerUnit: { value: 1 },
        dashOffset: { value: 0 },
        dotted: { value: vec4(DASH_PX.dotted) },
        dashed: { value: vec4(DASH_PX.dashed) },
        dashdot: { value: vec4(DASH_PX.dash_dot) },
        soft: { value: opts.soft ? 1 : 0 },
      },
    });
    this.mesh = new THREE.Mesh(new THREE.BufferGeometry(), this.material);
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = opts.renderOrder ?? 2;
  }

  set(lines: Polyline[]): void {
    const pos: number[] = [], oth: number[] = [], side: number[] = [], along: number[] = [];
    const col: number[] = [], width: number[] = [], style: number[] = [], alpha: number[] = [];
    const idx: number[] = [];
    let v = 0;
    for (const l of lines) {
      const pts = l.closed ? [...l.points, l.points[0]!] : l.points;
      let dist = 0;
      for (let i = 0; i + 1 < pts.length; i++) {
        const a = pts[i]!, b = pts[i + 1]!;
        const seg = a.distanceTo(b);
        // 4 vertices: a-, a+, b-, b+ ; b's "other" points back to a so the normal flips consistently
        const push = (p: THREE.Vector3, o: THREE.Vector3, s: number, d: number): void => {
          pos.push(p.x, p.y, p.z);
          oth.push(o.x, o.y, o.z);
          side.push(s);
          along.push(d);
          col.push(l.color.r, l.color.g, l.color.b);
          width.push(l.widthPx);
          style.push(STYLE_ID[l.style]);
          alpha.push(l.alpha ?? 1);
        };
        push(a, b, -1, dist);
        push(a, b, 1, dist);
        push(b, a, 1, dist + seg);
        push(b, a, -1, dist + seg);
        idx.push(v, v + 1, v + 3, v, v + 3, v + 2); // quad a-, a+, b+, b-
        v += 4;
        dist += seg;
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute("other", new THREE.Float32BufferAttribute(oth, 3));
    g.setAttribute("side", new THREE.Float32BufferAttribute(side, 1));
    g.setAttribute("along", new THREE.Float32BufferAttribute(along, 1));
    g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
    g.setAttribute("widthPx", new THREE.Float32BufferAttribute(width, 1));
    g.setAttribute("style", new THREE.Float32BufferAttribute(style, 1));
    g.setAttribute("alpha", new THREE.Float32BufferAttribute(alpha, 1));
    g.setIndex(idx);
    this.mesh.geometry.dispose();
    this.mesh.geometry = g;
  }

  update(viewportW: number, viewportH: number, pxPerUnit: number, dashOffset = 0): void {
    this.material.uniforms.viewport!.value.set(viewportW, viewportH);
    this.material.uniforms.pxPerUnit!.value = pxPerUnit;
    this.material.uniforms.dashOffset!.value = dashOffset;
  }
}
