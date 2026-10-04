// P7 M4: the chat panel's pure parts (the DOM parts run in e2e/chat.spec.ts against a real server).
import { describe, expect, it } from "vitest";
import { parseSse, usd } from "../src/ui/chat";
import { toIntent } from "../src/ui/intent";

describe("chat", () => {
  it("parses server-sent events across chunk boundaries", () => {
    const a = parseSse('event: tool_call\ndata: {"name":"ad2v_locate"}\n\nevent: us');
    expect(a.events).toEqual([{ event: "tool_call", data: { name: "ad2v_locate" } }]);
    const b = parseSse(a.rest + 'age\ndata: {"usd":0.001}\n\nevent: bad\ndata: {oops\n\n');
    expect(b.events).toEqual([{ event: "usage", data: { usd: 0.001 } }]); // a malformed frame is skipped
    expect(b.rest).toBe("");
  });

  it("formats money for the meter", () => {
    expect(usd(0.00123)).toBe("$0.0012");
    expect(usd(0.25)).toBe("$0.25");
    expect(usd(null)).toBe("unpriced");
  });

  it("maps ad2v_show results to map intents", () => {
    expect(toIntent({ intent: "path", nodes: [{ id: "n_a" }, { id: "n_b" }], workflow_id: "w" })).toMatchObject({
      intent: "path",
      nodes: ["n_a", "n_b"],
      workflowId: "w",
      theme: "auto",
    });
    expect(toIntent({}).intent).toBe("focus");
  });
});
