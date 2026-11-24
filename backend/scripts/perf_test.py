"""Performance measurement: a ~1,000-page digital PDF through the whole pipeline, plus API latency.

Runs in-process (Celery eager) against a real PostgreSQL, so the numbers show pipeline compute cost
without broker overhead. Writes the measured numbers to docs/perf_results.json.
"""

from __future__ import annotations

import json
import os
import platform
import random
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def rss_mb() -> float:
    with open("/proc/self/status") as fh:
        for line in fh:
            if line.startswith("VmRSS"):
                return int(line.split()[1]) / 1024
    return 0.0


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * p))]


def main(pages_target: int = 1000) -> None:
    import pgserver

    tmp = Path(tempfile.mkdtemp(prefix="docint-perf-"))
    pg = pgserver.get_server(tmp / "pg", cleanup_mode="stop")
    os.environ.update(
        {
            "DATABASE_URL": pg.get_uri().replace("postgresql://", "postgresql+psycopg://"),
            "STORAGE_DIR": str(tmp / "storage"),
            "APP_ENV": "test",
            "CELERY_EAGER": "true",
            "LOG_LEVEL": "ERROR",
            "LOG_JSON": "false",
            "JWT_SECRET": "perf-only-secret-0123456789-0123456789",
            "ADMIN_EMAIL": "admin@example.com",
            "ADMIN_PASSWORD": "perf-admin-password",
            "RATE_LIMIT_PER_MINUTE": "100000",
            "MAX_PAGES_PER_DOCUMENT": "3000",
        }
    )
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True, capture_output=True)

    from fastapi.testclient import TestClient

    from app.devtools import synthetic as syn
    from app.main import create_app
    from app.tasks.celery_app import celery_app

    celery_app.conf.task_always_eager = True
    rng = random.Random(1)
    invoices = []
    pages = 0
    while pages < pages_target:
        inv = syn.random_invoice(rng, len(invoices))
        inv.items = [(f"Item {i}", inv.items[0][1], inv.items[0][2]) for i in range(8)]
        inv.items_per_page = 3  # 8 items -> 3 pages per invoice
        invoices.append(inv)
        pages += 3
    t0 = time.perf_counter()
    pdf = syn.make_pdf(invoices)
    gen_s = time.perf_counter() - t0
    print(f"generated {pages}-page PDF ({len(pdf) / 1e6:.1f} MB, {len(invoices)} invoices) in {gen_s:.1f}s")

    out: dict[str, Any] = {
        "environment": {
            "python": platform.python_version(),
            "cpus": os.cpu_count(),
            "platform": platform.platform(),
            "note": "single process, eager Celery (no broker), PostgreSQL 16 on the same machine",
        },
        "document": {"pages": pages, "invoices": len(invoices), "size_mb": round(len(pdf) / 1e6, 2)},
    }
    with TestClient(create_app()) as c:
        token = c.post(
            "/api/v1/auth/login", json={"email": "admin@example.com", "password": "perf-admin-password"}
        ).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        rss_before = rss_mb()
        t0 = time.perf_counter()
        r = c.post("/api/v1/documents", headers=h, files=[("files", ("big.pdf", pdf, "application/pdf"))])
        total_s = time.perf_counter() - t0
        doc_id = r.json()["results"][0]["document_id"]
        st = c.get(f"/api/v1/documents/{doc_id}/status", headers=h).json()
        rss_after = rss_mb()
        found = [
            x for x in c.get(f"/api/v1/documents/{doc_id}/extractions", headers=h).json() if x["doc_type"] == "invoice"
        ]
        out["pipeline"] = {
            "status": st["status"],
            "wall_seconds": round(total_s, 1),
            "pages_per_second": round(pages / total_s, 1),
            "invoices_extracted": len(found),
            "invoices_expected": len(invoices),
            "rss_mb_before": round(rss_before),
            "rss_mb_after": round(rss_after),
            "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
        }
        print(json.dumps(out["pipeline"], indent=2))

        def latency(method: str, path: str, n: int = 200, **kw: Any) -> dict[str, float]:
            times = []
            for _ in range(n):
                t = time.perf_counter()
                resp = c.request(method, path, headers=h, **kw)
                assert resp.status_code == 200, (path, resp.text[:200])
                times.append((time.perf_counter() - t) * 1000)
            return {
                "n": n,
                "p50_ms": round(statistics.median(times), 1),
                "p95_ms": round(pct(times, 0.95), 1),
                "max_ms": round(max(times), 1),
            }

        out["api_latency_with_%d_indexed_pages" % pages] = {
            "GET /documents": latency("GET", "/api/v1/documents"),
            "GET /documents/{id}/status": latency("GET", f"/api/v1/documents/{doc_id}/status"),
            "GET /invoices (filtered)": latency("GET", "/api/v1/invoices", params={"supplier": "a", "size": 25}),
            "GET /search keyword": latency(
                "GET", "/api/v1/search", n=100, params={"q": "invoice total", "mode": "keyword"}
            ),
            "GET /search semantic": latency(
                "GET", "/api/v1/search", n=100, params={"q": "invoice total", "mode": "semantic"}
            ),
            "GET /search hybrid": latency(
                "GET", "/api/v1/search", n=100, params={"q": "invoice total", "mode": "hybrid"}
            ),
            "GET /stats/dashboard": latency("GET", "/api/v1/stats/dashboard", n=50),
        }
        for k, v in out["api_latency_with_%d_indexed_pages" % pages].items():
            print(f"{k:32s} p50={v['p50_ms']:7.1f} ms  p95={v['p95_ms']:7.1f} ms")
    dest = BACKEND.parent / "docs" / "perf_results.json"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(out, indent=2))
    print("written", dest)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1000)
