"""Search (keyword/semantic/hybrid/filters) and cross-document verification tests."""

from __future__ import annotations

import random
from datetime import date
from decimal import Decimal
from typing import Any

from app.devtools import synthetic as syn
from tests.conftest import Uploader


def make(
    rng: random.Random,
    i: int,
    supplier: str,
    items: list[tuple[str, int, str]],
    d: date,
    cur: str = "USD",
) -> syn.SyntheticInvoice:
    inv = syn.random_invoice(rng, i, supplier=supplier)
    inv.items = [(n, Decimal(q), Decimal(p)) for n, q, p in items]
    inv.invoice_date, inv.currency = d, cur
    return inv


def test_search_modes_and_filters(upload: Uploader, rng: random.Random) -> None:
    a = make(rng, 1, "Zephyr Plumbing Ltd", [("Copper pipe fittings", 4, "12.50")], date(2025, 2, 10))
    b = make(rng, 2, "Quokka Catering Co", [("Banquet catering service", 1, "950.00")], date(2025, 6, 20))
    c = make(
        rng,
        3,
        "Zephyr Plumbing Ltd",
        [("Emergency drain repair", 1, "300.00")],
        date(2025, 9, 5),
        "EUR",
    )
    ids = [upload.one(f"{i}.pdf", syn.make_pdf([inv])) for i, inv in enumerate((a, b, c))]
    get = lambda **p: upload.client.get("/api/v1/search", headers=upload.headers, params=p)  # noqa: E731

    r = get(q="plumbing", mode="keyword").json()
    assert {h["document_id"] for h in r} == {ids[0], ids[2]}
    assert "[[[" in r[0]["snippet"] or "Plumbing" in r[0]["snippet"]  # highlight markers, never raw HTML
    assert r[0]["logical"]["supplier_name"] == "Zephyr Plumbing Ltd"

    r = get(q="catering banquet", mode="semantic").json()
    assert r[0]["document_id"] == ids[1] and r[0]["sources"] == ["semantic"]

    r = get(q="drain repair", mode="hybrid").json()
    assert r[0]["document_id"] == ids[2]
    assert set(r[0]["sources"]) == {"keyword", "semantic"}

    r = get(q="invoice", mode="keyword", supplier="zephyr", date_from="2025-08-01").json()
    assert [h["document_id"] for h in r] == [ids[2]]
    r = get(q="invoice", mode="keyword", currency="EUR").json()
    assert [h["document_id"] for h in r] == [ids[2]]
    r = get(q="invoice", mode="keyword", min_total="1000").json()
    assert [h["document_id"] for h in r] == [ids[1]]
    assert get(q="invoice", mode="keyword", status="failed").json() == []


def test_search_is_safe_against_injection_and_odd_input(upload: Uploader, rng: random.Random) -> None:
    upload.one("a.pdf", syn.make_pdf([syn.random_invoice(rng, 1)]))
    for q in [
        "'; DROP TABLE pages; --",
        '"unbalanced quote',
        "a & | ! ( )",
        "\\",
        "%_%",
        "x" * 300,
    ]:
        r = upload.client.get("/api/v1/search", headers=upload.headers, params={"q": q, "mode": "hybrid"})
        assert r.status_code == 200, (q, r.text)
    assert upload.client.get("/api/v1/documents", headers=upload.headers).json()["total"] == 1
    r = upload.client.get("/api/v1/search", headers=upload.headers, params={"q": "x", "supplier": "%"})
    assert r.status_code == 200 and r.json() == []  # LIKE wildcards in filters are escaped
    assert upload.client.get("/api/v1/search", headers=upload.headers, params={"q": ""}).status_code == 422


def test_invoice_listing_filters_sort_and_pagination(upload: Uploader, rng: random.Random) -> None:
    for i in range(5):
        inv = make(
            rng,
            i,
            "Acme Widgets Ltd" if i % 2 == 0 else "Blue Harbor Logistics",
            [("Thing", 1, str(100 * (i + 1)))],
            date(2025, 1 + i, 15),
        )
        upload.one(f"{i}.pdf", syn.make_pdf([inv]))
    get = lambda **p: upload.client.get("/api/v1/invoices", headers=upload.headers, params=p).json()  # noqa: E731
    page = get(sort="total_amount", desc="false", size=2)
    assert page["total"] == 5 and len(page["items"]) == 2
    totals = [float(i["total_amount"]) for i in page["items"]]
    assert totals == sorted(totals)
    assert get(supplier="acme")["total"] == 3
    assert get(date_from="2025-03-01", date_to="2025-04-30")["total"] == 2
    assert get(min_total="300", max_total="450")["total"] >= 1


def _by_field(pair: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {i["field"]: i for i in pair["items"]}


def test_pdf_vs_pdf_reports_exact_discrepancy_with_evidence(upload: Uploader, rng: random.Random) -> None:
    inv = syn.random_invoice(rng, 1)
    other = syn.random_invoice(rng, 1)
    other.__dict__.update(
        {
            **inv.__dict__,
            "total_override": inv.total + Decimal("25.00"),
            "supplier": inv.supplier.replace("Ltd", "Limited"),
        }
    )
    left = upload.one("left.pdf", syn.make_pdf([inv]))
    right = upload.one("right.pdf", syn.make_pdf([other]))
    r = upload.client.post(
        "/api/v1/comparisons",
        headers=upload.headers,
        json={"left_document_id": left, "right_document_id": right},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["summary"]["pairs"] == 1 and body["summary"]["discrepancy"] == 1
    (pair,) = body["pairs"]
    f = _by_field(pair)
    assert pair["status"] == "discrepancy"
    assert f["invoice_number"]["verdict"] == "match"
    assert f["currency"]["verdict"] == "match"
    assert f["total_amount"]["verdict"] == "mismatch"
    assert float(f["total_amount"]["right_value"]) - float(f["total_amount"]["left_value"]) == 25.0
    assert f["total_amount"]["left_source"]["filename"] == "left.pdf" and f["total_amount"]["left_source"]["page"] == 1
    assert f["total_amount"]["right_source"]["bbox"]  # where on the page the value was read
    assert f["supplier_name"]["verdict"] == "match"  # "Ltd" vs "Limited" is normalised away
    again = upload.client.get(f"/api/v1/comparisons/{body['id']}", headers=upload.headers).json()
    assert again["pairs"][0]["status"] == "discrepancy"
    assert upload.client.get("/api/v1/comparisons", headers=upload.headers).json()["total"] == 1


def test_pdf_vs_excel_with_matched_mismatched_and_unmatched(upload: Uploader, rng: random.Random) -> None:
    invs = [syn.random_invoice(rng, i) for i in range(1, 4)]
    pdf_id = upload.one("invoices.pdf", syn.make_pdf(invs))
    sheet_invs = [invs[0], invs[1], syn.random_invoice(rng, 9)]
    sheet_invs[1] = syn.random_invoice(rng, 2)
    sheet_invs[1].__dict__.update({**invs[1].__dict__, "total_override": invs[1].total - Decimal("5")})
    xlsx_id = upload.one("register.xlsx", syn.make_xlsx(sheet_invs, "summary"))
    r = upload.client.post(
        "/api/v1/comparisons",
        headers=upload.headers,
        json={"left_document_id": pdf_id, "right_document_id": xlsx_id},
    )
    assert r.status_code == 201, r.text
    s = r.json()["summary"]
    assert s["match"] == 1 and s["discrepancy"] == 1 and s["unmatched_left"] == 1 and s["unmatched_right"] == 1
    mismatch = next(p for p in r.json()["pairs"] if p["status"] == "discrepancy")
    total = _by_field(mismatch)["total_amount"]
    assert total["right_source"]["sheet"] == "Invoices" and total["right_source"]["cell"].startswith("Invoices!")
    assert total["left_source"]["page"] >= 1


def test_invoice_vs_receipt_verification(upload: Uploader, rng: random.Random) -> None:
    inv = syn.random_invoice(rng, 1)
    inv_id = upload.one("inv.pdf", syn.make_pdf([inv]))
    rec_id = upload.one("rec.pdf", syn.make_receipt_pdf(inv))
    body = upload.client.post(
        "/api/v1/comparisons",
        headers=upload.headers,
        json={"left_document_id": inv_id, "right_document_id": rec_id},
    ).json()
    (pair,) = body["pairs"]
    f = _by_field(pair)
    assert f["invoice_number"]["verdict"] == "match" and f["total_amount"]["verdict"] == "match"
    assert f["subtotal"]["verdict"] == "missing_in_right"  # a receipt has no subtotal: reported, not invented


def test_comparison_input_validation(upload: Uploader, rng: random.Random) -> None:
    d = upload.one("a.pdf", syn.make_pdf([syn.random_invoice(rng, 1)]))
    r = upload.client.post(
        "/api/v1/comparisons",
        headers=upload.headers,
        json={"left_document_id": d, "right_document_id": d},
    )
    assert r.status_code == 400
    r = upload.client.post(
        "/api/v1/comparisons",
        headers=upload.headers,
        json={"left_document_id": d, "right_document_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 404
