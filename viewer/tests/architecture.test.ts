// P10 (ADR-0079): the Architecture view's helpers. Every infra status has a line style, a theme token
// in both themes, and (for problems) a badge; problems are never color-only.
import { describe, expect, it } from "vitest";
import { INFRA_LINE, infraBadge, KIND_LABEL } from "../src/ui/architecture";
import { THEMES } from "../src/theme";

const STATUSES = ["deployed", "undeployed", "wired", "unwired", "in_use", "infra_orphan", "ambiguous", "unknown"];

describe("architecture view helpers", () => {
  it("styles every infra status, in both themes", () => {
    for (const s of STATUSES) {
      expect(INFRA_LINE[s], s).toBeDefined();
      for (const t of Object.values(THEMES)) {
        const infra = (t as unknown as { infra: Record<string, { stroke: string; fill: string }> }).infra;
        expect(infra[s]?.stroke, s).toMatch(/^#[0-9A-F]{6}$/i);
      }
    }
  });

  it("problems differ by line style, not color alone", () => {
    expect(INFRA_LINE.undeployed).toBe("dashed");
    expect(INFRA_LINE.infra_orphan).toBe("dotted");
    expect(INFRA_LINE.unwired).toBe("dash_dot");
    expect(INFRA_LINE.deployed).toBe("solid");
    expect(new Set(["undeployed", "unwired", "infra_orphan", "ambiguous"].map(infraBadge)).size).toBe(4);
    expect(infraBadge("in_use")).toBe("");
    expect(infraBadge(undefined)).toBe("");
  });

  it("names every element kind the C4 derivation emits", () => {
    for (const k of ["person", "system", "external_system", "deployment_unit", "static_site", "code_container",
      "managed_datastore", "managed_queue", "bucket", "scheduler"]) {
      expect(KIND_LABEL[k], k).toBeTruthy();
    }
  });
});
