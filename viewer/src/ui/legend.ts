// The status legend (P8.1, ADR-0066): every status with its non-color signature and what it means.
// Shown from the toolbar; node cards repeat the meaning of `not_evaluable` with the language.
import { STATUS_STYLES, statusStyle } from "../theme";
import { h } from "./dom";

export const STATUS_MEANINGS: Record<string, string> = {
  drift: "the code contradicts the spec (structure, or the AI judge in effective mode)",
  needs_review: "a pairing ad2v could not decide (ambiguous id, unresolved route path)",
  missing: "a spec endpoint with no implementing route",
  orphan: "code with no spec, once the repository has specs",
  stale: "linked, but the spec changed since code and spec last agreed",
  verified: "implemented and covered by passing tests",
  implemented: "spec and code are paired",
  not_evaluable:
    "specified and written in a language no active extractor reads, so ad2v cannot evaluate it; " +
    "enable an extractor for that language (ad2v extractors list)",
  specified: "in the spec, with no code paired yet",
  none: "no spec coverage applies here",
};

export const LEGEND_ORDER = [
  "drift", "needs_review", "missing", "orphan", "stale", "verified", "implemented", "not_evaluable", "specified", "none",
];

function signature(status: string): string {
  const s = statusStyle(status);
  const bits = [s.line.replace("_", "-") + " line"];
  if (s.fill === "hollow") bits.push("hollow");
  if (s.decoration === "emphasis") bits.push("glow / halo");
  if (s.decoration === "warning_badge") bits.push("! badge");
  if (s.decoration === "clock_badge") bits.push("◷ badge");
  if (s.decoration === "scope_badge") bits.push("∅ badge");
  if (s.weight === "thin") bits.push("thin");
  return bits.join(", ");
}

export function legendPanel(onClose: () => void): HTMLElement {
  const rows = LEGEND_ORDER.filter((s) => s in STATUS_STYLES).map((s) =>
    h("li", { "data-status": s },
      h("span", { class: `chip st-${s}`, "data-line": statusStyle(s).line }, s.replace(/_/g, " ")),
      h("span", { class: "sig" }, ` ${signature(s)}: `),
      STATUS_MEANINGS[s] ?? ""),
  );
  return h("div", { id: "legend", class: "legend", role: "dialog", "aria-label": "status legend" },
    h("div", { class: "legend-head" }, h("strong", {}, "Statuses"),
      h("button", { class: "linkish", id: "legend-close", onclick: onClose }, "close")),
    h("ul", {}, ...rows));
}

/** The sentence a node card shows for a `not_evaluable` node. */
/** P9 (ADR-0070, issue 95): a requirement whose spec component maps to code no extractor reads. */
export function componentOutOfScopeNote(component: string, languages: string[]): string {
  const lang = languages.length ? languages.join(", ") : "a language no active extractor reads";
  return `Not evaluable: its component ${component} is implemented in ${lang}, which no active extractor reads, ` +
    "so ad2v cannot check this requirement against the code. Enable an extractor for it (ad2v extractors list).";
}

export function notEvaluableNote(language: string | undefined): string {
  const lang = language ? `in ${language}, ` : "in a language ";
  return `Not evaluable: this is written ${lang}which no active extractor reads, so ad2v cannot check ` +
    "it against the spec. Enable an extractor for it (ad2v extractors list).";
}
