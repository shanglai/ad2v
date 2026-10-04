# ADR-0046: Route recall, and routes whose path is not fully known

- Status: accepted (P6.1)
- Context: P1 issue 7 and P2 issue 22. Routes registered in an app factory, with
  `add_api_route`, through `include_router` chains, or as Starlette `Route`/`Mount` lists were
  invisible, so their spec endpoints showed `missing`.
- Decisions:
  1. **Recognizers stay rules-driven** (`rules/python.yaml`, covered by `rules_hash`). New
     `ports.http` keys:
     - `add_route_methods`: `add_api_route` (path arg 0, endpoint arg 1), Flask `add_url_rule`
       (rule 0, view_func 2), Starlette `add_route` (path 0, route 1);
     - `route_list_constructors` (Starlette, Router, FastAPI, APIRouter with `routes=[…]`),
       `route_constructors` (`starlette.routing.Route`, `fastapi.routing.APIRoute`),
       `mount_constructors` (`starlette.routing.Mount`) and `mount_methods` (`app.mount(path, app)`).
     - `starlette.applications.Starlette` is an app constructor. `add_api_route` left
       `route_decorators`, where it never matched.
  2. **Factories.** App and router objects created inside a function get an origin
     (`module`, `scope:name`), so `include_router`/`register_blueprint`/`mount` inside
     `create_app()` link them like module-level objects. A router's own `prefix=` is kept when it is
     included again (this alone corrected 286 of 290 paths on dispatch, with `app.mount`).
  3. **Constant folding.** Paths and prefixes fold string literals, f-strings of constants, `+`
     and implicit concatenation, and module or function-local names. Each folded value carries
     `exact`.
  4. **`path_unresolved`.** When a prefix cannot be folded (for example
     `settings.API_V1_STR`, a pydantic `BaseSettings` default that an environment variable can
     override), the route keeps the known tail: `attrs.path_unresolved = true`,
     `attrs.path_tail = "/items/{id}"`, `attrs.registration`. We do **not** read Settings
     defaults: the deployed value can differ (pending.md lists it as an opt-in resolver).
  5. **Pairing.** An unpaired spec endpoint is offered unresolved routes with the same method
     whose known tail ends its path. The link is `needs_review` (method `route_match`, evidence
     `unresolved_route_path` with the tail), never `implemented`. The link method enum is
     unchanged (format v0.4 CHECK constraint).
  6. **Fixture deviation.** The P6.1 prompt suggested moving an existing endpoint into the factory.
     That would break the P3 history story (approve goes missing in one commit and is implemented
     in another). Instead `api/recon_api/factory.py` adds a new endpoint,
     `GET /reconciliations/{run_id}/export`, registered with `add_api_route` on a router included
     with an f-string prefix. P6's extractor reports it `missing`; P6.1 reports `implemented`.
- Consequences: `LOCAL_EXTRACTOR_VERSION` is `python-local-3`, so cached local facts are
  recomputed once. Two LLM suggestion recordings had their candidate index shifted (the
  candidate order changed); the content is the same.
