# brownfield-es (ad2v fixture, P9)

A small synthetic project that looks like an existing one: specs in `sdd/` in a team's own Spanish
format (an RF table with a Componente column, an RNF table, user stories, Spanish Gherkin, an
OpenAPI file and one prose file), a FastAPI backend whose routes sit under a settings prefix, a
TypeScript frontend, SQL with migrations, and Terraform. No `ad2v:` annotation anywhere. Used to
measure `ad2v init` against a zero-config `ad2v extract` (docs/reports/P9.md).
