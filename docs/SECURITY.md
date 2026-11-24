# Security

Uploaded documents are **untrusted data**. Nothing inside a document can change the application's behaviour, grant a permission or approve itself.

## Controls implemented (and where they are tested: `tests/test_security_api.py` unless noted)

| Risk | Control |
|---|---|
| Executable/hostile file with a harmless extension | File type is decided from the **content** (magic bytes) and must match the extension; allow-list only |
| Path traversal / hostile filenames | Original name is sanitised and used for display only; storage path is the SHA-256 (`objects/ab/cd/<hash>.ext`); `resolve()` refuses paths outside the storage directory |
| Oversized uploads | Size limit enforced **while streaming** (temp file removed on failure); request-size guard; max files per request; max pages per document |
| Zip bombs / macro workbooks / XML tricks | XLSX uncompressed-size and ratio limits, unsafe member paths rejected, `vbaProject.bin` rejected, `defusedxml` installed so `openpyxl` parses XML safely |
| Decompression-bomb images | pixel limit checked before decoding (`MAX_IMAGE_PIXELS`) |
| Malicious/damaged PDFs | opened only by the PDF parser in a worker (no JavaScript is ever executed); encrypted rejected; repaired files forced to human review; original served with `Content-Security-Policy: sandbox` and `nosniff` |
| Broken authentication | scrypt password hashes (random salt, constant-time compare); JWT (HS256, 60 min) with required `exp`/`sub`; `alg: none` and wrong-secret tokens rejected; account state re-checked on every request; login timing does not reveal whether a user exists |
| Broken authorisation | roles `viewer < reviewer < admin` enforced per endpoint (see API_DOCUMENTATION); admin-only: delete, users, audit log |
| Brute force / abuse | per-IP login limit (10/min) and per-user API limit (240/min), Redis-backed so it holds across processes; `Retry-After` header |
| Injection | all SQL through SQLAlchemy bound parameters; LIKE wildcards in filters are escaped; sort keys are allow-listed; search text goes through `websearch_to_tsquery` |
| XSS | React escapes all output; search highlights use `[[[ ]]]` markers split into text nodes, never HTML; no `dangerouslySetInnerHTML` |
| **Prompt injection via document text** | see ARCHITECTURE.md: delimited untrusted data, strict output schema, grounding, deterministic decisions (`tests/test_review_and_failures.py`) |
| Secrets | only environment variables; `.env` is git-ignored; production refuses to start without a ≥32-char `JWT_SECRET`; `detect-private-key` pre-commit hook |
| Error leakage | consistent error envelope; unexpected errors return a generic message (details only in server logs) |
| Accountability | `audit_log` (logins, failed logins, uploads, rejections, corrections, approvals, deletions, comparisons, user creation) and per-document `processing_events` |
| Container | non-root users in both images; DB/Redis not exposed publicly (DB bound to 127.0.0.1 for local testing only) |

## Known weaknesses / not implemented — please read

1. **Token storage:** the JWT lives in `localStorage` (readable by any script on the origin). There is no refresh token, logout-all or revocation list.
   For production prefer an httpOnly, `Secure`, `SameSite` cookie plus CSRF protection.
2. **No TLS termination** is included. Put a reverse proxy (Caddy/nginx/Traefik) with HTTPS in front; set `CORS_ORIGINS` to your real origin.
3. **No per-file sandbox:** parsers (MuPDF, Pillow, Tesseract, openpyxl) run inside the worker process with the container's privileges. A parser vulnerability in a hostile file could compromise the worker.
   Mitigations to add: gVisor/seccomp profile, read-only root filesystem, no outbound network for workers that do not call an LLM, resource limits per task.
4. **No antivirus scanning** of uploads (e.g. ClamAV).
5. **No password policy beyond length ≥ 10**, no password reset or user-management UI (users are created by an admin via the API), no MFA.
6. **Encryption at rest** is not configured (database volume, storage volume).
7. **Free LLM tiers** (e.g. Gemini free) may use submitted prompts for model improvement. Do not send confidential or personal data. The default `heuristic` provider sends nothing anywhere.
8. Rate limiting uses client IP; behind a proxy configure it to pass the real client address (`X-Forwarded-For` is not trusted automatically).
9. Dependency versions are lower-bounded in `pyproject.toml`; `backend/constraints-tested.txt` records the versions the tests ran against. No automated vulnerability scanning is configured yet.
10. PyMuPDF is AGPL-licensed (see README "Licensing note").

## Reporting
This is a portfolio project; open an issue or contact the repository owner.
