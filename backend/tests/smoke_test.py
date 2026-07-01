"""
Round 6 — Smoke test.

Hits every endpoint of the running FastAPI backend with real HTTP calls against
actual PostgreSQL and Redis (no mocks, no transaction rollback).

Usage:
    python tests/smoke_test.py [--base-url http://localhost:8000]
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx

BASE_URL = "http://localhost:8000"


@dataclass
class SmokeResult:
    name: str
    passed: bool
    detail: str = ""


class SmokeTester:
    """Run a battery of smoke tests against a live backend."""

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=15.0)
        self.results: list[SmokeResult] = []
        self.access_token: str = ""
        self.refresh_token: str = ""

    def _ok(self, name: str, detail: str = "") -> None:
        self.results.append(SmokeResult(name, True, detail))

    def _fail(self, name: str, detail: str) -> None:
        self.results.append(SmokeResult(name, False, detail))

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

    def _assert_eq(self, name: str, actual: Any, expected: Any) -> None:
        if actual == expected:
            self._ok(name, f"== {expected!r}")
        else:
            self._fail(name, f"expected {expected!r}, got {actual!r}")

    def _assert_in(self, name: str, item: Any, container: Any) -> None:
        if item in container:
            self._ok(name, "found")
        else:
            self._fail(name, f"{item!r} not found")

    def _fresh_session(self) -> str:
        """Register a new user and store access_token. Returns email."""
        email = f"smoke_{int(time.time() * 1000)}@test.com"
        resp = self.client.post(
            f"{self.base_url}/auth/register",
            json={"email": email, "password": "SmokeTest123!", "full_name": "Smoke Tester"},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 201, f"fresh session: {resp.status_code} {resp.text[:200]}"
        data = resp.json()
        self.access_token = data["tokens"]["access_token"]
        self.refresh_token = data["tokens"]["refresh_token"]
        return email

    def _extract_tokens(self, data: dict) -> None:
        """Handle both nested (register/login) and flat (refresh) token response formats."""
        if "tokens" in data:
            self.access_token = data["tokens"]["access_token"]
            self.refresh_token = data["tokens"]["refresh_token"]
        else:
            self.access_token = data["access_token"]
            self.refresh_token = data["refresh_token"]

    # ---- test groups ----------------------------------------------------------

    def health(self) -> None:
        resp = self.client.get(f"{self.base_url}/health")
        self._assert_eq("GET /health", resp.status_code, 200)
        self._assert_eq("status = ok", resp.json().get("status"), "ok")

    def auth_flow(self) -> None:
        """Full lifecycle: register → login → me → refresh → stolen → logout."""
        email = self._fresh_session()
        # Login
        resp = self.client.post(
            f"{self.base_url}/auth/login",
            json={"email": email, "password": "SmokeTest123!"},
            headers={"Content-Type": "application/json"},
        )
        self._assert_eq("POST /auth/login", resp.status_code, 200)
        data = resp.json()
        self._extract_tokens(data)

        # /me
        resp = self.client.get(
            f"{self.base_url}/auth/me", headers={"Authorization": f"Bearer {self.access_token}"}
        )
        self._assert_eq("GET /auth/me", resp.status_code, 200)
        self._assert_eq("email matches", resp.json()["email"], email)

        # Refresh
        resp = self.client.post(
            f"{self.base_url}/auth/refresh",
            json={"refresh_token": self.refresh_token},
            headers={"Content-Type": "application/json"},
        )
        self._assert_eq("POST /auth/refresh", resp.status_code, 200)
        data = resp.json()
        old_refresh = self.refresh_token
        self._extract_tokens(data)

        # Stolen-token: replay old refresh → 401
        resp = self.client.post(
            f"{self.base_url}/auth/refresh",
            json={"refresh_token": old_refresh},
            headers={"Content-Type": "application/json"},
        )
        self._assert_eq("stolen refresh → 401", resp.status_code, 401)

        # Logout
        resp = self.client.post(
            f"{self.base_url}/auth/logout",
            json={"refresh_token": self.refresh_token},
            headers=self._auth_headers(),
        )
        self._assert_eq("POST /auth/logout → 204", resp.status_code, 204)

        # Access token after logout → 401
        resp = self.client.get(
            f"{self.base_url}/auth/me",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )
        self._assert_eq("post-logout GET /auth/me → 401", resp.status_code, 401)

    def portfolios(self) -> None:
        self._fresh_session()
        pid: str = ""

        # Create
        resp = self.client.post(
            f"{self.base_url}/portfolios",
            json={"name": "Smoke Portfolio"},
            headers=self._auth_headers(),
        )
        self._assert_eq("POST /portfolios", resp.status_code, 201)
        pid = resp.json()["id"]

        # List
        resp = self.client.get(f"{self.base_url}/portfolios", headers=self._auth_headers())
        self._assert_eq("GET /portfolios", resp.status_code, 200)
        self._assert_in("portfolio in list", pid, [p["id"] for p in resp.json()["portfolios"]])

        # Get
        resp = self.client.get(f"{self.base_url}/portfolios/{pid}", headers=self._auth_headers())
        self._assert_eq("GET /portfolios/{id}", resp.status_code, 200)
        self._assert_eq("name matches", resp.json()["name"], "Smoke Portfolio")

        # Update
        resp = self.client.put(
            f"{self.base_url}/portfolios/{pid}",
            json={"name": "Updated"},
            headers=self._auth_headers(),
        )
        self._assert_eq("PUT /portfolios/{id}", resp.status_code, 200)
        self._assert_eq("updated name", resp.json()["name"], "Updated")

        # 404
        resp = self.client.get(
            f"{self.base_url}/portfolios/00000000-0000-0000-0000-000000000000",
            headers=self._auth_headers(),
        )
        self._assert_eq("GET /portfolios/missing → 404", resp.status_code, 404)

        # Delete
        resp = self.client.post(
            f"{self.base_url}/portfolios",
            json={"name": "To Delete"},
            headers=self._auth_headers(),
        )
        assert resp.status_code == 201
        del_id = resp.json()["id"]
        resp = self.client.delete(
            f"{self.base_url}/portfolios/{del_id}", headers=self._auth_headers()
        )
        self._assert_eq("DELETE /portfolios/{id} → 204", resp.status_code, 204)
        resp = self.client.get(f"{self.base_url}/portfolios/{del_id}", headers=self._auth_headers())
        self._assert_eq("GET deleted portfolio → 404", resp.status_code, 404)

    def holdings(self) -> None:
        self._fresh_session()
        pid: str = ""
        hid: str = ""

        # Create portfolio first
        resp = self.client.post(
            f"{self.base_url}/portfolios",
            json={"name": "Holdings Test"},
            headers=self._auth_headers(),
        )
        assert resp.status_code == 201
        pid = resp.json()["id"]

        # Create holding
        resp = self.client.post(
            f"{self.base_url}/portfolios/{pid}/holdings",
            json={"ticker": "AAPL", "shares": 10, "average_cost_basis": 150.0},
            headers=self._auth_headers(),
        )
        self._assert_eq("POST /portfolios/{id}/holdings", resp.status_code, 201)
        hid = resp.json()["id"]
        self._assert_eq("ticker uppercase", resp.json()["ticker"], "AAPL")

        # List
        resp = self.client.get(
            f"{self.base_url}/portfolios/{pid}/holdings", headers=self._auth_headers()
        )
        self._assert_eq("GET /portfolios/{id}/holdings", resp.status_code, 200)
        self._assert_in("holding in list", hid, [h["id"] for h in resp.json()["holdings"]])

        # Get standalone
        resp = self.client.get(f"{self.base_url}/holdings/{hid}", headers=self._auth_headers())
        self._assert_eq("GET /holdings/{id}", resp.status_code, 200)
        self._assert_eq("ticker AAPL", resp.json()["ticker"], "AAPL")

        # Get nested
        resp = self.client.get(
            f"{self.base_url}/portfolios/{pid}/holdings/{hid}", headers=self._auth_headers()
        )
        self._assert_eq("GET /portfolios/{pid}/holdings/{hid}", resp.status_code, 200)
        self._assert_eq("nested ticker AAPL", resp.json()["ticker"], "AAPL")

        # Update
        resp = self.client.put(
            f"{self.base_url}/holdings/{hid}",
            json={"shares": 15},
            headers=self._auth_headers(),
        )
        self._assert_eq("PUT /holdings/{id}", resp.status_code, 200)
        self._assert_eq("shares → 15", resp.json()["shares"], 15.0)

        # Ticker auto-uppercase
        resp = self.client.post(
            f"{self.base_url}/portfolios/{pid}/holdings",
            json={"ticker": "msft", "shares": 5, "average_cost_basis": 200.0},
            headers=self._auth_headers(),
        )
        self._assert_eq("lowercase ticker → MSFT", resp.json()["ticker"], "MSFT")

        # Duplicate → 409
        resp = self.client.post(
            f"{self.base_url}/portfolios/{pid}/holdings",
            json={"ticker": "AAPL", "shares": 1, "average_cost_basis": 100.0},
            headers=self._auth_headers(),
        )
        self._assert_eq("duplicate ticker → 409", resp.status_code, 409)

        # 404
        resp = self.client.get(
            f"{self.base_url}/holdings/00000000-0000-0000-0000-000000000000",
            headers=self._auth_headers(),
        )
        self._assert_eq("GET /holdings/missing → 404", resp.status_code, 404)

        # Delete
        resp = self.client.delete(f"{self.base_url}/holdings/{hid}", headers=self._auth_headers())
        self._assert_eq("DELETE /holdings/{id} → 204", resp.status_code, 204)
        resp = self.client.get(f"{self.base_url}/holdings/{hid}", headers=self._auth_headers())
        self._assert_eq("GET deleted holding → 404", resp.status_code, 404)

    def transactions(self) -> None:
        self._fresh_session()
        pid: str = ""
        tid: str = ""

        # Create portfolio
        resp = self.client.post(
            f"{self.base_url}/portfolios",
            json={"name": "Transactions Test"},
            headers=self._auth_headers(),
        )
        assert resp.status_code == 201
        pid = resp.json()["id"]

        # Create transaction
        resp = self.client.post(
            f"{self.base_url}/portfolios/{pid}/transactions",
            json={
                "ticker": "GOOGL",
                "type": "BUY",
                "shares": 10,
                "price_per_share": 140.0,
                "transaction_date": "2026-06-29",
                "notes": "smoke test",
            },
            headers=self._auth_headers(),
        )
        self._assert_eq("POST /portfolios/{id}/transactions", resp.status_code, 201)
        tid = resp.json()["id"]
        self._assert_eq("total_amount = 1400", resp.json()["total_amount"], 1400.0)

        # List paginated
        resp = self.client.get(
            f"{self.base_url}/portfolios/{pid}/transactions?limit=10&offset=0",
            headers=self._auth_headers(),
        )
        self._assert_eq("GET /portfolios/{id}/transactions", resp.status_code, 200)
        body = resp.json()
        self._assert_in("transaction in list", tid, [t["id"] for t in body["transactions"]])
        self._assert_eq("total >= 1", body["total"] >= 1, True)

        # Ticker filter
        resp = self.client.get(
            f"{self.base_url}/portfolios/{pid}/transactions?limit=10&offset=0&ticker=GOOGL",
            headers=self._auth_headers(),
        )
        self._assert_eq("ticker filter count", len(resp.json()["transactions"]), 1)

        # Get standalone
        resp = self.client.get(f"{self.base_url}/transactions/{tid}", headers=self._auth_headers())
        self._assert_eq("GET /transactions/{id}", resp.status_code, 200)
        self._assert_eq("ticker GOOGL", resp.json()["ticker"], "GOOGL")

        # Get nested
        resp = self.client.get(
            f"{self.base_url}/portfolios/{pid}/transactions/{tid}",
            headers=self._auth_headers(),
        )
        self._assert_eq("GET /portfolios/{pid}/transactions/{tid}", resp.status_code, 200)
        self._assert_eq("nested ticker", resp.json()["ticker"], "GOOGL")

        # 404
        resp = self.client.get(
            f"{self.base_url}/transactions/00000000-0000-0000-0000-000000000000",
            headers=self._auth_headers(),
        )
        self._assert_eq("GET /transactions/missing → 404", resp.status_code, 404)

    def categories(self) -> None:
        self._fresh_session()

        resp = self.client.get(f"{self.base_url}/categories", headers=self._auth_headers())
        self._assert_eq("GET /categories", resp.status_code, 200)
        cats = resp.json()
        self._assert_eq("categories is list", isinstance(cats.get("categories"), list), True)
        self._assert_eq("has at least 1", len(cats.get("categories", [])) >= 1, True)
        category_list = cats.get("categories", [])
        if category_list:
            cid = category_list[0]["id"]
            resp = self.client.get(
                f"{self.base_url}/categories/{cid}", headers=self._auth_headers()
            )
            self._assert_eq("GET /categories/{id}", resp.status_code, 200)
            self._assert_eq("id matches", resp.json()["id"], cid)

        # 404
        resp = self.client.get(
            f"{self.base_url}/categories/00000000-0000-0000-0000-000000000000",
            headers=self._auth_headers(),
        )
        self._assert_eq("GET /categories/missing → 404", resp.status_code, 404)

    def receipts(self) -> None:
        self._fresh_session()
        rid: str = ""

        # Create
        resp = self.client.post(
            f"{self.base_url}/receipts",
            json={
                "merchant_name": "Test Shop",
                "total_amount": 42.50,
                "transaction_date": "2026-06-29",
                "notes": "smoke test",
            },
            headers=self._auth_headers(),
        )
        self._assert_eq("POST /receipts", resp.status_code, 201)
        rid = resp.json()["id"]

        # Get
        resp = self.client.get(f"{self.base_url}/receipts/{rid}", headers=self._auth_headers())
        self._assert_eq("GET /receipts/{id}", resp.status_code, 200)
        self._assert_eq("merchant matches", resp.json()["merchant_name"], "Test Shop")

        # List
        resp = self.client.get(
            f"{self.base_url}/receipts?limit=10&offset=0", headers=self._auth_headers()
        )
        self._assert_eq("GET /receipts paginated", resp.status_code, 200)
        self._assert_in("receipt in list", rid, [r["id"] for r in resp.json()["receipts"]])

        # Update
        resp = self.client.put(
            f"{self.base_url}/receipts/{rid}",
            json={"notes": "updated"},
            headers=self._auth_headers(),
        )
        self._assert_eq("PUT /receipts/{id}", resp.status_code, 200)
        self._assert_eq("notes updated", resp.json()["notes"], "updated")

        # Delete
        resp = self.client.delete(f"{self.base_url}/receipts/{rid}", headers=self._auth_headers())
        self._assert_eq("DELETE /receipts/{id} → 204", resp.status_code, 204)
        resp = self.client.get(f"{self.base_url}/receipts/{rid}", headers=self._auth_headers())
        self._assert_eq("GET deleted receipt → 404", resp.status_code, 404)

    def unauthorized(self) -> None:
        for method, path in [
            ("GET", "/portfolios"),
            ("POST", "/portfolios"),
            ("GET", "/categories"),
            ("GET", "/receipts"),
            ("POST", "/receipts"),
            ("GET", "/auth/me"),
        ]:
            resp = self.client.request(method, f"{self.base_url}{path}")
            self._assert_eq(f"{method} {path} → 401", resp.status_code, 401)

    def validation(self) -> None:
        self._fresh_session()
        hdrs = self._auth_headers()

        # Missing required field
        resp = self.client.post(f"{self.base_url}/portfolios", json={}, headers=hdrs)
        self._assert_eq("POST /portfolios {} → 422", resp.status_code, 422)

        # Bad UUID
        resp = self.client.get(f"{self.base_url}/portfolios/not-a-uuid", headers=hdrs)
        self._assert_eq("GET /portfolios/bad-uuid → 422", resp.status_code, 422)


def main() -> int:
    parser = argparse.ArgumentParser(description="StockLens smoke test")
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()

    print(f"🧪  StockLens Smoke Test — Round 6\n    Base URL: {args.base_url}\n")

    tester = SmokeTester(args.base_url)
    groups = [
        ("Health", tester.health),
        ("Unauthorized Access", tester.unauthorized),
        ("Validation Errors", tester.validation),
        ("Portfolios CRUD", tester.portfolios),
        ("Holdings CRUD", tester.holdings),
        ("Transactions CRUD", tester.transactions),
        ("Categories", tester.categories),
        ("Receipts CRUD", tester.receipts),
        ("Auth Flow", tester.auth_flow),  # last — invalidates tokens
    ]

    for name, fn in groups:
        try:
            fn()
        except Exception as e:
            tester.results.append(SmokeResult(name, False, f"EXCEPTION: {e}"))

    passed = sum(1 for r in tester.results if r.passed)
    total = len(tester.results)

    print(f"\n{'─' * 55}")
    for r in tester.results:
        print(r)
    print(f"{'─' * 55}")
    print(f"\n  {passed}/{total} checks passed")
    if passed < total:
        print("  ❌  SMOKE TEST FAILED")
        return 1
    print("  ✅  SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
