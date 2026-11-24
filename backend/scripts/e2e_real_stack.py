"""End-to-end test against a REAL stack: PostgreSQL + Redis + Celery worker process + API server.

Two modes:
  python scripts/e2e_real_stack.py                    # starts everything locally (needs redis-server + pgserver)
  python scripts/e2e_real_stack.py --base-url http://localhost:8000 --email a@b.c --password ...
                                                      # tests an already-running stack (e.g. docker compose)
The local mode also kills the worker with SIGKILL mid-OCR to prove the stalled-document recovery works.
"""

from __future__ import annotations

import argparse
import os
import random
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.devtools import synthetic as syn  # noqa: E402

FINAL = {"completed", "needs_review", "failed", "rejected"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Stack:
    def __init__(self) -> None:
        self.procs: list[subprocess.Popen[bytes]] = []
        self.worker: subprocess.Popen[bytes] | None = None
        self.tmp = Path(tempfile.mkdtemp(prefix="docint-e2e-"))

    def start(self) -> tuple[str, str, str]:
        import pgserver

        self.pg = pgserver.get_server(self.tmp / "pg", cleanup_mode="stop")
        db = self.pg.get_uri().replace("postgresql://", "postgresql+psycopg://")
        redis_port, api_port = free_port(), free_port()
        self.env = {
            **os.environ,
            "DATABASE_URL": db,
            "REDIS_URL": f"redis://127.0.0.1:{redis_port}/0",
            "STORAGE_DIR": str(self.tmp / "storage"),
            "APP_ENV": "test",
            "LOG_JSON": "false",
            "LOG_LEVEL": "INFO",
            "JWT_SECRET": "e2e-only-secret-0123456789-0123456789",
            "ADMIN_EMAIL": "admin@example.com",
            "ADMIN_PASSWORD": "e2e-admin-password",
            "CELERY_EAGER": "false",
            "STALLED_AFTER_MINUTES": "0.15",
            "REQUEUE_INTERVAL_SECONDS": "5",
            "PYTHONPATH": str(BACKEND),
        }
        self._spawn(["redis-server", "--port", str(redis_port), "--save", "", "--appendonly", "no"], "redis")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            env=self.env,
            check=True,
            capture_output=True,
        )
        self.start_worker()
        self._spawn(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(api_port), "--log-level", "warning"], "api"
        )
        base = f"http://127.0.0.1:{api_port}"
        for _ in range(60):
            try:
                if httpx.get(f"{base}/health/ready", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            raise RuntimeError("API did not become ready")
        return base, "admin@example.com", "e2e-admin-password"

    def start_worker(self) -> None:
        self.worker = self._spawn(
            [
                sys.executable,
                "-m",
                "celery",
                "-A",
                "app.tasks.celery_app:celery_app",
                "worker",
                "-B",
                "-Q",
                "parse,ocr,llm",
                "-c",
                "2",
                "--loglevel=WARNING",
                "-n",
                f"w{time.time_ns()}@%h",
            ],
            "worker",
        )

    def kill_worker_hard(self) -> None:
        assert self.worker is not None
        os.killpg(os.getpgid(self.worker.pid), signal.SIGKILL)  # no graceful shutdown: in-flight messages are lost
        self.worker.wait()

    def _spawn(self, cmd: list[str], name: str) -> subprocess.Popen[bytes]:
        log = open(self.tmp / f"{name}.log", "ab")  # noqa: SIM115
        p = subprocess.Popen(cmd, cwd=BACKEND, env=self.env, stdout=log, stderr=log, start_new_session=True)
        self.procs.append(p)
        return p

    def stop(self) -> None:
        for p in self.procs:
            if p.poll() is None:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass


class Client:
    def __init__(self, base: str, email: str, password: str) -> None:
        self.http = httpx.Client(base_url=f"{base}/api/v1", timeout=60)
        token = self.http.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]
        self.http.headers["Authorization"] = f"Bearer {token}"

    def upload(self, name: str, data: bytes) -> str:
        r = self.http.post("/documents", files=[("files", (name, data))])
        r.raise_for_status()
        return str(r.json()["results"][0]["document_id"])

    def wait(self, doc_id: str, timeout: float = 240) -> dict[str, Any]:
        end = time.time() + timeout
        while time.time() < end:
            st: dict[str, Any] = self.http.get(f"/documents/{doc_id}/status").json()
            if st["status"] in FINAL:
                return st
            time.sleep(0.5)
        raise TimeoutError(f"{doc_id} still {st['status']}")  # noqa: F821

    def logicals(self, doc_id: str) -> list[dict[str, Any]]:
        return self.http.get(f"/documents/{doc_id}/extractions").json()  # type: ignore[no-any-return]


def check(cond: bool, message: str) -> None:
    print(("PASS  " if cond else "FAIL  ") + message)
    if not cond:
        raise SystemExit(1)


def run(c: Client, stack: Stack | None) -> None:
    rng = random.Random(7)
    invs = [syn.random_invoice(rng, i) for i in range(1, 9)]
    bundle_id = c.upload("bundle.pdf", syn.make_pdf(invs, filler_pages=2))
    scan_inv = syn.random_invoice(rng, 20)
    scan_id = c.upload(
        "scan.pdf",
        syn.make_scanned_pdf(syn.make_pdf([scan_inv, syn.random_invoice(rng, 21)]), 150, rotate=1.0, blur=0.5, noise=6),
    )
    xlsx_id = c.upload("register.xlsx", syn.make_xlsx(invs[:4], "summary"))
    csv_id = c.upload("data.csv", syn.make_csv(invs[:2]))
    results = {k: c.wait(v) for k, v in {"bundle": bundle_id, "scan": scan_id, "xlsx": xlsx_id, "csv": csv_id}.items()}
    check(
        all(r["status"] in ("completed", "needs_review") for r in results.values()),
        f"all four documents finished: { {k: r['status'] for k, r in results.items()} }",
    )
    got = [lg for lg in c.logicals(bundle_id) if lg["doc_type"] == "invoice"]
    check(len(got) == 8, "bundle PDF was split into 8 invoices by separate worker processes")
    numbers = [next(f["value"] for f in lg["fields"] if f["name"] == "invoice_number") for lg in got]
    check(numbers == [i.invoice_number for i in invs], "every invoice number extracted correctly, in order")
    check(len(c.logicals(xlsx_id)) == 4 and len(c.logicals(csv_id)) == 2, "spreadsheet and CSV records extracted")
    scan_page = c.http.get(f"/documents/{scan_id}/pages/1").json()
    check(scan_page["method"] == "ocr", "scanned PDF went through the OCR queue")

    if stack is not None:
        # --- crash test: SIGKILL the worker in the middle of OCR ------------------------------------------
        big = syn.make_scanned_pdf(
            syn.make_pdf([syn.random_invoice(rng, 30 + i) for i in range(6)]), 150, rotate=1.5, blur=0.5, noise=6
        )
        crash_id = c.upload("crash.pdf", big)
        time.sleep(4)
        mid = c.http.get(f"/documents/{crash_id}/status").json()
        check(
            mid["status"] == "processing",
            f"document is mid-flight when the worker is killed ({mid['pages_done']}/{mid['page_count']} pages done)",
        )
        stack.kill_worker_hard()
        print("      worker killed with SIGKILL; starting a replacement worker")
        stack.start_worker()
        final = c.wait(crash_id, 300)
        check(
            final["status"] in ("completed", "needs_review"), f"document recovered after the crash -> {final['status']}"
        )
        ls = [lg for lg in c.logicals(crash_id) if lg["doc_type"] == "invoice"]
        check(len(ls) == 6, "all 6 invoices were recovered after the worker crash")
        events = c.http.get(f"/documents/{crash_id}/history").json()
        print("      recovery events:", [e["message"] for e in events if e["stage"] == "recovery"])
    dash = c.http.get("/stats/dashboard").json()
    print("      dashboard:", {k: dash[k] for k in ("documents_total", "by_status", "pages_processed", "pages_ocr")})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url")
    ap.add_argument("--email", default="admin@example.com")
    ap.add_argument("--password")
    args = ap.parse_args()
    if args.base_url:
        run(Client(args.base_url, args.email, args.password), None)
        return
    stack = Stack()
    try:
        base, email, pw = stack.start()
        run(Client(base, email, pw), stack)
        print("\nALL CHECKS PASSED")
    finally:
        stack.stop()
        print(f"(logs kept in {stack.tmp})")


if __name__ == "__main__":
    main()
