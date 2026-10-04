# ADR-0060: Containers and components are rolled up, not judged

- Status: accepted (P7)
- Context: P4 judged container- and component-level links from a digest only (issue 43): costly,
  vague, and redundant with the judgments of their contents.
- Decisions:
  1. `judge.judgeable` skips links whose spec or code side is a container, component or spec
     component. These are no longer in `plan` or `run`.
  2. After every judge run (also when rebuilding from the cache), `judge_rollups` (format v0.5,
     class I) gets one row per container, component or spec component that has confident
     judgments below it (valid, confidence ≥ `llm.judge.min_confidence`, on links whose spec or
     code side descends from it). Each row holds:
     - the worst verdict (drift > partial > conforms > cannot_tell);
     - its confidence (ties go to higher confidence, then the link id);
     - the counts per verdict, the link ids and the threshold used.
  3. `node_status_effective` treats a roll-up `drift` like a judged drift: an
     implemented/verified container shows effective `drift` (provenance llm). Nothing the model
     says can clear a problem.
  4. The roll-up is deterministic: the same judgments give the same rows.
  5. Fixture: CMP-002 → `container:worker` stays labeled in `expected-judgments.yaml` for
     comparison with P4, but it is no longer scored. Judge jobs go from 12 to 11, and labeled
     links judged from 11 to 10.
- Found while testing: `ad2v prune --drop-llm-cache` built its "still referenced" list with
  `SELECT result_id FROM <table>`. For a table without that column, SQLite binds the name to the
  outer query, so nothing was ever deleted. The subquery is now qualified and skips
  `judge_rollups`.
