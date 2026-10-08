# The infra layer (P10)

ad2v maps spec ↔ code. With infra it can also answer:
- "Which Cloud Run service runs this component?"
- "The code reads `DATABASE_URL`: does any deployment provide it?"
- "What does the architecture look like, and which requirements does each part carry?"

Infra is read deterministically and never executed. It feeds two things: the env-var bridge
between code and infra, and a C4 view in its own tab (**Architecture**).

## 1. Inputs

| input | when | what ad2v does |
|---|---|---|
| plan JSON (`--infra-plan [ENV=]plan.json`, repeatable) | you produce it | reads `planned_values`, `configuration`, `resource_changes` (actions, unknowns) |
| `.tf` files (`infra_root: [infra]` in `ad2v.yaml`) | every epoch, also in `history` | parses them statically (python-hcl2); nothing is evaluated |

**ad2v never runs `terraform`, `tofu`, `terragrunt` or providers.** `plan` runs providers and
`external` data sources (arbitrary programs) and needs credentials and state. You produce the plan
yourself; `ad2v init` prints the command:

```bash
terraform init && terraform plan -refresh=false -out tfplan && terraform show -json tfplan > plan.json
```

Keep `plan.json` out of the repository. Plan versions: `format_version` 1.x (Terraform ≥ 1.1,
OpenTofu). Key order, whitespace, BOM and the timestamp never change the epoch.

```bash
ad2v extract --repo . --manifest ad2v.yaml --out app.ad2v --infra-plan prod=plan-prod.json --infra-plan dev=plan-dev.json
```

An epoch extracted without a plan carries the previous epoch's plan forward. A change in the
plans or the `.tf` files alone gives a new epoch with `change_kind: infra`.

**Plan and static together.** For the same environment the plan wins. The static read only fills
gaps: resources the plan's configuration does not declare at all, which happens when the plan is
older than the `.tf`. Those nodes are marked `gap_fill`, and the summary says "filled from .tf".

## 2. Resource types

`src/ad2v/infra/infra.yaml` maps provider types to kinds. It is part of the epoch rules, so it is
covered by `rules_hash`.

| kind | GCP | AWS |
|---|---|---|
| `deployment_unit` | Cloud Run services (v1, v2) and jobs, Cloud Functions v2 | Lambda, ECS service (env from its task definition), Batch job definition, App Runner |
| `managed_datastore` | Cloud SQL, Firestore, BigQuery dataset, Memorystore | RDS instance and cluster, DynamoDB, ElastiCache |
| `managed_queue` | Pub/Sub topic and subscription | SQS, SNS |
| `bucket` | GCS (a `website` block makes it a static site) | S3 (+ `aws_s3_bucket_website_configuration`) |
| `secret_store` | Secret Manager secret (names only) | Secrets Manager secret |
| `network` | VPC network, VPC access connector | |
| `scheduler` | Cloud Scheduler job | EventBridge rule |
| `infra_other` | anything else (kept and counted) | |

Azure and Kubernetes manifests are not read yet (`pending.md`).

## 3. Secrets policy

The policy (ADR-0076):
- Only an allowlist of attributes per type is stored: names, locations, scaling, the image
  repository without tag or digest, engine and tier, encryption flags as booleans, schedules.
- Env vars keep their **names** and a **source** (`reference` to a resource, `secret`, `literal`,
  `unknown`), never the value.
- Anything under `sensitive_values` is dropped, and `variables`, `prior_state` and output values
  are never read.
- Module sources become `remote: true|false`, never the URL.

A test plants more than 15 fake secrets in plans and `.tf` files. It checks that none appears in
the `.ad2v` file's bytes or in its dump.

## 4. Static `.tf` limits

- `count` / `for_each` are not expanded: one node, `multiplicity: unresolved`.
- Local modules are followed one level. Deeper calls are reported, and remote modules are
  recorded but not read.
- Variables stay unresolved, and their defaults are never stored.
- Only literals are known; `locals` are followed for references.
- `dynamic` blocks and `jsonencode(...)` are opaque.
- Files over 4 MB are skipped, and a file that does not parse is reported, never fatal.
- One static environment per infra root: `default` for one root, otherwise the folder's name.

## 5. The env-var bridge

**Code side.** The env var names the code reads are collected:
- `os.environ[...]`, `os.getenv(...)`, `os.environ.get(...)`;
- pydantic `BaseSettings` fields, with `env_prefix`, `Field(alias=…)` and `validation_alias`.

They are stored as `attrs.env_reads`, only in epochs with infra input.

**`deploys`** (deployment unit → code container), per environment, first match wins:
1. the manifest: `infra: {deploys: {"google_cloud_run_v2_service.api": backend}}`;
2. a name match: the unit's name or its image repository equals the container name, or ends or
   starts with it at a `-` (`conciliacion-backend` ↔ `backend`);
3. env-var overlap: the container's reads are a subset of the unit's env, with ≥ 2 shared names
   and one best candidate.

Several candidates at one level are **ambiguous**: no edge, and `ad2v init` proposes
`infra.deploys` placeholders. One unit may deploy several containers, and units with the same
image may deploy one container. A website bucket can deploy a container too (a static site).

**`provides_env` / `wires`.** An env var read in a deployed container is `wired` when its unit
sets it, with an edge to the resource the value comes from when known. Otherwise it is `unwired`,
naming the variable and the unit.

## 6. Statuses: a separate dimension

Infra findings never change the ten spec↔code statuses (ADR-0078). They live in `infra_status`,
per environment:

| applies to | statuses |
|---|---|
| code containers | `deployed`, `undeployed`, `ambiguous` |
| code nodes reading env vars (in a deployed container) | `wired`, `unwired` |
| infra resources | `in_use`, `infra_orphan` |
| everything, without infra input | `unknown` (no rows: nothing is claimed) |

On the map, **Infra badges** (toolbar) prefix labels: ☁ deployed, ∅☁ undeployed, ⚠ unwired,
?☁ ambiguous, ∅ orphan. Node cards list the status per environment.

## 7. The C4 view (Architecture tab)

The view is derived from the epoch's graph, never drawn by hand (ADR-0079):
- **Context level:** the system, persons (user-story actors) and external systems.
- **Container level:**
  - deployment units, with the code containers they run;
  - static sites;
  - datastores, queues, buckets and schedulers;
  - code containers that nothing deploys.
- **Relations:** code calls, reads, writes and publishes aggregated to containers; `wires` (env
  var names on hover); persons → the containers their stories pair with.

Each container shows:
- the roll-up of its requirements' statuses;
- its infra status (line style + color);
- unwired env vars;
- its NFRs ("NFR (checked against infra in a later phase)").

Click an element for its card; **open in map** jumps to the container. Selecting on the map
highlights the element. The **Env** selector switches environments.

The layout is deterministic and keeps each element's slot across epochs.

```bash
ad2v c4 app.ad2v --env prod --format structurizr > workspace.dsl
```

```bash
ad2v c4 app.ad2v --env prod --format json
```

## 8. MCP

- `ad2v_architecture`: elements, relations and findings per environment.
- `ad2v_show` with intent `c4` (and `env`): opens the Architecture view in the MCP App.
- `ad2v_overview`: reports infra counts and findings.
- `ad2v_locate` understands infra words: "which service runs the backend", "unwired",
  "orphan bucket".

## 9. Per environment

Every finding is computed per environment. A container can be deployed in prod and not in dev,
and an env var can be wired in one and missing in the other. Plans name their environment.
Without plans, each infra root is one environment.
