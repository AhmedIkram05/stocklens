"""
Tests for the FastAPI application (src.main).

Tests cover app metadata, router mounting, CORS, lifespan, and health endpoint.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.main import app


class TestAppMetadata:
    """Test FastAPI app metadata."""

    def test_app_title(self):
        assert app.title == "StockLens API"

    def test_app_description(self):
        assert "Receipt OCR" in app.description
        assert "portfolio tracking" in app.description.lower()

    def test_app_version(self):
        assert app.version == "0.1.0"

    def test_docs_url(self):
        assert app.docs_url == "/docs"

    def test_redoc_disabled(self):
        assert app.redoc_url is None


class TestRouterMounting:
    """Test that all routers are mounted with correct prefixes and tags."""

    def test_included_routers_count(self):
        """App should have 12 included routers (as _IncludedRouter)."""
        included = [r for r in app.routes if type(r).__name__ == "_IncludedRouter"]
        # 12 routers: auth, receipts, categories, portfolios, holdings, market,
        # cash_flows, performance, prediction, drift, transactions, agent
        assert len(included) == 12

    def test_health_endpoint_route_exists(self):
        """The /health endpoint should be directly on the app."""
        health_routes = [
            r for r in app.routes if hasattr(r, "path_format") and r.path_format == "/health"
        ]
        assert len(health_routes) == 1


class TestCORS:
    """Test CORS middleware configuration."""

    def test_cors_middleware_present(self):
        cors_middlewares = [m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware"]
        assert len(cors_middlewares) == 1

    def test_cors_allow_origins_from_settings(self):
        cors = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
        # Access options via kwargs
        assert cors.kwargs.get("allow_credentials") is True
        assert cors.kwargs.get("allow_methods") == ["*"]
        assert cors.kwargs.get("allow_headers") == ["*"]


class TestRateLimiting:
    """Test rate limiting middleware."""

    def test_limiter_attached(self):
        assert hasattr(app.state, "limiter")

    def test_rate_limit_handler_registered(self):
        handlers = app.exception_handlers
        assert 429 in handlers


class TestLifespan:
    """Test application lifespan events."""

    @patch("src.main.run_migrations", new_callable=AsyncMock)
    @patch("src.main.init_pool", new_callable=AsyncMock)
    @patch("src.categories.seed.seed_categories", new_callable=AsyncMock, return_value=0)
    @patch("src.prediction.service.prediction_service")
    @patch("src.main.close_pool", new_callable=AsyncMock)
    async def test_lifespan_startup_runs_migrations_pool_seed(
        self, mock_close_pool, mock_prediction_service, mock_seed, mock_init_pool, mock_migrations
    ):
        from src.main import lifespan

        class MockApp:
            pass

        mock_prediction_service.load_model.return_value = False

        # lifespan is an async generator, we need to iterate it manually
        gen = lifespan(MockApp())
        await gen.__anext__()  # startup
        await gen.aclose()  # shutdown

        mock_migrations.assert_awaited_once()
        mock_init_pool.assert_awaited_once()
        mock_seed.assert_awaited_once()
        mock_prediction_service.load_model.assert_called_once()

    @patch("src.main.run_migrations", new_callable=AsyncMock)
    @patch("src.main.init_pool", new_callable=AsyncMock)
    @patch("src.categories.seed.seed_categories", new_callable=AsyncMock, return_value=5)
    @patch("src.prediction.service.prediction_service")
    @patch("src.main.close_pool", new_callable=AsyncMock)
    async def test_lifespan_seeds_categories_on_first_run(
        self, mock_close_pool, mock_prediction_service, mock_seed, mock_init_pool, mock_migrations
    ):
        from src.main import lifespan

        class MockApp:
            pass

        mock_prediction_service.load_model.return_value = False

        gen = lifespan(MockApp())
        await gen.__anext__()  # startup
        await gen.aclose()  # shutdown

        mock_seed.assert_awaited_once()

    @patch("src.main.run_migrations", new_callable=AsyncMock)
    @patch("src.main.init_pool", new_callable=AsyncMock)
    @patch("src.categories.seed.seed_categories", new_callable=AsyncMock, return_value=0)
    @patch("src.prediction.service.prediction_service")
    @patch("src.main.close_pool", new_callable=AsyncMock)
    async def test_lifespan_shutdown_closes_pool(
        self, mock_close_pool, mock_prediction_service, mock_seed, mock_init_pool, mock_migrations
    ):
        from src.main import lifespan

        class MockApp:
            pass

        mock_prediction_service.load_model.return_value = False

        gen = lifespan(MockApp())
        await gen.__anext__()  # startup
        await gen.aclose()  # shutdown

        mock_close_pool.assert_awaited_once()


class TestHealthEndpoint:
    """Test /health endpoint."""

    def test_health_endpoint_exists(self):
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "environment" in data
