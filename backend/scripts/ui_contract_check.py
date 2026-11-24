"""Frontend <-> backend contract check against the REAL running stack.

1. Starts PostgreSQL, Redis, a Celery worker, the API and the built Next.js frontend.
2. Verifies every page route is served and the CORS rules (allowed origin vs foreign origin).
3. For every TypeScript interface in frontend/lib/api.ts, fetches a real API response and verifies that all
   required properties exist. This catches the classic bug where the UI reads a field the API does not send.
Run (after `npm run build` in frontend/):  python scripts/ui_contract_check.py
"""

from __future__ import annotations

import random
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from decimal import Decimal  # noqa: E402

from e2e_real_stack import Client, Stack, check, free_port  # noqa: E402

from app.devtools import synthetic as syn  # noqa: E402

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


def parse_interfaces(ts: str) -> dict[str, dict[str, bool]]:
    """interface name -> {property: is_required} (top-level properties only; follows `extends`)."""
    out: dict[str, dict[str, bool]] = {}
    extends: dict[str, str] = {}
    for m in re.finditer(r"export interface (\w+)(?: extends (\w+))? \{", ts):
        name, parent = m.group(1), m.group(2)
        depth, i, props = 1, m.end(), {}
        start = i
        body = ""
        while depth:
            ch = ts[i]
            depth += (ch == "{") - (ch == "}")
            i += 1
        body = ts[start : i - 1]
        depth = 0
        token = ""
        for ch in body:
            if ch in "{<([":
                depth += 1
            elif ch in "})>]":
                depth -= 1
            if depth == 0 and ch in ";\n":
                pm = re.match(r"\s*(\w+)(\?)?\s*:", token)
                if pm:
                    props[pm.group(1)] = pm.group(2) is None
                token = ""
            else:
                token += ch
        pm = re.match(r"\s*(\w+)(\?)?\s*:", token)
        if pm:
            props[pm.group(1)] = pm.group(2) is None
        out[name] = props
        if parent:
            extends[name] = parent
    for child, parent in extends.items():
        out[child] = {**out[parent], **out[child]}
    return out


def main() -> None:
    interfaces = parse_interfaces((FRONTEND / "lib" / "api.ts").read_text())
    stack = Stack()
    web: subprocess.Popen[bytes] | None = None
    try:
        base, email, pw = stack.start()
        web_port = free_port()
        # NEXT_PUBLIC_API_URL was baked in at build time (default http://localhost:8000); the browser would call that.
        web = subprocess.Popen(
            ["npx", "next", "start", "-p", str(web_port)],
            cwd=FRONTEND,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(60):
            try:
                if httpx.get(f"http://127.0.0.1:{web_port}/login", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)

        # ---- 1. pages are served ------------------------------------------------------------------------
        for route in [
            "/",
            "/login",
            "/dashboard",
            "/upload",
            "/documents",
            "/documents/abc",
            "/compare",
            "/search",
            "/history",
        ]:
            r = httpx.get(f"http://127.0.0.1:{web_port}{route}", follow_redirects=True, timeout=20)
            check(r.status_code == 200 and "<html" in r.text, f"frontend route {route} -> HTTP {r.status_code}")
        hdr = httpx.get(f"http://127.0.0.1:{web_port}/login").headers
        check(
            hdr.get("x-frame-options") == "DENY" and hdr.get("x-content-type-options") == "nosniff",
            "frontend sends security headers",
        )

        # ---- 2. CORS ----------------------------------------------------------------------------------------
        pre = httpx.options(
            f"{base}/api/v1/auth/login",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,authorization",
            },
        )
        check(
            pre.status_code == 200 and pre.headers.get("access-control-allow-origin") == "http://localhost:3000",
            "CORS preflight allows the frontend origin",
        )
        evil = httpx.options(
            f"{base}/api/v1/auth/login",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        check("access-control-allow-origin" not in evil.headers, "CORS preflight refuses a foreign origin")
        patch = httpx.options(
            f"{base}/api/v1/documents/x",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "PATCH"},
        )
        check(
            "PATCH" in patch.headers.get("access-control-allow-methods", ""),
            "CORS allows PATCH (needed for corrections)",
        )

        # ---- 3. type contract ---------------------------------------------------------------------------------
        c = Client(base, email, pw)
        rng = random.Random(5)
        good = syn.random_invoice(rng, 1)
        bad = syn.random_invoice(rng, 2)
        bad.total_override = bad.subtotal + bad.tax + Decimal(7)
        good_id = c.upload("good.pdf", syn.make_pdf([good]))
        bad_id = c.upload("bad.pdf", syn.make_pdf([bad]))
        sheet_id = c.upload("register.xlsx", syn.make_xlsx([good, bad], "summary"))
        for d in (good_id, bad_id, sheet_id):
            c.wait(d)
        lg = c.logicals(bad_id)[0]
        c.http.patch(
            f"/logical-documents/{lg['id']}/fields/customer_name", json={"value": "Contract Check Ltd", "reason": "x"}
        ).raise_for_status()
        lg = c.logicals(bad_id)[0]
        comparison = c.http.post(
            "/comparisons", json={"left_document_id": bad_id, "right_document_id": sheet_id}
        ).json()

        def get(path: str) -> Any:
            r = c.http.get(path)
            r.raise_for_status()
            return r.json()

        samples: dict[str, Any] = {
            "User": get("/auth/me"),
            "DocumentRow": get("/documents")["items"][0],
            "UploadItemResult": c.http.post("/documents", files=[("files", ("good.pdf", syn.make_pdf([good])))]).json()[
                "results"
            ][0],
            "DocStatus": get(f"/documents/{bad_id}/status"),
            "ProcEvent": get(f"/documents/{bad_id}/history")[0],
            "Logical": lg,
            "Field": lg["fields"][0],
            "LineItem": lg["line_items"][0],
            "ValidationIssue": lg["validation"][0],
            "Correction": lg["corrections"][0],
            "PageInfo": get(f"/documents/{bad_id}/pages")["items"][0],
            "PageDetail": get(f"/documents/{bad_id}/pages/1"),
            "InvoiceRow": get("/invoices")["items"][0],
            "SearchHit": get("/search?q=invoice&mode=hybrid")[0],
            "ComparisonDetail": comparison,
            "ComparePair": comparison["pairs"][0],
            "CompareItem": comparison["pairs"][0]["items"][0],
            "ComparisonRow": get("/comparisons")["items"][0],
            "Dashboard": get("/stats/dashboard"),
            "AuditEntry": get("/audit-log")[0],
        }
        checked = 0
        for name, sample in samples.items():
            required = {p for p, req in interfaces[name].items() if req}
            missing = required - set(sample)
            check(
                not missing,
                f"TypeScript interface {name}: all {len(required)} required properties present in the real API response"
                + (f" — MISSING {sorted(missing)}" if missing else ""),
            )
            checked += 1
        # paginated envelopes
        for path in ("/documents", "/invoices", "/comparisons", f"/documents/{bad_id}/pages"):
            check({"items", "total", "page", "size"} <= set(get(path)), f"{path} returns the Paginated envelope")
        print(f"\nCONTRACT OK: {checked} interfaces verified, {len(interfaces)} parsed")
    finally:
        if web and web.poll() is None:
            web.terminate()
        stack.stop()
        print(f"(logs kept in {stack.tmp})")


if __name__ == "__main__":
    main()
