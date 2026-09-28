// Workflow replay state (P5 §8). The playhead lives on the fine trace: changing the detail level
// re-projects and keeps the playhead inside the coarse step that contains it, so it never jumps.
import type { NarrationRow, StepRow } from "../data/types";
import { coarseIndexOf, levels, type Ancestry, type CoarseStep } from "../model/projection";

export class Replay {
  readonly levels: Array<{ level: number; coarse: CoarseStep[] }>;
  levelIdx = 0;
  playhead: number; // fine step seq

  constructor(
    readonly workflowId: string,
    readonly name: string,
    readonly steps: StepRow[],
    anc: Ancestry,
    readonly narrations: NarrationRow[],
  ) {
    this.levels = levels(steps, anc);
    if (!this.levels.length) this.levels.push({ level: 0, coarse: steps.map((s, i) => ({ seq: i, nodeIds: s.nodeIds, touched: s.nodeIds, span: [s.seq, s.seq] })) });
    this.playhead = steps[0]?.seq ?? 0;
  }

  get level(): number {
    return this.levels[this.levelIdx]!.level;
  }

  get coarse(): CoarseStep[] {
    return this.levels[this.levelIdx]!.coarse;
  }

  get index(): number {
    return coarseIndexOf(this.coarse, this.playhead);
  }

  get current(): CoarseStep {
    return this.coarse[this.index]!;
  }

  get previous(): CoarseStep | null {
    return this.index > 0 ? this.coarse[this.index - 1]! : null;
  }

  get atEnd(): boolean {
    return this.index >= this.coarse.length - 1;
  }

  setLevel(i: number): void {
    this.levelIdx = Math.max(0, Math.min(this.levels.length - 1, i)); // the playhead stays put
  }

  step(delta: number): void {
    const next = Math.max(0, Math.min(this.coarse.length - 1, this.index + delta));
    this.playhead = this.coarse[next]!.span[0];
  }

  /** The narration for the current step, and the enclosing coarser one as a subtitle. */
  narration(): { text: string | null; parent: string | null } {
    const cur = this.current;
    const at = (level: number, span: [number, number]): string | null =>
      this.narrations.find((n) => n.detailLevel === level && n.spanStart <= span[0] && span[1] <= n.spanEnd)?.text ?? null;
    const exact = this.narrations.find((n) => n.detailLevel === this.level && n.spanStart === cur.span[0])?.text ?? null;
    const parentLevel = this.levelIdx > 0 ? this.levels[this.levelIdx - 1]!.level : null;
    return { text: exact, parent: parentLevel === null ? null : at(parentLevel, cur.span) };
  }
}
