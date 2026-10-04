// A small, safe Markdown renderer for chat answers (P7, ADR-0056). It builds DOM nodes, never
// innerHTML: raw HTML in the model's text is shown as text. Supported: paragraphs, headings (#..###),
// bullet and numbered lists, fenced code, `code`, **bold**, *italic*. Links render only when they
// point at a node id ([label](n_…)) and become a chip that flies to the node; any other link is
// shown as its label, unlinked.
const NODE_ID = /^n_[0-9a-f]{20}$/;

export type NodeLink = (id: string, label: string) => HTMLElement;

export function renderMarkdown(md: string, link: NodeLink): DocumentFragment {
  const frag = document.createDocumentFragment();
  const lines = md.replace(/\r\n?/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i]!;
    if (/^\s*```/.test(line)) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i]!)) body.push(lines[i++]!);
      i++; // the closing fence
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = body.join("\n");
      pre.append(code);
      frag.append(pre);
      continue;
    }
    const head = /^(#{1,3})\s+(.*)$/.exec(line);
    if (head) {
      const el = document.createElement(`h${Math.min(6, head[1]!.length + 3)}` as "h4");
      el.append(...inline(head[2]!, link));
      frag.append(el);
      i++;
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const list = document.createElement(ordered ? "ol" : "ul");
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i]!)) {
        const li = document.createElement("li");
        li.append(...inline(lines[i]!.replace(/^\s*([-*]|\d+\.)\s+/, ""), link));
        list.append(li);
        i++;
      }
      frag.append(list);
      continue;
    }
    if (!line.trim()) {
      i++;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i]!.trim() && !/^\s*(```|#{1,3}\s|[-*]\s|\d+\.\s)/.test(lines[i]!)) para.push(lines[i++]!);
    const p = document.createElement("p");
    p.append(...inline(para.join(" "), link));
    frag.append(p);
  }
  return frag;
}

const TOKEN = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\([^)\s]+\))/g;

export function inline(text: string, link: NodeLink): Node[] {
  const out: Node[] = [];
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    if (m.index! > last) out.push(document.createTextNode(text.slice(last, m.index)));
    const t = m[0];
    if (t.startsWith("`")) {
      const c = document.createElement("code");
      c.textContent = t.slice(1, -1);
      out.push(c);
    } else if (t.startsWith("**")) {
      const b = document.createElement("strong");
      b.textContent = t.slice(2, -2);
      out.push(b);
    } else if (t.startsWith("*")) {
      const e = document.createElement("em");
      e.textContent = t.slice(1, -1);
      out.push(e);
    } else {
      const lm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(t)!;
      out.push(NODE_ID.test(lm[2]!) ? link(lm[2]!, lm[1]!) : document.createTextNode(lm[1]!));
    }
    last = m.index! + t.length;
  }
  if (last < text.length) out.push(document.createTextNode(text.slice(last)));
  return out;
}
