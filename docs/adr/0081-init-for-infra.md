# ADR-0081: `ad2v init` for infra

- Status: accepted (P10)

## Decisions

1. **`infra_root`.** `init` proposes the Terraform folders it detects as root modules (P9
   detection; folders named `modules` excluded) and reports, per container, the deployment unit
   that matches by name.
2. **The plan command, with its warning,** printed verbatim:
   `terraform init && terraform plan -refresh=false -out tfplan && terraform show -json tfplan > plan.json`.
   It runs the providers and needs credentials and state. ad2v never runs it and only reads
   `plan.json` (`--infra-plan prod=plan.json`). Keep `plan.json` out of the repository.
3. **Ambiguity.** When several units match a container by name (different images), the proposal
   gets `infra: {deploys: {<address>: ""}}` placeholders, one per candidate. An empty value is
   ignored, so the proposal stays valid. `init --check` lists an ambiguous container until one
   placeholder is filled, and a Terraform folder missing from `infra_root`.
4. Other IaC (Pulumi, CloudFormation, Kubernetes, Helm) is still only reported: "detected; not
   read".
