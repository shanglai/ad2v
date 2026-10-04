# Example ad2v plug-ins (out of tree)

Two tiny packages that use only the public plug-in API (`ad2v.api`, api 1.0). Neither is part of
ad2v; they show that an extractor or a framework pack can live in its own repository.

| package | entry point | what it does |
|---|---|---|
| `routes-dsl-extractor/` (`ad2v-routes-dsl`) | `ad2v.extractors: routes-dsl` | reads `*.routes` files (`GET /v1/orders list_orders # ad2v: REQ-001`) into `module` and `http_route` nodes |
| `bottle-framework-pack/` (`ad2v-bottle-pack`) | `ad2v.frameworks: bottle` | adds one route recognizer (`bottle.Bottle` apps) to the built-in Python extractor, as a rules fragment |

Each has a `fixture/` directory for the conformance kit.

## Try them in a throwaway virtual environment

From the repository root (ad2v is not on PyPI yet, so install it from the checkout first):

```bash
python -m venv .venv-plugins
```

```bash
.venv-plugins/bin/pip install . examples/plugins/routes-dsl-extractor examples/plugins/bottle-framework-pack
```

(On Windows use `.venv-plugins\Scripts\pip`.) Then:

```bash
ad2v extractors list --inspect
```

```bash
ad2v extractor check routes-dsl --fixture examples/plugins/routes-dsl-extractor/fixture
```

```bash
ad2v extractor check bottle --fixture examples/plugins/bottle-framework-pack/fixture
```

```bash
ad2v extract --repo examples/plugins/routes-dsl-extractor/fixture --out orders.ad2v
```

The routes fixture enables its extractor in its own `ad2v.yaml`; the Bottle fixture needs
`--extractor bottle`. Delete `.venv-plugins` afterwards.
