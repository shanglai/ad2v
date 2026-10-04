# ADR-0057: Security of the chat endpoint, and the one unseeded random value

- Status: accepted (P7)
- Context: `/api/chat/*` spends the user's money and reads their map. Any web page the user
  visits can send requests to `127.0.0.1`.
- Decisions:
  1. **Bind** 127.0.0.1 only, as before.
  2. **Per-launch token:** `secrets.token_urlsafe(32)`. It reaches the page in the URL fragment
     (`…/index.html?file=project.ad2v#chat=<token>`), which browsers never send to a server, so it
     stays out of logs and Referer. Every `/api/chat/*` call must send it as `X-Ad2v-Token`; the
     comparison is constant-time. Missing or wrong → 401.
  3. **Host** must be `127.0.0.1:<port>` or `localhost:<port>`, against DNS rebinding → 403.
  4. **Origin**, when present, must be that same origin. It is required on POST (browsers always
     send it there) → 403.
  5. **POST** requires `Content-Type: application/json` (415) and a body of at most 16 KB (413).
     A cross-site form can't send that content type without a preflight, and the preflight fails:
     `OPTIONS` → 405, and the server never sends CORS headers.
  6. POST is accepted only under `/api/chat/`. The file and the viewer stay GET/HEAD only.
  7. Without `--chat` the endpoints don't exist (404), except `GET /api/chat/session`, which
     returns `{enabled: false, command}` so the panel can show how to turn the chat on.
- **Seed rule exception.** Randomness in logic, tests and sampling uses seed 987654. The chat
  token is a security secret and uses `secrets`, never a seed. This is the only exception.
- Tested: every rejection path (bad Host, bad Origin, missing Origin on POST, missing token,
  wrong token, wrong content type, oversized body, OPTIONS, POST outside the API, an empty
  question), the success paths for both host names, SSE framing over chunked transfer, and the
  disabled state.
