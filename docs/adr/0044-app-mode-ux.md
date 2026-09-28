# ADR-0044: App mode of the viewer

- Status: accepted (P6)
- Decisions:
  1. **Same app, different mode.** `App` takes `{mode: "app", file, intent, onSelect}`.
     - The chrome is compact: breadcrumbs of the selection, the normative/effective toggle,
       theme, a diff label, and "Open full map".
     - There is one collapsible card at a time, no chat box (the host is the chat) and no epoch
       scrubber. The replay bar appears for the `replay` intent.
  2. **Intents:**
     - `focus`: one node is entered and framed at interior LOD; several are fitted.
     - `fit`: the union of the boxes is framed, with a list card.
     - `path`: the nodes are outlined and joined in order with the replay styling (a new static
       `path` overlay), and fitted.
     - `replay`: the replay UI at `detail_level`.
     - `diff`: the diff overlay between two epochs (ids from `ad2v_show`), with a changes card.
  3. **Selection is shared with the host.** Clicking a node sends `ui/update-model-context` with
     a one-line description (name, kind, status, id). No message is posted to the chat.
  4. **"Open full map"** shows `ad2v view <file>` to copy: an app cannot start local programs.
  5. **Names outside the slice.** Link and suggestion partners outside the loaded slice are
     named through `nodeDetail`. Deterministic cards in app mode count only the loaded part of
     a subtree (a known limitation, listed in issues.md).
  6. Suggestion commands now include the file argument
     (`ad2v suggestions accept <file> <id> …`). The P5 viewer had omitted it, and the command
     failed as written.
