"""
Pure unit tests for Pydantic schemas — from_db_row() construction, field
validators, and edge cases where no database is needed.

Each ``from_db_row`` test constructs a dict as asyncpg would return it and
verifies the model is built with correct types (str coercions, default
values, null handling).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

# ── Receipt schemas ──────────────────────────────────────────────────────


class TestReceiptInDB:
    def test_from_db_row_full(self):
        from src.receipts.models import ReceiptInDB

        now = datetime.now(timezone.utc)
        row = {
            "id": "rec-123",
            "user_id": "usr-1",
            "total_amount": Decimal("45.99"),
            "merchant_name": "Tesco",
            "category_id": "cat-1",
            "ocr_raw_text": "TESCO STORES\n45.99\n20/03/2024",
            "ocr_confidence": 0.95,
            "line_items": [{"name": "Milk", "price": 1.50, "quantity": 2}],
            "receipt_image_s3_key": "receipts/abc.jpg",
            "notes": "weekly shop",
            "transaction_date": date(2024, 3, 20),
            "scanned_at": now,
            "created_at": now,
        }
        obj = ReceiptInDB.from_db_row(row)
        assert obj.id == "rec-123"
        assert obj.merchant_name == "Tesco"
        assert obj.total_amount == Decimal("45.99")
        assert obj.category_id == "cat-1"
        assert obj.scanned_at == now
        assert obj.line_items == [{"name": "Milk", "price": 1.50, "quantity": 2}]

    def test_from_db_row_minimal(self):
        from src.receipts.models import ReceiptInDB

        now = datetime.now(timezone.utc)
        row = {
            "id": "rec-1",
            "user_id": "usr-1",
            "scanned_at": now,
            "created_at": now,
        }
        obj = ReceiptInDB.from_db_row(row)
        assert obj.id == "rec-1"
        assert obj.total_amount is None
        assert obj.merchant_name is None
        assert obj.category_id is None
        assert obj.line_items is None

    def test_uri_coercion(self):
        """UUID-style category_id is coerced to str."""
        from src.receipts.models import ReceiptInDB

        now = datetime.now(timezone.utc)
        row = {
            "id": "rec-1",
            "user_id": "usr-1",
            "category_id": "550e8400-e29b-41d4-a716-446655440000",
            "scanned_at": now,
            "created_at": now,
        }
        obj = ReceiptInDB.from_db_row(row)
        assert obj.category_id == "550e8400-e29b-41d4-a716-446655440000"


class TestReceiptCreate:
    def test_optional_fields(self):
        from src.receipts.models import ReceiptCreate

        obj = ReceiptCreate()
        assert obj.merchant_name is None
        assert obj.total_amount is None

    def test_with_all_fields(self):
        from src.receipts.models import ReceiptCreate

        obj = ReceiptCreate(
            merchant_name="Tesco",
            total_amount=Decimal("45.99"),
            transaction_date=date(2024, 3, 20),
        )
        assert obj.merchant_name == "Tesco"
        assert obj.total_amount == Decimal("45.99")


# ── Transaction schemas ──────────────────────────────────────────────────


class TestTransactionBase:
    def test_ticker_uppercased(self):
        from src.transactions.schemas import TransactionCreate

        obj = TransactionCreate(
            ticker="aapl",
            type="BUY",
            shares=Decimal("10"),
            price_per_share=Decimal("150"),
            transaction_date=date(2024, 1, 1),
        )
        assert obj.ticker == "AAPL"

    def test_rejects_future_date(self):
        from src.transactions.schemas import TransactionCreate

        future = date(2099, 1, 1)
        with pytest.raises(ValidationError, match="future"):
            TransactionCreate(
                ticker="AAPL",
                type="BUY",
                shares=Decimal("10"),
                price_per_share=Decimal("150"),
                transaction_date=future,
            )

    def test_rejects_invalid_type(self):
        from src.transactions.schemas import TransactionCreate

        with pytest.raises(ValidationError, match="BUY|SELL"):
            TransactionCreate(
                ticker="AAPL",
                type="HOLD",
                shares=Decimal("10"),
                price_per_share=Decimal("150"),
                transaction_date=date(2024, 1, 1),
            )

    def test_rejects_excessive_shares_decimals(self):
        from src.transactions.schemas import TransactionCreate

        with pytest.raises(ValidationError, match="decimal places"):
            TransactionCreate(
                ticker="AAPL",
                type="SELL",
                shares=Decimal("10.1234567"),
                price_per_share=Decimal("150"),
                transaction_date=date(2024, 1, 1),
            )

    def test_rejects_excessive_price_decimals(self):
        from src.transactions.schemas import TransactionCreate

        with pytest.raises(ValidationError, match="decimal places"):
            TransactionCreate(
                ticker="AAPL",
                type="BUY",
                shares=Decimal("10"),
                price_per_share=Decimal("150.12345"),
                transaction_date=date(2024, 1, 1),
            )

    def test_rejects_empty_ticker(self):
        from src.transactions.schemas import TransactionCreate

        with pytest.raises(ValidationError):
            TransactionCreate(
                ticker="",
                type="BUY",
                shares=Decimal("10"),
                price_per_share=Decimal("150"),
                transaction_date=date(2024, 1, 1),
            )

    def test_allows_today_date(self):
        from src.transactions.schemas import TransactionCreate

        obj = TransactionCreate(
            ticker="AAPL",
            type="BUY",
            shares=Decimal("10"),
            price_per_share=Decimal("150"),
            transaction_date=date.today(),
        )
        assert obj.transaction_date == date.today()


class TestTransactionInDB:
    def test_from_db_row_full(self):
        from src.transactions.schemas import TransactionInDB

        now = datetime.now(timezone.utc)
        row = {
            "id": "txn-1",
            "portfolio_id": "pf-1",
            "ticker": "AAPL",
            "type": "BUY",
            "shares": Decimal("10"),
            "price_per_share": Decimal("150.00"),
            "total_amount": Decimal("1500.00"),
            "currency": "USD",
            "total_amount_gbp": Decimal("1125.00"),
            "transaction_date": date(2024, 1, 15),
            "notes": "First buy",
            "created_at": now,
        }
        obj = TransactionInDB.from_db_row(row)
        assert obj.id == "txn-1"
        assert obj.ticker == "AAPL"
        assert obj.total_amount == Decimal("1500.00")
        assert obj.total_amount_gbp == Decimal("1125.00")
        assert obj.currency == "USD"
        assert obj.notes == "First buy"

    def test_from_db_row_minimal(self):
        from src.transactions.schemas import TransactionInDB

        now = datetime.now(timezone.utc)
        row = {
            "id": "txn-2",
            "portfolio_id": "pf-1",
            "ticker": "TSLA",
            "type": "BUY",
            "shares": Decimal("5"),
            "price_per_share": Decimal("200"),
            "total_amount": Decimal("1000"),
            "transaction_date": date(2024, 2, 1),
            "created_at": now,
        }
        obj = TransactionInDB.from_db_row(row)
        assert obj.currency == "GBP"  # default
        assert obj.total_amount_gbp is None
        assert obj.notes is None

    def test_total_amount_default_is_decimal(self):
        from src.transactions.schemas import TransactionInDB

        now = datetime.now(timezone.utc)
        row = {
            "id": "txn-3",
            "portfolio_id": "pf-1",
            "ticker": "GOOG",
            "type": "SELL",
            "shares": Decimal("2"),
            "price_per_share": Decimal("3000"),
            "total_amount": Decimal("6000"),
            "transaction_date": date(2024, 3, 1),
            "created_at": now,
        }
        obj = TransactionInDB.from_db_row(row)
        assert isinstance(obj.total_amount, Decimal)


# ── Holding schemas ──────────────────────────────────────────────────────


class TestHoldingCreate:
    def test_ticker_uppercased(self):
        from src.holdings.schemas import HoldingCreate

        obj = HoldingCreate(
            ticker="msft",
            shares=Decimal("50"),
            average_cost_basis=Decimal("300"),
        )
        assert obj.ticker == "MSFT"

    def test_rejects_zero_shares(self):
        from src.holdings.schemas import HoldingCreate

        with pytest.raises(ValidationError):
            HoldingCreate(
                ticker="AAPL",
                shares=Decimal("0"),
                average_cost_basis=Decimal("150"),
            )


class TestHoldingInDB:
    def test_from_db_row_full(self):
        from src.holdings.schemas import HoldingInDB

        now = datetime.now(timezone.utc)
        row = {
            "id": "hld-1",
            "portfolio_id": "pf-1",
            "ticker": "AAPL",
            "shares": Decimal("100"),
            "average_cost_basis": Decimal("150"),
            "currency": "USD",
            "average_cost_basis_gbp": Decimal("112.50"),
            "created_at": now,
            "updated_at": now,
        }
        obj = HoldingInDB.from_db_row(row)
        assert obj.id == "hld-1"
        assert obj.average_cost_basis_gbp == Decimal("112.50")
        assert obj.currency == "USD"

    def test_from_db_row_minimal(self):
        from src.holdings.schemas import HoldingInDB

        now = datetime.now(timezone.utc)
        row = {
            "id": "hld-2",
            "portfolio_id": "pf-1",
            "ticker": "TSLA",
            "shares": Decimal("10"),
            "average_cost_basis": Decimal("200"),
            "created_at": now,
            "updated_at": now,
        }
        obj = HoldingInDB.from_db_row(row)
        assert obj.currency == "GBP"  # default
        assert obj.average_cost_basis_gbp is None


# ── Portfolio schemas ────────────────────────────────────────────────────


class TestPortfolioInDB:
    def test_from_db_row_full(self):
        from src.portfolios.schemas import PortfolioInDB

        now = datetime.now(timezone.utc)
        row = {
            "id": "pf-1",
            "user_id": "usr-1",
            "name": "Retirement",
            "description": "Long-term growth",
            "created_at": now,
            "updated_at": now,
        }
        obj = PortfolioInDB.from_db_row(row)
        assert obj.id == "pf-1"
        assert obj.name == "Retirement"
        assert obj.description == "Long-term growth"

    def test_from_db_row_no_description(self):
        from src.portfolios.schemas import PortfolioInDB

        now = datetime.now(timezone.utc)
        row = {
            "id": "pf-2",
            "user_id": "usr-1",
            "name": "Trading",
            "created_at": now,
            "updated_at": now,
        }
        obj = PortfolioInDB.from_db_row(row)
        assert obj.description is None

    def test_from_db_row_name_max_length(self):
        from src.portfolios.schemas import PortfolioInDB

        now = datetime.now(timezone.utc)
        long_name = "P" * 100
        row = {
            "id": "pf-3",
            "user_id": "usr-1",
            "name": long_name,
            "created_at": now,
            "updated_at": now,
        }
        obj = PortfolioInDB.from_db_row(row)
        assert obj.name == long_name

    def test_too_long_name_rejected_at_create(self):
        from src.portfolios.schemas import PortfolioCreate

        with pytest.raises(ValidationError):
            PortfolioCreate(name="P" * 101)


# ── Category schemas ─────────────────────────────────────────────────────


class TestCategoryInDB:
    def test_from_db_row_full(self):
        from src.categories.schemas import CategoryInDB

        row = {
            "id": "cat-1",
            "name": "Groceries",
            "description": "Supermarket purchases",
            "merchant_keywords": ["Tesco", "Sainsbury"],
            "associated_tickers": ["TSCO", "SBRY"],
        }
        obj = CategoryInDB.from_db_row(row)
        assert obj.id == "cat-1"
        assert obj.name == "Groceries"
        assert "Tesco" in obj.merchant_keywords
        assert "TSCO" in obj.associated_tickers

    def test_from_db_row_minimal(self):
        from src.categories.schemas import CategoryInDB

        row = {
            "id": "cat-2",
            "name": "Custom",
        }
        obj = CategoryInDB.from_db_row(row)
        assert obj.description is None
        assert obj.merchant_keywords == []
        assert obj.associated_tickers == []
