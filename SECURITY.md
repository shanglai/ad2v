# Security policy

> **Private repository for now.** ad2v is not published yet. Until the public repository exists,
> report issues directly to the owner through the private channel you received access
> from; do not open public issues for vulnerabilities. This file will be updated with a public
> contact (GitHub private vulnerability reporting) when the project is published.

## Supported versions

Only the latest version (`0.7.0`, branch `main`) receives fixes.

## Reporting a vulnerability

Please include: the ad2v version (`ad2v --version`), the command or file that triggers the issue,
and what an attacker gains. Expect an acknowledgement within 7 days. Please give us a reasonable
time to fix the issue before disclosing it.

In scope: anything in `docs/security.md`: hostile `.ad2v` files, the local viewer server and chat
endpoint, the MCP server, prompt injection that leads to a write or to spending beyond the budget,
plug-in isolation claims, path traversal, and the dependency chain.

Out of scope: issues that need a plug-in the user enabled (plug-ins are trusted code by design), a
compromised local machine, or the user's own model provider.

The threat model and the current list of known, accepted risks: [`docs/security.md`](docs/security.md).
