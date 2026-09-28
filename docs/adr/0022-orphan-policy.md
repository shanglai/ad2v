# ADR-0022: Orphan policy

- Status: accepted (P3)
- Context: in P2, spec-less repositories painted every port and container `orphan` (template: 42
  orphans, dispatch: 462). "Nobody wrote specs" was reported as "everything is undocumented".
- Decisions:
  1. `pairing.orphan_policy` ∈ `auto` (default), `strict` (P2 behavior), `off`. `auto` assigns
     orphans only when the epoch has at least one spec item (`requirement`, `scenario`,
     `spec_component`, `spec_endpoint`); otherwise unpaired code keeps status `none`, and
     `meta.spec_coverage = 'none'`.
  2. The **effective** policy enters `config_hash` (`{"effective": {"orphan_policy": …},
     "manifest": …}`), so changing the default in a later version changes epoch ids instead of
     silently changing statuses under the same id.
  3. **YAML 1.1 `off`**: PyYAML reads a bare `off` as `false`. `false` is accepted as `off`, and
     other non-string values are an error listing the valid policies.
- Consequences: a spec-less repository shows no red at all until specs appear. Adding the first
  spec item can flip many nodes to `orphan` in one epoch; `ad2v diff` reports that as status
  transitions, which is the intended signal.
