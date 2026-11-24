"""Authentication, authorisation, upload hardening, rate limiting and error format."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from typing import Any

import jwt
import pytest

from app.devtools import synthetic as syn
from tests.conftest import PASSWORD, Uploader


def test_unauthenticated_requests_are_rejected(client: Any) -> None:
    for method, path in [
        ("get", "/api/v1/documents"),
        ("get", "/api/v1/search?q=x"),
        ("post", "/api/v1/comparisons"),
        ("get", "/api/v1/stats/dashboard"),
        ("get", "/api/v1/audit-log"),
    ]:
        r = getattr(client, method)(path)
        assert r.status_code == 401, path
        assert r.json()["error"]["code"] == "unauthorized"
    assert client.get("/health").json() == {"status": "ok"}


def test_login_does_not_reveal_whether_user_exists(client: Any, make_user: Any) -> None:
    make_user("viewer")
    wrong_pw = client.post("/api/v1/auth/login", json={"email": "viewer@example.com", "password": "nope-nope-nope"})
    no_user = client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()


def test_forged_and_expired_tokens_are_rejected(client: Any, auth: dict[str, str], settings_override: Any) -> None:
    from app.core.config import get_settings

    secret = get_settings().jwt_secret
    none_alg = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"sub": "1", "exp": 4102444800}).encode()).rstrip(b"=").decode()
    forged = [
        f"{none_alg}.{payload}.",
        jwt.encode(
            {"sub": "1", "exp": 4102444800},
            "wrong-secret-wrong-secret-wrong-secret",
            algorithm="HS256",
        ),
        jwt.encode({"sub": "1", "exp": 1}, secret, algorithm="HS256"),
        "garbage",
    ]
    for token in forged:
        r = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, token


def test_role_permissions(client: Any, make_user: Any, rng: Any) -> None:
    viewer, reviewer, admin = make_user("viewer"), make_user("reviewer"), make_user("admin")
    up = Uploader(client, reviewer)
    doc_id = up.one("a.pdf", syn.make_pdf([syn.random_invoice(rng, 1)]))
    assert client.delete(f"/api/v1/documents/{doc_id}", headers=reviewer).status_code == 403
    assert client.delete(f"/api/v1/documents/{doc_id}", headers=viewer).status_code == 403
    assert client.get("/api/v1/audit-log", headers=reviewer).status_code == 403
    assert (
        client.post(
            "/api/v1/users",
            headers=reviewer,
            json={"email": "x@y.com", "password": "a-long-password", "role": "admin"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/users",
            headers=admin,
            json={"email": "new@y.com", "password": "a-long-password", "role": "viewer"},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/users",
            headers=admin,
            json={"email": "weak@y.com", "password": "short", "role": "viewer"},
        ).status_code
        == 422
    )
    assert client.delete(f"/api/v1/documents/{doc_id}", headers=admin).status_code == 204
    assert client.get(f"/api/v1/documents/{doc_id}", headers=admin).status_code == 404
    actions = {a["action"] for a in client.get("/api/v1/audit-log", headers=admin).json()}
    assert {"login", "upload", "delete_document", "create_user"} <= actions


def test_login_rate_limit(client: Any, make_user: Any) -> None:
    make_user("viewer")
    codes = [
        client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "bad-bad-bad-bad"},
        ).status_code
        for _ in range(14)
    ]
    assert 429 in codes and codes[0] == 401
    assert (
        client.post("/api/v1/auth/login", json={"email": "viewer@example.com", "password": PASSWORD}).status_code == 429
    )


def test_api_rate_limit(client: Any, auth: dict[str, str], settings_override: Any) -> None:
    settings_override(RATE_LIMIT_PER_MINUTE="5")
    codes = [client.get("/api/v1/documents", headers=auth).status_code for _ in range(8)]
    assert codes[:5] == [200] * 5 and set(codes[5:]) == {429}
    r = client.get("/api/v1/documents", headers=auth)
    assert r.headers["retry-after"] == "60" and r.json()["error"]["code"] == "rate_limited"
    assert client.get("/health").status_code == 200  # health checks are exempt


def test_upload_hardening(upload: Uploader, rng: Any, settings_override: Any) -> None:
    pdf = syn.make_pdf([syn.random_invoice(rng, 1)])
    # hostile filenames never influence where the file is stored
    res = upload(("../../../etc/passwd.pdf", pdf))[0]
    assert res["status"] == "accepted"
    doc = upload.doc(res["document_id"])
    assert doc["original_filename"] == "passwd.pdf" and "/" not in doc["original_filename"]
    # extension / content mismatches
    assert upload(("fake.pdf", b"\x89PNG\r\n\x1a\n" + b"0" * 100), expect=422)[0]["status"] == "rejected"
    assert upload(("fake.png", pdf), expect=422)[0]["status"] == "rejected"
    assert upload(("empty.pdf", b""), expect=422)[0]["reason"] == "File is empty."
    # executable renamed
    assert "does not match" in upload(("setup.xlsx", b"MZ\x90\x00" + b"0" * 64), expect=422)[0]["reason"]
    # polyglot: ZIP that is not a workbook
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("evil.txt", "x")
    assert "not an Excel workbook" in upload(("a.xlsx", buf.getvalue()), expect=422)[0]["reason"]
    # macro-enabled content hidden in an .xlsx
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/workbook.xml", "<workbook/>")
        zf.writestr("xl/vbaProject.bin", b"macro")
    assert "Macro" in upload(("m.xlsx", buf.getvalue()), expect=422)[0]["reason"]
    # binary content posing as CSV
    assert upload(("x.csv", b"\x00\x01\x02\x03" * 10), expect=422)[0]["status"] == "rejected"


def test_zip_bomb_is_rejected(upload: Uploader, settings_override: Any) -> None:
    settings_override(MAX_ZIP_UNCOMPRESSED_MB="5")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/workbook.xml", "<workbook/>")
        zf.writestr("xl/sharedStrings.xml", b"A" * (20 * 1024 * 1024))
    assert buf.tell() < 200_000  # tiny on disk, huge when expanded
    res = upload(("bomb.xlsx", buf.getvalue()), expect=422)[0]
    assert "zip bomb" in res["reason"]


def test_oversized_upload_is_rejected_while_streaming(upload: Uploader, settings_override: Any, rng: Any) -> None:
    settings_override(MAX_UPLOAD_MB="1")
    big = syn.make_pdf([syn.random_invoice(rng, 1)]) + b"0" * (1_100_000)
    res = upload(("big.pdf", big), expect=422)[0]
    assert res["status"] == "rejected" and "1 MB" in res["reason"]
    import os

    from app.core.config import get_settings

    leftovers = list((get_settings().storage_dir / "tmp").glob("*"))
    assert leftovers == [], f"temp files must be cleaned up: {leftovers} {os.getpid()}"


def test_decompression_bomb_image_is_rejected(upload: Uploader, settings_override: Any) -> None:
    from PIL import Image

    settings_override(MAX_IMAGE_PIXELS="1000000")
    buf = io.BytesIO()
    Image.new("L", (4000, 4000), 255).save(buf, format="PNG")  # tiny file, 16 megapixels
    res = upload(("huge.png", buf.getvalue()))[0]
    assert upload.status(res["document_id"])["status"] == "rejected"


def test_too_many_files_and_error_envelope(upload: Uploader, settings_override: Any, rng: Any) -> None:
    settings_override(MAX_FILES_PER_REQUEST="2")
    pdf = syn.make_pdf([syn.random_invoice(rng, 1)])
    r = upload.client.post(
        "/api/v1/documents",
        headers=upload.headers,
        files=[("files", (f"{i}.pdf", pdf, "x")) for i in range(3)],
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_many_files"
    r = upload.client.get("/api/v1/documents/not-a-uuid", headers=upload.headers)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    r = upload.client.get("/api/v1/nope", headers=upload.headers)
    assert r.status_code == 404 and "error" in r.json()


def test_security_headers_and_no_error_leakage(client: Any, auth: dict[str, str]) -> None:
    r = client.get("/api/v1/documents", headers=auth)
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store" and r.headers["x-request-id"]
    r = client.get("/api/v1/documents?size=1000", headers=auth)
    assert r.status_code == 422
    assert "Traceback" not in r.text


def test_sql_injection_attempts_are_harmless(upload: Uploader, rng: Any) -> None:
    upload.one("a.pdf", syn.make_pdf([syn.random_invoice(rng, 1)]))
    for payload in ["' OR '1'='1", "'; DROP TABLE documents;--", "%' --"]:
        r = upload.client.get(
            "/api/v1/invoices",
            headers=upload.headers,
            params={"supplier": payload, "invoice_number": payload},
        )
        assert r.status_code == 200 and r.json()["total"] == 0
    r = upload.client.get("/api/v1/documents", headers=upload.headers, params={"q": "'; DROP TABLE documents;--"})
    assert r.status_code == 200
    assert upload.client.get("/api/v1/documents", headers=upload.headers).json()["total"] == 1
    r = upload.client.get("/api/v1/invoices", headers=upload.headers, params={"sort": "id; DROP TABLE users"})
    assert r.status_code == 200  # unknown sort keys fall back to a safe default


@pytest.mark.parametrize("path", ["/api/v1/documents/00000000-0000-0000-0000-000000000000/file"])
def test_missing_resources_return_404(upload: Uploader, path: str) -> None:
    assert upload.client.get(path, headers=upload.headers).status_code == 404
