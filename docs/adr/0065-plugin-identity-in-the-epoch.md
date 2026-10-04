# ADR-0065: Plug-in identity in the epoch, additive within format v0.5

- Status: accepted (P8)
- Context: an epoch id must cover every input that shapes its output (ADR-0010, ADR-0012). With
  plug-ins, the extractor set, each plug-in's version and its rules are such inputs. The parse
  cache (ADR-0018) must not serve one extractor's records to another, or to a newer version.

## Decisions

1. **Identity records in the rules.** The epoch rules (what `rules_versions.rules_json` stores
   and `rules_hash` hashes) gain a key `plugins`: for every active plug-in `{kind, name, version,
   api_version, rules_hash}` (the canonical hash of its own rules files), plus `attaches_to` for
   packs and `effective_rules_hash` (its rules after packs and overlay) for extractors, sorted by
   kind and name. Third-party extractors' effective rules are stored under `plugin_rules.<name>`.
   The built-in Python extractor's effective rules stay at the top level, as in P7, so severity
   and retrieval readers are unchanged. Plug-in identity is therefore covered by `rules_hash` and
   by the epoch id "the same way `rules_hash` does today", and a plug-in change is reported as
   `change_kind = rules`.
2. **No format bump.** No DDL changes; the new key is inside an existing normative JSON column,
   and `epochs.attrs.plugin_failures` is a new optional attribute. v0.5 readers (viewer, MCP,
   validate) need no change, so this is **additive within v0.5** (format spec "Additions within
   v0.5"). Upgrade path: none needed; an old file gets a new epoch on its next extraction even if
   nothing else changed, because its head epoch's rules lack `plugins`.
3. **Epoch ids change once.** Every epoch extracted by P8 has a different `rules_hash` and epoch
   id than the same inputs under P7. Everything else in the normative output is identical:
   P8 compared the normative dumps (every epoch) of all fixtures before and after the refactor
   with each epoch id and rules hash replaced by its P7 counterpart (same `seq`): identical for
   `payments-recon` (with and without test results, both settings-prefix modes), the P3 history
   scenario (8 epochs, LF and CRLF+BOM) and the three `sdd-presets` fixtures.
4. **Inputs.** `repo_tree_hash` covers every file claimed by an active plug-in (`*.py` for
   `python`, `*.sql` for `python-frameworks`: exactly the P7 input set), so enabling an extractor
   for `*.routes` adds those files as inputs.
5. **Parse cache key.** `extractor_version` = `<name>@<version>[:<cache version>]`
   (`python@1.0.0:python-local-3`), `rules_hash` = that extractor's `effective_rules_hash`, so
   enabling an unrelated plug-in does not invalidate the Python cache. No DDL change. The GC in
   `prune` keeps a row while some remaining epoch has the file content and lists that effective
   hash in its `plugins` records (or, for pre-P8 rows, has it as its own `rules_hash`).
