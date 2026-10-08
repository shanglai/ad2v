# ADR-0074: Infra from a Terraform/OpenTofu plan JSON (never by running Terraform)

- Status: accepted (P10)
- Context: the questions worth answering sit across spec, code and infra:
  - which service runs this component?
  - does any deployment provide `DATABASE_URL`?
  Terraform knows the deployed shape, but `terraform plan` runs providers and `external` data
  sources (arbitrary programs) and needs credentials and state. ad2v must never execute anything
  from a repository.

## Decisions

1. **The human supplies the plan.** `ad2v extract … --infra-plan [ENV=]plan.json` is repeatable,
   one file per environment, and the default name is `default`; `--infra-env` names a plan given
   without `ENV=`. ad2v only reads the JSON written by `terraform show -json tfplan` or
   `tofu show -json`. `ad2v init` prints the command and the warning (ADR-0081). Terraform (BSL)
   and OpenTofu (MPL) are tools the user runs, never dependencies.
2. **Format.** The documented plan representation has `format_version` "1.0"; minor versions are
   backward compatible, and Terraform 1.9 and OpenTofu 1.13 emit "1.2". ad2v reads any 1.x and
   refuses anything else.
3. **What is read.**
   - `planned_values`: root and child modules, with `count`/`for_each` instances already expanded;
   - `configuration`: references between resources and the env-var wiring expressions. Module
     variables and module outputs are followed (bounded depth); locals do not exist there;
   - `resource_changes`: the action only (`create`, `update`, `delete+create`, …) and
     `after_unknown`, so an attribute known only after apply is stored as `unknown`.
   Never read: `variables` (they hold sensitive values in clear), `prior_state`, output values,
   `timestamp`, `relevant_attributes`, `checks`.
4. **Typing by rules.** `src/ad2v/infra/infra.yaml` maps provider types to kinds:
   - GCP: Cloud Run v1/v2 services and jobs, Cloud Functions v2, Cloud SQL, Firestore, BigQuery,
     Memorystore, Pub/Sub, GCS, Secret Manager, VPC, Scheduler;
   - AWS: Lambda, ECS service (env from its task definition), Batch, App Runner, RDS/Aurora,
     DynamoDB, ElastiCache, SQS, SNS, S3 (plus the website configuration), Secrets Manager,
     EventBridge rules.
   Anything else is `infra_other`. Azure and Kubernetes manifests are pending. The rules are in
   the epoch rules (`infra`), so they are covered by `rules_hash`.
5. **Epoch input.** Each plan's content hash is computed over canonical JSON without
   `timestamp`, so key order, whitespace, BOM and line endings never matter. With the static
   files (ADR-0075) it forms `epochs.infra_hash`, which is `''` when there is no infra input.
   An epoch given no plan carries the parent's plan-derived nodes forward, like test results.
   `change_kind` gains `infra`.
6. **Nodes.**
   - one `infra_module` root per environment (`infra:<env>`);
   - module instances below it;
   - each resource instance as `infra:<env>:<address>`, with `attrs.source = plan|static`, its
     type, provider, action and the allowlisted attributes (ADR-0076).
   Edges: `references` (from configuration expressions) and `wires` (unit → the resource an env
   var's value comes from).
7. **Verified on real output.** A plan produced offline by OpenTofu 1.13.1 (`null`/`random`
   providers and `terraform_data`, `-refresh=false`, no credentials) parses, and module variables
   resolve. It is kept as `fixtures/infra/tofu-real`; the binary and provider cache were deleted.
