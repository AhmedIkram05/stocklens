"""
Tests for pure-DTO Pydantic schemas with no ``from_db_row`` methods or field
validators — auth, agent, prediction, drift modules.

These tests verify construction, default values, serialisation round-trips,
and type enforcement — no database or Redis needed.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

# ── Auth schemas ─────────────────────────────────────────────────────────


class TestTokenPayload:
    def test_construction(self):
        from src.auth.schemas import TokenPayload

        obj = TokenPayload(
            sub="usr-1", jti="abc-123", exp=9999999999, iat=1000000000, type="access"
        )
        assert obj.sub == "usr-1"
        assert obj.type == "access"

    def test_serialisation_round_trip(self):
        from src.auth.schemas import TokenPayload

        obj = TokenPayload(sub="usr-1", jti="abc", exp=100, iat=50, type="refresh")
        data = obj.model_dump()
        assert data["sub"] == "usr-1"
        assert data["type"] == "refresh"

        restored = TokenPayload.model_validate(data)
        assert restored.sub == obj.sub


class TestTokenPair:
    def test_default_values(self):
        from src.auth.schemas import TokenPair

        obj = TokenPair(access_token="ey...", refresh_token="ey...")
        assert obj.token_type == "bearer"
        assert obj.expires_in == 1800

    def test_custom_expires_in(self):
        from src.auth.schemas import TokenPair

        obj = TokenPair(access_token="a", refresh_token="b", expires_in=3600)
        assert obj.expires_in == 3600


class TestUserInDB:
    def test_minimal(self):
        from src.auth.schemas import UserInDB

        now = datetime.now(timezone.utc)
        obj = UserInDB(
            id="usr-1",
            email="test@example.com",
            password_hash="$2b$12$abc",
            created_at=now,
            updated_at=now,
        )
        assert obj.display_name is None
        assert obj.is_active is True

    def test_with_display_name(self):
        from src.auth.schemas import UserInDB

        now = datetime.now(timezone.utc)
        obj = UserInDB(
            id="usr-1",
            email="test@example.com",
            password_hash="$2b$12$abc",
            display_name="Test User",
            created_at=now,
            updated_at=now,
        )
        assert obj.display_name == "Test User"

    def test_model_dump_round_trip(self):
        from src.auth.schemas import UserInDB

        now = datetime.now(timezone.utc)
        obj = UserInDB(
            id="usr-1",
            email="test@example.com",
            password_hash="hash",
            display_name="Test",
            created_at=now,
            updated_at=now,
        )
        data = obj.model_dump(mode="json")
        assert data["is_active"] is True
        assert "password_hash" in data
        restored = UserInDB.model_validate(obj.model_dump())
        assert restored.email == "test@example.com"


class TestUserPublic:
    def test_no_password_hash(self):
        from src.auth.schemas import UserPublic

        now = datetime.now(timezone.utc)
        obj = UserPublic(id="usr-1", email="test@example.com", created_at=now, updated_at=now)
        assert not hasattr(obj, "password_hash") or getattr(obj, "password_hash", None) is None
        data = obj.model_dump()
        assert "password_hash" not in data


class TestRegisterRequest:
    def test_valid(self):
        from src.auth.schemas import RegisterRequest

        obj = RegisterRequest(
            email="new@example.com", password="securepass123", full_name="New User"
        )
        assert obj.email == "new@example.com"

    def test_rejects_short_password(self):
        from src.auth.schemas import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(email="new@example.com", password="short", full_name="User")

    def test_rejects_long_password(self):
        from src.auth.schemas import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(email="new@example.com", password="x" * 129, full_name="User")

    def test_rejects_invalid_email(self):
        from src.auth.schemas import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(email="not-an-email", password="securepass123", full_name="User")

    def test_empty_full_name_rejected(self):
        from src.auth.schemas import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(email="test@example.com", password="securepass123", full_name="")


class TestLoginRequest:
    def test_valid(self):
        from src.auth.schemas import LoginRequest

        obj = LoginRequest(email="user@example.com", password="mypassword")
        assert obj.email == "user@example.com"

    def test_rejects_invalid_email(self):
        from src.auth.schemas import LoginRequest

        with pytest.raises(ValidationError):
            LoginRequest(email="bad", password="x")


class TestLogoutRequest:
    def test_refresh_token_optional(self):
        from src.auth.schemas import LogoutRequest

        obj = LogoutRequest()
        assert obj.refresh_token is None

    def test_with_refresh_token(self):
        from src.auth.schemas import LogoutRequest

        obj = LogoutRequest(refresh_token="ey...")
        assert obj.refresh_token == "ey..."


class TestAuthResponse:
    def test_construction(self):
        from src.auth.schemas import AuthResponse, TokenPair, UserPublic

        now = datetime.now(timezone.utc)
        user = UserPublic(id="usr-1", email="test@example.com", created_at=now, updated_at=now)
        tokens = TokenPair(access_token="a", refresh_token="b")
        obj = AuthResponse(user=user, tokens=tokens)
        assert obj.user.email == "test@example.com"
        assert obj.tokens.access_token == "a"


class TestRefreshTokenRecord:
    def test_minimal(self):
        from src.auth.schemas import RefreshTokenRecord

        now = datetime.now(timezone.utc)
        obj = RefreshTokenRecord(
            id="rt-1",
            user_id="usr-1",
            token_hash="abc123",
            expires_at=now,
            created_at=now,
        )
        assert obj.revoked is False

    def test_revoked(self):
        from src.auth.schemas import RefreshTokenRecord

        now = datetime.now(timezone.utc)
        obj = RefreshTokenRecord(
            id="rt-1",
            user_id="usr-1",
            token_hash="abc123",
            expires_at=now,
            revoked=True,
            created_at=now,
        )
        assert obj.revoked is True


# ── Agent schemas ────────────────────────────────────────────────────────


class TestChatRequest:
    def test_new_conversation(self):
        from src.agent.schemas import ChatRequest

        obj = ChatRequest(message="Hello")
        assert obj.message == "Hello"
        assert obj.conversation_id is None

    def test_existing_conversation(self):
        from uuid import UUID

        from src.agent.schemas import ChatRequest

        cid = UUID("12345678-1234-5678-1234-567812345678")
        obj = ChatRequest(message="Hello", conversation_id=cid)
        assert obj.conversation_id == cid


class TestToolCallEvent:
    def test_construction(self):
        from src.agent.schemas import ToolCallEvent

        obj = ToolCallEvent(tool_name="get_stock_price", input={"ticker": "AAPL"})
        assert obj.tool_name == "get_stock_price"
        assert obj.input == {"ticker": "AAPL"}


class TestToolResultEvent:
    def test_success(self):
        from src.agent.schemas import ToolResultEvent

        obj = ToolResultEvent(tool_name="get_stock_price", output_summary="$150.00", success=True)
        assert obj.success is True

    def test_failure(self):
        from src.agent.schemas import ToolResultEvent

        obj = ToolResultEvent(
            tool_name="get_stock_price", output_summary="API error", success=False
        )
        assert obj.success is False


class TestSSEEvent:
    def test_construction(self):
        from src.agent.schemas import SSEEvent

        obj = SSEEvent(event="token", data='{"content":"Hello"}')
        assert obj.event == "token"
        assert obj.data == '{"content":"Hello"}'


class TestConversationSummary:
    def test_construction(self):
        from uuid import UUID

        from src.agent.schemas import ConversationSummary

        now = datetime.now(timezone.utc)
        cid = UUID("00000000-0000-0000-0000-000000000001")
        obj = ConversationSummary(
            id=cid,
            title="My Chat",
            message_count=5,
            created_at=now,
            updated_at=now,
        )
        assert obj.title == "My Chat"
        assert obj.message_count == 5

    def test_title_none(self):
        from uuid import UUID

        from src.agent.schemas import ConversationSummary

        now = datetime.now(timezone.utc)
        obj = ConversationSummary(
            id=UUID(int=2),
            title=None,
            message_count=0,
            created_at=now,
            updated_at=now,
        )
        assert obj.title is None


class TestMessageResponse:
    def test_minimal(self):
        from src.agent.schemas import MessageResponse

        now = datetime.now(timezone.utc)
        obj = MessageResponse(
            role="assistant",
            content="Hello",
            tools_used=None,
            reasoning_steps=None,
            created_at=now,
        )
        assert obj.tools_used is None
        assert obj.reasoning_steps is None

    def test_with_tools(self):
        from src.agent.schemas import MessageResponse

        now = datetime.now(timezone.utc)
        obj = MessageResponse(
            role="assistant",
            content="Let me check",
            tools_used={"get_stock_price": {"ticker": "AAPL"}},
            reasoning_steps=None,
            created_at=now,
        )
        assert obj.tools_used is not None
        assert "get_stock_price" in obj.tools_used


class TestAgentFeedbackRequest:
    def test_minimal(self):
        from src.agent.schemas import AgentFeedbackRequest

        obj = AgentFeedbackRequest(rating="positive", trace_id="tr-123")
        assert obj.comment is None

    def test_with_comment(self):
        from src.agent.schemas import AgentFeedbackRequest

        obj = AgentFeedbackRequest(rating="negative", trace_id="tr-123", comment="Wrong answer")
        assert obj.comment == "Wrong answer"


# ── Prediction schemas ───────────────────────────────────────────────────


class TestPredictionResponse:
    def test_construction(self):
        from src.prediction.schemas import PredictionResponse

        now = datetime.now(timezone.utc)
        obj = PredictionResponse(
            ticker="AAPL",
            direction="UP",
            confidence=0.87,
            probabilities={"DOWN": 0.05, "FLAT": 0.08, "UP": 0.87},
            model_version="v1.2.3",
            predicted_at=now,
        )
        assert obj.ticker == "AAPL"
        assert obj.direction == "UP"
        assert obj.cached is False

    def test_cached_flag(self):
        from src.prediction.schemas import PredictionResponse

        now = datetime.now(timezone.utc)
        obj = PredictionResponse(
            ticker="TSLA",
            direction="FLAT",
            confidence=0.45,
            probabilities={"DOWN": 0.3, "FLAT": 0.45, "UP": 0.25},
            model_version="v1",
            cached=True,
            predicted_at=now,
        )
        assert obj.cached is True

    def test_json_serialisation(self):
        from src.prediction.schemas import PredictionResponse

        now = datetime.now(timezone.utc)
        obj = PredictionResponse(
            ticker="AAPL",
            direction="UP",
            confidence=0.87,
            probabilities={"DOWN": 0.05, "FLAT": 0.08, "UP": 0.87},
            model_version="v1.2.3",
            predicted_at=now,
        )
        data = obj.model_dump(mode="json")
        assert data["ticker"] == "AAPL"
        assert data["confidence"] == 0.87
        assert isinstance(data["predicted_at"], str)  # ISO datetime string


class TestPredictionErrorResponse:
    def test_construction(self):
        from src.prediction.schemas import PredictionErrorResponse

        obj = PredictionErrorResponse(detail="No data available", code="NO_DATA")
        assert obj.detail == "No data available"
        assert obj.code == "NO_DATA"


# ── Drift schemas ────────────────────────────────────────────────────────


class TestDriftRunRequest:
    def test_defaults(self):
        from src.drift.schemas import DriftRunRequest

        obj = DriftRunRequest()
        assert obj.tickers is None
        assert obj.lookback_days == 30
        assert obj.generate_report is False

    def test_with_tickers(self):
        from src.drift.schemas import DriftRunRequest

        obj = DriftRunRequest(tickers=["AAPL", "TSLA"], lookback_days=90, generate_report=True)
        assert obj.tickers == ["AAPL", "TSLA"]
        assert obj.lookback_days == 90
        assert obj.generate_report is True

    def test_lookback_days_min(self):
        from src.drift.schemas import DriftRunRequest

        with pytest.raises(ValidationError):
            DriftRunRequest(lookback_days=0)

    def test_lookback_days_max(self):
        from src.drift.schemas import DriftRunRequest

        with pytest.raises(ValidationError):
            DriftRunRequest(lookback_days=366)

    def test_lookback_days_boundary(self):
        from src.drift.schemas import DriftRunRequest

        obj = DriftRunRequest(lookback_days=365)
        assert obj.lookback_days == 365

        obj2 = DriftRunRequest(lookback_days=1)
        assert obj2.lookback_days == 1


class TestDriftMetricResponse:
    def test_construction(self):
        from src.drift.schemas import DriftMetricResponse

        obj = DriftMetricResponse(
            ticker="AAPL",
            feature_name="close_price",
            metric_type="psi",
            drift_score=0.15,
            alert_triggered=False,
            model_version="v1",
        )
        assert obj.drift_score == 0.15
        assert obj.alert_triggered is False

    def test_alert_active(self):
        from src.drift.schemas import DriftMetricResponse

        obj = DriftMetricResponse(
            ticker="AAPL",
            feature_name="volume",
            metric_type="js_divergence",
            drift_score=0.85,
            alert_triggered=True,
            model_version="v1",
            reference_period="2024-01",
            current_period="2024-06",
        )
        assert obj.alert_triggered is True
        assert obj.reference_period == "2024-01"


class TestDriftRunResponse:
    def test_construction(self):
        from src.drift.schemas import DriftMetricResponse, DriftRunResponse

        now = datetime.now(timezone.utc)
        metric = DriftMetricResponse(
            ticker="AAPL",
            feature_name="close_price",
            metric_type="psi",
            drift_score=0.1,
            alert_triggered=False,
            model_version="v1",
        )
        obj = DriftRunResponse(
            drift_run_id="dr-1",
            tickers_monitored=["AAPL"],
            total_metrics=1,
            alerts_triggered=0,
            max_psi=0.1,
            max_js_divergence=0.0,
            overall_drift_verdict="PASS",
            metrics=[metric],
            created_at=now,
        )
        assert obj.drift_run_id == "dr-1"
        assert obj.overall_drift_verdict == "PASS"
        assert len(obj.metrics) == 1
        assert obj.report_url is None


class TestDriftReportSummary:
    def test_construction(self):
        from src.drift.schemas import DriftReportSummary

        obj = DriftReportSummary(
            overall_status="HEALTHY",
            drifted_features=0,
            total_features=10,
            latest_run_at="2024-06-01T00:00:00Z",
            tickers_with_drift=[],
        )
        assert obj.overall_status == "HEALTHY"
        assert obj.drifted_features == 0
        assert obj.tickers_with_drift == []


# ── Cash Flow schemas ────────────────────────────────────────────────────


class TestCashFlowCreate:
    def test_minimal(self):
        from src.cash_flows.schemas import CashFlowCreate

        obj = CashFlowCreate(amount=Decimal("100.00"))
        assert obj.amount == Decimal("100.00")
        assert obj.source == "receipt"
        assert obj.source_id is None
        assert obj.notes is None

    def test_rejects_zero_amount(self):
        from src.cash_flows.schemas import CashFlowCreate

        with pytest.raises(ValidationError):
            CashFlowCreate(amount=Decimal("0"))

    def test_rejects_negative_amount(self):
        from src.cash_flows.schemas import CashFlowCreate

        with pytest.raises(ValidationError):
            CashFlowCreate(amount=Decimal("-50"))


class TestCashFlowInDB:
    def test_construction(self):
        from uuid import UUID

        from src.cash_flows.schemas import CashFlowInDB

        now = datetime.now(timezone.utc)
        pid = UUID(int=1)
        cid = UUID(int=2)
        obj = CashFlowInDB(
            id=cid,
            portfolio_id=pid,
            amount=Decimal("250.00"),
            source="manual",
            created_at=now,
        )
        assert obj.amount == Decimal("250.00")
        assert obj.source == "manual"
        assert obj.notes is None

    def test_with_all_fields(self):
        from uuid import UUID

        from src.cash_flows.schemas import CashFlowInDB

        now = datetime.now(timezone.utc)
        sid = UUID(int=3)
        obj = CashFlowInDB(
            id=UUID(int=1),
            portfolio_id=UUID(int=2),
            amount=Decimal("100.00"),
            source="receipt",
            source_id=sid,
            notes="Tesco refund",
            created_at=now,
        )
        assert obj.source_id == sid
        assert obj.notes == "Tesco refund"


# ── Performance schemas ──────────────────────────────────────────────────


class TestHoldingPerformance:
    def test_construction(self):
        from src.performance.schemas import HoldingPerformance

        obj = HoldingPerformance(
            ticker="AAPL",
            shares=Decimal("100"),
            average_cost_basis=Decimal("150"),
            cost_basis=Decimal("15000"),
        )
        assert obj.ticker == "AAPL"
        assert obj.currency == "GBP"
        assert obj.current_price is None
        assert obj.market_value is None

    def test_with_price_data(self):
        from src.performance.schemas import HoldingPerformance

        obj = HoldingPerformance(
            ticker="AAPL",
            shares=Decimal("100"),
            average_cost_basis=Decimal("150"),
            current_price=Decimal("200"),
            cost_basis=Decimal("15000"),
            market_value=Decimal("20000"),
            unrealised_pl=Decimal("5000"),
        )
        assert obj.unrealised_pl == Decimal("5000")


class TestPortfolioPerformanceResponse:
    def test_construction(self):
        from src.performance.schemas import PortfolioPerformanceResponse

        now = datetime.now(timezone.utc)
        obj = PortfolioPerformanceResponse(
            portfolio_id="p1",
            portfolio_name="Test",
            total_cost_basis=Decimal("0"),
            holdings=[],
            total_holdings=0,
            calculated_at=now,
        )
        assert obj.total_market_value is None
        assert obj.data_quality == "complete"
        assert obj.free_cash_balance == Decimal("0")
        assert obj.twr is None

    def test_serialisation_round_trip(self):
        from src.performance.schemas import PortfolioPerformanceResponse

        now = datetime.now(timezone.utc)
        obj = PortfolioPerformanceResponse(
            portfolio_id="p1",
            portfolio_name="Test",
            total_cost_basis=Decimal("1000"),
            holdings=[],
            total_holdings=0,
            calculated_at=now,
        )
        data = obj.model_dump(mode="json")
        assert data["data_quality"] == "complete"
        restored = PortfolioPerformanceResponse.model_validate(obj.model_dump())
        assert restored.portfolio_id == "p1"


class TestBenchmarkParams:
    def test_defaults(self):
        from src.performance.schemas import BenchmarkParams

        obj = BenchmarkParams()
        assert obj.benchmark == "SPY"
        assert obj.start_date is None
        assert obj.end_date is None

    def test_custom(self):
        from src.performance.schemas import BenchmarkParams

        obj = BenchmarkParams(benchmark="QQQ", start_date=date(2024, 1, 1))
        assert obj.benchmark == "QQQ"


# ── Market schemas ───────────────────────────────────────────────────────


class TestOHLCVData:
    def test_construction(self):
        from src.market.schemas import OHLCVData

        obj = OHLCVData(date=date(2024, 1, 2), close=Decimal("150.00"), volume=1000000)
        assert obj.close == Decimal("150.00")
        assert obj.open is None
        assert obj.high is None

    def test_all_fields_nullable(self):
        from src.market.schemas import OHLCVData

        obj = OHLCVData(date=date(2024, 1, 2))
        assert obj.close is None
        assert obj.volume is None


class TestQuoteResponse:
    def test_construction(self):
        from src.market.schemas import QuoteResponse

        now = datetime.now(timezone.utc)
        obj = QuoteResponse(
            ticker="AAPL",
            price=Decimal("200.00"),
            change=Decimal("2.50"),
            change_pct=Decimal("1.265"),
            previous_close=Decimal("197.50"),
            volume=50000000,
            timestamp=now,
        )
        assert obj.ticker == "AAPL"
        assert obj.currency == "GBP"
        assert obj.exchange is None

    def test_with_exchange(self):
        from src.market.schemas import QuoteResponse

        now = datetime.now(timezone.utc)
        obj = QuoteResponse(
            ticker="AAPL",
            price=Decimal("200.00"),
            change=Decimal("2.50"),
            change_pct=Decimal("1.265"),
            previous_close=Decimal("197.50"),
            volume=50000000,
            timestamp=now,
            currency="USD",
            exchange="NASDAQ",
        )
        assert obj.currency == "USD"
        assert obj.exchange == "NASDAQ"
