// Unit geometries for the 10 base shapes of the glyph grammar (footprint 1×1, height 1, base at
// y = 0), scaled per instance to the layout box, and the outline polygon each one uses for its
// status line. Low poly on purpose: thousands of instances.
import * as THREE from "three";

export type BaseShape =
  | "rounded_box"
  | "cylinder"
  | "tube"
  | "trapezoid"
  | "hexagon"
  | "diamond"
  | "ring"
  | "port_notch"
  | "folded_sheet"
  | "cloud";

export const BASE_SHAPES: BaseShape[] = [
  "rounded_box",
  "cylinder",
  "tube",
  "trapezoid",
  "hexagon",
  "diamond",
  "ring",
  "port_notch",
  "folded_sheet",
  "cloud",
];

function baseAtZero(g: THREE.BufferGeometry): THREE.BufferGeometry {
  g.computeBoundingBox();
  const b = g.boundingBox!;
  const sx = 1 / Math.max(1e-6, b.max.x - b.min.x);
  const sy = 1 / Math.max(1e-6, b.max.y - b.min.y);
  const sz = 1 / Math.max(1e-6, b.max.z - b.min.z);
  g.translate(-(b.min.x + b.max.x) / 2, -b.min.y, -(b.min.z + b.max.z) / 2);
  g.scale(sx, sy, sz);
  g.computeVertexNormals();
  return g;
}

export function geometry(shape: BaseShape): THREE.BufferGeometry {
  switch (shape) {
    case "rounded_box":
    case "port_notch":
      return baseAtZero(new THREE.BoxGeometry(1, 1, 1));
    case "folded_sheet": {
      // a sheet with its north-east corner folded down
      const s = new THREE.Shape();
      s.moveTo(-0.5, -0.5);
      s.lineTo(0.5, -0.5);
      s.lineTo(0.5, 0.25);
      s.lineTo(0.25, 0.5);
      s.lineTo(-0.5, 0.5);
      s.lineTo(-0.5, -0.5);
      const g = new THREE.ExtrudeGeometry(s, { depth: 1, bevelEnabled: false });
      g.rotateX(-Math.PI / 2);
      return baseAtZero(g);
    }
    case "cylinder":
      return baseAtZero(new THREE.CylinderGeometry(0.5, 0.5, 1, 20));
    case "tube": {
      const g = new THREE.CylinderGeometry(0.5, 0.5, 1, 16);
      g.rotateZ(Math.PI / 2);
      return baseAtZero(g);
    }
    case "trapezoid": {
      const g = new THREE.CylinderGeometry(0.42, 0.62, 1, 4);
      g.rotateY(Math.PI / 4);
      return baseAtZero(g);
    }
    case "hexagon":
      return baseAtZero(new THREE.CylinderGeometry(0.5, 0.5, 1, 6));
    case "diamond": {
      const g = new THREE.OctahedronGeometry(0.5);
      return baseAtZero(g);
    }
    case "ring": {
      const g = new THREE.TorusGeometry(0.36, 0.13, 8, 20);
      g.rotateX(Math.PI / 2);
      return baseAtZero(g);
    }
    case "cloud": {
      const g = new THREE.SphereGeometry(0.5, 10, 6);
      return baseAtZero(g);
    }
  }
}

/** Outline polygon (unit footprint, centred) for the status line. */
export function outline(shape: string): Array<[number, number]> {
  const circle = (n: number, r = 0.5, rot = 0): Array<[number, number]> =>
    Array.from({ length: n }, (_, i) => {
      const a = rot + (i / n) * Math.PI * 2;
      return [Math.cos(a) * r, Math.sin(a) * r] as [number, number];
    });
  switch (shape) {
    case "cylinder":
    case "cloud":
    case "ring":
      return circle(24);
    case "hexagon":
      return circle(6);
    case "diamond":
      return circle(4);
    case "folded_sheet":
      return [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.25], [0.25, 0.5], [-0.5, 0.5]];
    default:
      return [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]];
  }
}
