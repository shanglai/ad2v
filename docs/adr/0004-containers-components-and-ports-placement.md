# ADR-0004: Containers, components, and where ports live

- Status: accepted (P1)
- Decisions:
  1. **Container assignment** uses the longest matching manifest path. Without a manifest, each
     top-level directory that contains `pyproject.toml`, `setup.py` or `Dockerfile` is a container.
     Files that match no container go to a fallback container named after the system, created only
     when needed. If there are no containers at all, that fallback is the repo root.
  2. **`component` = a directory** between the container root and the module. Nested directories give
     nested components, so depth is relative (format principle 5). The manifest cannot declare
     components yet (see `pending.md`).
  3. **Ports are children of their container** (`parent_id = container`, plus an `exposes` edge), so a
     collapsed container still shows its notches. The port reaches its handler through a `calls`
     edge `port -> handler`, and `attrs.handler` holds the handler's qualified name.
  4. **Port qualified names include the container** (`http:api:GET /v1/x`), because two services may
     expose the same route.
  5. **System name** = manifest `system.name`, else the repo directory name. It is the system node's
     qualified name, so without a manifest, renaming the checkout directory renames the system node.
     The fixture declares it.
- Consequences: P2 pairs `http_route` with `spec_endpoint` by `(method, path)` from `attrs`, never by
  comparing qualified names across sides.
