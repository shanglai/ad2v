# Infra fixtures (P10)

- `gcp/plan.json`, `aws/plan.json`: hand-written plan JSON (`terraform show -json` format, version
  1.x) with modules, `for_each`, `count`, unknown values, sensitive values and env vars sourced from a
  resource, a secret and a literal. Values containing `PLANTED` are fake secrets: the tests check
  that none of them reaches a `.ad2v` file or its dump.
- `brownfield-es/{prod,dev}.json`: plans for `fixtures/brownfield-es/infra` (dev declares the
  frontend bucket, the archive bucket and the topic with `count = 0`).
- `tofu-real/`: a real plan produced offline by OpenTofu 1.13.1 from `cfg/` (providers `null`,
  `random` and the built-in `terraform_data`; `-refresh=false`, no credentials). The binary and the
  provider cache were deleted after the run.
