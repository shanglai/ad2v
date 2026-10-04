// The viewer's own chat (P7, ADR-0056): a panel input that talks to `ad2v view --chat` over
// `/api/chat/*` (server-sent events). The model runs server-side; this page only shows the turn:
// the question, the tool steps (collapsible), the answer (safe Markdown), citation chips and an AI
// label, plus the budget meter and the per-turn estimate. `ad2v_show` drives the map when
// "Follow" is on. Without `--chat`, the input stays disabled and shows how to turn it on.
import { h } from "./dom";
import { toIntent, type ShowResult } from "./intent";
import { renderMarkdown } from "./markdown";
import type { ShowIntent } from "./app";

export interface ChatHost {
  fileName: string;
  /** a cited node: pin it in the panel and fly to it */
  select(id: string): void;
  /** an ad2v_show intent from the agent */
  show(intent: ShowIntent): void;
  label(id: string): string | null;
}

interface Meter {
  budget_usd: number;
  spent_usd: number;
  remaining_usd: number;
  input_tokens: number;
  output_tokens: number;
  calls: number;
  turns: number;
}

interface Ref {
  id: string;
  label: string;
  kind: string;
  status: string;
}

export interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

/** Split a server-sent-events buffer into complete events and the unparsed rest. */
export function parseSse(buf: string): { events: SseEvent[]; rest: string } {
  const events: SseEvent[] = [];
  const frames = buf.split("\n\n");
  const rest = frames.pop() ?? "";
  for (const f of frames) {
    let event = "message";
    const data: string[] = [];
    for (const line of f.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    try {
      events.push({ event, data: data.length ? JSON.parse(data.join("\n")) : {} });
    } catch {
      /* a malformed frame is skipped */
    }
  }
  return { events, rest };
}

export function usd(x: number | null | undefined): string {
  if (x === null || x === undefined) return "unpriced";
  return x < 0.01 ? `$${x.toFixed(4)}` : `$${x.toFixed(2)}`;
}

function ktok(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

export class ChatPanel {
  readonly el = h("div", { class: "chat", id: "chat" });
  readonly meterEl = h("span", { class: "meter", id: "chat-meter", title: "chat budget for this session" });
  private readonly input = h("textarea", {
    id: "chat-input",
    rows: 2,
    disabled: true,
    placeholder: "Checking for the chat…",
    "aria-label": "ask about this map",
  });
  private readonly send = h("button", { id: "chat-send", disabled: true, title: "send (Ctrl+Enter)" }, "Ask");
  private readonly estimateEl = h("div", { class: "muted estimate", id: "chat-estimate" });
  private readonly follow = h("input", { type: "checkbox", id: "chat-follow", checked: true });
  private token = "";
  private enabled = false;
  private busy = false;
  private abort: AbortController | null = null;
  private meter: Meter | null = null;

  constructor(
    private readonly host: ChatHost,
    private readonly addCard: (el: HTMLElement) => void,
    private readonly fetchFn: typeof fetch = (...a) => fetch(...a),
  ) {
    this.el.append(
      this.input,
      h("div", { class: "chat-row" },
        h("label", { class: "follow", title: "the map follows what the agent shows" }, this.follow, " Follow"),
        this.estimateEl,
        this.send),
    );
    this.send.addEventListener("click", () => void this.ask());
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        void this.ask();
      } else if (e.key === "Escape") {
        e.preventDefault();
        void this.cancel();
      }
    });
  }

  private headers(json = false): Record<string, string> {
    return { "X-Ad2v-Token": this.token, ...(json ? { "Content-Type": "application/json" } : {}) };
  }

  /** Ask the server whether the chat is on (only `ad2v view --chat` serves it). */
  async init(hash: string = location.hash): Promise<void> {
    this.token = new URLSearchParams(hash.replace(/^#/, "")).get("chat") ?? "";
    const off = `Chat with your own model: ad2v view ${this.host.fileName} --chat --manifest ad2v.yaml (or use an MCP host: ad2v mcp)`;
    if (typeof location !== "undefined" && !/^https?:$/.test(location.protocol)) {
      this.input.placeholder = off; // the single-file demo: no server to ask
      return;
    }
    try {
      const r = await this.fetchFn("/api/chat/session", { headers: this.headers() });
      if (!r.ok) throw new Error(String(r.status));
      const s = (await r.json()) as { enabled: boolean; command?: string; meter?: Meter; estimate?: { usd: number | null; calls: number }; provider?: string; model?: string };
      if (!s.enabled) {
        this.input.placeholder = `Chat is off. Start it with: ${s.command ?? off}`;
        return;
      }
      this.enabled = true;
      this.input.disabled = false;
      this.send.disabled = false;
      this.input.placeholder = `Ask about this map (${s.provider}/${s.model}) · Ctrl+Enter sends, Esc cancels`;
      this.update(s.meter ?? null, s.estimate ?? null);
    } catch {
      this.input.placeholder = off; // the static demo, or a server without --chat
    }
  }

  get isEnabled(): boolean {
    return this.enabled;
  }

  private update(m: Meter | null, est: { usd: number | null; calls: number } | null): void {
    if (m) {
      this.meter = m;
      this.meterEl.textContent = `${usd(m.spent_usd)} / ${usd(m.budget_usd)} · ${ktok(m.input_tokens + m.output_tokens)} tok`;
      if (m.remaining_usd <= 0) this.capped();
    }
    if (est) this.estimateEl.textContent = `next turn ≈ ${usd(est.usd)} (${est.calls} call${est.calls === 1 ? "" : "s"})`;
  }

  private capped(message?: string): void {
    this.input.disabled = true;
    this.send.disabled = true;
    this.input.placeholder = message ?? `Budget used up. Restart with a higher cap: ad2v view ${this.host.fileName} --chat --chat-budget-usd 0.50 --manifest ad2v.yaml`;
  }

  async cancel(): Promise<void> {
    if (!this.busy) return;
    await this.fetchFn("/api/chat/cancel", { method: "POST", headers: this.headers(true), body: "{}" }).catch(() => undefined);
  }

  async ask(question = this.input.value): Promise<void> {
    const q = question.trim();
    if (!this.enabled || this.busy || !q) return;
    this.busy = true;
    this.send.disabled = true;
    this.input.value = "";
    const card = new TurnCard(q, (id) => this.host.select(id), (id) => this.host.label(id));
    this.addCard(card.el);
    this.abort = new AbortController();
    try {
      const r = await this.fetchFn("/api/chat/turn", {
        method: "POST",
        headers: this.headers(true),
        body: JSON.stringify({ question: q }),
        signal: this.abort.signal,
      });
      if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const { events, rest } = parseSse(buf);
        buf = rest;
        for (const ev of events) this.onEvent(ev, card);
      }
    } catch (e) {
      card.error(`The chat request failed: ${String(e)}`);
    } finally {
      this.busy = false;
      this.abort = null;
      if (this.enabled && !(this.meter && this.meter.remaining_usd <= 0)) this.send.disabled = false;
    }
  }

  onEvent(ev: SseEvent, card: TurnCard): void {
    const d = ev.data as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    switch (ev.event) {
      case "estimate":
        card.note(`estimated ${usd(d["usd"])} for ~${d["calls"]} call(s)`);
        break;
      case "tool_call":
        card.step(String(d["name"]), d["args"] as Record<string, unknown>);
        break;
      case "tool_result":
        card.stepResult(Number(d["chars"]), (d["node_ids"] as string[]).length);
        break;
      case "show":
        if (this.follow.checked) this.host.show(toIntent(d as unknown as ShowResult));
        break;
      case "usage":
        this.update(d["meter"] as Meter, null);
        break;
      case "answer":
        card.answer(String(d["answer_markdown"]), d["citations"] as Ref[], d["dropped"] as string[], d["flags"] as string[]);
        break;
      case "error":
        card.error(String(d["message"]));
        if (d["code"] === "budget") this.capped(String(d["message"]));
        if (d["meter"]) this.update(d["meter"] as Meter, null);
        break;
      case "done":
        this.update(d["meter"] as Meter, null);
        void this.refreshEstimate();
        break;
    }
  }

  private async refreshEstimate(): Promise<void> {
    try {
      const r = await this.fetchFn("/api/chat/session", { headers: this.headers() });
      if (r.ok) {
        const s = (await r.json()) as { meter: Meter; estimate: { usd: number | null; calls: number } };
        this.update(s.meter, s.estimate);
      }
    } catch {
      /* the meter in the last event stays */
    }
  }
}

export class TurnCard {
  readonly el: HTMLElement;
  private readonly steps = h("ol", { class: "steps" });
  private readonly stepsBox = h("details", { class: "tool-steps" }, h("summary", {}, "0 tool steps"), this.steps);
  private readonly body = h("div", { class: "answer", "aria-live": "polite" }, h("p", { class: "muted" }, "Thinking…"));
  private nSteps = 0;

  constructor(
    question: string,
    private readonly select: (id: string) => void,
    private readonly label: (id: string) => string | null,
  ) {
    this.el = h("section", { class: "card chat-turn" },
      h("p", { class: "question" }, question),
      this.stepsBox,
      this.body);
  }

  note(text: string): void {
    this.stepsBox.append(h("p", { class: "muted" }, text));
  }

  step(name: string, args: Record<string, unknown>): void {
    this.nSteps++;
    const brief = Object.entries(args ?? {}).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join(", ");
    this.steps.append(h("li", {}, h("code", {}, name), brief ? ` ${brief.slice(0, 160)}` : ""));
    (this.stepsBox.querySelector("summary") as HTMLElement).textContent = `${this.nSteps} tool step${this.nSteps === 1 ? "" : "s"}`;
  }

  stepResult(chars: number, nodes: number): void {
    const li = this.steps.lastElementChild;
    if (li) li.append(h("span", { class: "muted" }, ` → ${chars} chars, ${nodes} node(s)`));
  }

  private chip(id: string, text: string, status?: string): HTMLElement {
    return h("button", { class: "chip cite", "data-node": id, "data-status": status ?? "", title: `fly to ${text}`, onclick: () => this.select(id) }, text);
  }

  answer(md: string, citations: Ref[], dropped: string[], flags: string[]): void {
    const content = renderMarkdown(md, (id, text) => this.chip(id, this.label(id) ?? text));
    const parts: Node[] = [h("p", { class: "ai-label", title: "written by your model; check it against the map" }, "AI"), content];
    if (citations.length) parts.push(h("div", { class: "citations" }, ...citations.map((c) => this.chip(c.id, c.label, c.status))));
    if (dropped.length) parts.push(h("p", { class: "warn" }, `${dropped.length} citation(s) dropped: not found in this turn's tool results.`));
    if (flags.includes("echoed_injection"))
      parts.push(h("p", { class: "warn" }, "Warning: the answer repeats an instruction found in the repository data; treat it with care."));
    this.body.replaceChildren(...parts);
  }

  error(text: string): void {
    this.body.append(h("p", { class: "warn" }, text));
    const thinking = this.body.querySelector("p.muted");
    if (thinking?.textContent === "Thinking…") thinking.remove();
  }
}
