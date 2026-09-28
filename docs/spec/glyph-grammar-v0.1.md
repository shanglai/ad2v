# ad2v glyph grammar, v0.1

Status: **draft, normative**. Reference implementation: `src/ad2v/glyphs.py`.

A glyph is how a node looks. The grammar makes it computable without an LLM, identical across
viewers, and learnable: a reader who knows the ten shapes can read any ad2v map.

## 1. Encoding channels

| channel | encodes | source | decided in |
|---|---|---|---|
| **shape** (base shape + variant) | node **kind** | `nodes.kind` (+ container kind) | this document |
| **modifiers** | node **attributes** | graph structure + attrs | this document |
| **line style / glow / color** | link **status** | `links.status` | reserved; P2 fills `links` |
| **size** | **weight** | `glyphs.size_weight` | this document |

**Never overload a channel.** A risk is a modifier (badge), not a color. A status is a line style,
not a shape. An API gateway is a gateway with N port axles, not a new shape.

## 2. Base shapes (closed set of 10)

| base shape | used for |
|---|---|
| `cylinder` | datastore |
| `tube` | queue |
| `trapezoid` | ui; containers whose manifest kind is `gateway`, `api_gateway`, `ui` or `frontend` |
| `rounded_box` | system, container, component, module, class, function, transaction |
| `hexagon` | llm_endpoint, llm_call |
| `diamond` | decision/branching behavior: fan_out |
| `ring` | loop, retry |
| `port_notch` | http_route, mcp_tool, cli_command, event_consumer. Drawn attached to the parent's face. |
| `folded_sheet` | every spec kind |
| `cloud` | external_service |

## 3. Exact kind → (base shape, variant) mapping

| kind | base shape | variant | drawing note |
|---|---|---|---|
| system | rounded_box | `system` | largest box, thin wall |
| container | rounded_box | `container` (or trapezoid `gateway`) | thick wall, tall |
| component | rounded_box | `component` | medium |
| module | rounded_box | `module` | flat tile |
| class | rounded_box | `class` | **small** box, 0.5× module height |
| function | rounded_box | `function` | **smallest** box, 0.25× module height, flat |
| transaction | rounded_box | `transaction` | bracketed outline around its children |
| http_route | port_notch | `http_route` | notch label = `METHOD path` |
| mcp_tool | port_notch | `mcp_tool` | notch with tool glyph |
| cli_command | port_notch | `cli_command` | notch with prompt glyph |
| event_consumer | port_notch | `event_consumer` | inward notch |
| datastore | cylinder | `datastore` | |
| queue | tube | `queue` | horizontal |
| external_service | cloud | `external_service` | |
| llm_endpoint | hexagon | `llm_endpoint` | |
| llm_call | hexagon | `llm_call` | small, flat |
| ui | trapezoid | `ui` | |
| loop | ring | `loop` | |
| retry | ring | `retry` | ring with arrowhead |
| fan_out | diamond | `fan_out` | |
| spec_doc … spec_endpoint | folded_sheet | = kind | spec_doc largest, scenario_step smallest |

## 4. Modifiers

`glyphs.modifiers_json` always contains all five keys:

| modifier | type | rule | drawn as |
|---|---|---|---|
| `ports` | int | number of outgoing `exposes` edges | notches/axles on the glyph |
| `replicas` | int ≥ 1 | containers: `attrs.replicas` (manifest), others 1 | stacked shadow copies (max 3 drawn) |
| `has_loop_risk` | bool | the node's `attrs.risk` ∩ {`io_in_loop`, `llm_in_loop`, `nested_loop_io`, `unbounded_retry`} ≠ ∅, **or any descendant has it** | warning badge |
| `has_llm` | bool | kind is llm_endpoint/llm_call, or the node has an outgoing `invokes_llm` edge, or any descendant does | hexagon badge |
| `external` | bool | kind is external_service, or the node has an outgoing `invokes_external` edge, or any descendant does | cloud badge |

Modifiers roll up the `contains` hierarchy, so a collapsed container still tells you it hides an
N+1 loop.

## 5. Level of detail (LOD)

The same glyph at three detail levels. **The shape never changes across zoom.**

| LOD | shows |
|---|---|
| 0 silhouette | base shape + variant proportions only |
| 1 modifiers | + modifier badges, port notches, replica shadows, name label |
| 2 open interior | + children laid out inside (only if `has_interior = 1`) |

## 6. Size

`size_weight` (int ≥ 1): for resources (`datastore`, `queue`, `external_service`, `llm_endpoint`, `ui`),
it is the sum of the weights of incoming non-hierarchy edges (how much the resource is used). For
every other node, it is the line count of its span (`span_end - span_start + 1`). Nodes without a span
use the sum over their children. Viewers SHOULD map size with a sub-linear scale (e.g. `sqrt`).

## 7. Reserved: line style and glow (status channel)

These come from `links.status` in P2 and are not stored in `glyphs`:

| status | line | glow |
|---|---|---|
| specified | dotted | none |
| missing | dotted, dim | none |
| implemented | solid | none |
| verified | solid | blue |
| drift | solid | amber |
| orphan | red dashed | none |
| stale | desaturated previous style | none |
| needs_review | amber outline | none |

## 8. Palette constraints (informative)

Dark background. Color is reserved for status (§7). Kinds are distinguished by shape only, so
the map stays readable in grayscale and for color-blind users.
