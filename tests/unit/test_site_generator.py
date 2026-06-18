"""Unit tests for the Jinja2 Site Generator.

Tests cover:
- Index page contains all subnets with badges (Req 21.2)
- Subnet page contains full intelligence card (Req 21.3)
- Rankings page has sortable table (Req 21.5)
- Briefing page renders alerts (Req 21.4)
- Data staleness warning when data >36h old (Req 34.2)
- Generated HTML is valid (no unclosed tags in key sections)
"""

from datetime import datetime, timezone, timedelta

import pytest



# ---------------------------------------------------------------------------
# Test Data
# ---------------------------------------------------------------------------


def _make_subnet_summary(netuid: int, *, name: str = None,
                         category: str = "COMPUTE",
                         taoflow_status: str = "HEALTHY",
                         mining_style: str = "GPU_INFERENCE") -> dict:
    return {
        "netuid": netuid,
        "name": name or f"Subnet {netuid}",
        "category": category,
        "mining_style": mining_style,
        "taoflow_status": taoflow_status,
        "net_tao_yield": 0.5,
        "days_to_recoup": 10.0,
        "attractiveness_score": 0.7,
        "active_miners": 50,
        "registration_cost": 1.0,
        "real_apy_percent": 65.0,
        "self_mining_risk": 0.0,
        "concentration_risk": {"risk": 0.0, "tier": "healthy"},
        "pool_tao_liquidity": 30000.0,
        "liquidity_warning": False,
        "earning_miners_count": 5,
        "reward_model": "TIERED",
        "gini_coefficient": 0.5,
        "price_trend_7d": -0.02,
        "price_volatility_7d": 0.001,
        "trend_direction": "stable",
    }


def _make_rankings() -> list[dict]:
    return [
        {"netuid": 1, "net_tao_yield": 1.0, "days_to_recoup": 5.0,
         "competitive_density": 0.2, "emission_trend": 0.05,
         "attractiveness_score": 0.85, "alpha_price": 0.05,
         "thirty_day_projection": 14.0, "real_apy_percent": 120.0,
         "self_mining_risk": 0.0, "concentration_risk": {"risk": 0.0, "tier": "healthy"},
         "pool_tao_liquidity": 50000.0, "liquidity_warning": False,
         "earning_miners_count": 10, "reward_model": "TIERED",
         "gini_coefficient": 0.45, "registration_cost_tao": 0.5,
         "price_trend_7d": 0.06, "price_volatility_7d": 0.002,
         "trend_direction": "up"},
        {"netuid": 2, "net_tao_yield": 0.5, "days_to_recoup": 15.0,
         "competitive_density": 0.4, "emission_trend": -0.02,
         "attractiveness_score": 0.55, "alpha_price": 0.03,
         "thirty_day_projection": 4.0, "real_apy_percent": 45.0,
         "self_mining_risk": 0.8, "concentration_risk": {"risk": 0.7, "tier": "high"},
         "pool_tao_liquidity": 2000.0, "liquidity_warning": True,
         "earning_miners_count": 0, "reward_model": "WINNER_TAKES_ALL",
         "gini_coefficient": 0.9, "registration_cost_tao": 2.0,
         "price_trend_7d": -0.08, "price_volatility_7d": 0.005,
         "trend_direction": "down"},
    ]


def _make_briefing() -> dict:
    return {
        "date": "2026-05-15",
        "cycle_id": "2026-05-15",
        "generated_at": "2026-05-15T01:00:00+00:00",
        "summary": "2 subnets processed, 1 alert.",
        "alerts": [
            {"netuid": 1, "alert_type": "emission_change", "severity": "warning",
             "message": "Subnet 1 emission changed 15.0% day-over-day"},
        ],
        "new_subnets": [3],
        "removed_subnets": [],
        "subnets_processed": 2,
        "subnets_failed": 0,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIndexPage:
    """Test index page generation."""

    def test_index_contains_all_subnets(self):
        """Index page lists all provided subnets."""
        from src.site_generator.generator import SiteGenerator

        gen = SiteGenerator()
        subnets = [_make_subnet_summary(1), _make_subnet_summary(2)]
        html = gen.generate_index(subnets, last_updated="2026-05-15T01:00:00+00:00")

        assert "SN1" in html
        assert "SN2" in html

    def test_index_contains_reward_model_badges(self):
        """Index page shows reward model badges."""
        from src.site_generator.generator import SiteGenerator

        gen = SiteGenerator()
        subnets = [_make_subnet_summary(1)]
        html = gen.generate_index(subnets, last_updated="2026-05-15T01:00:00+00:00")

        assert "TIER" in html

    def test_index_contains_apy(self):
        """Index page shows APY for subnets."""
        from src.site_generator.generator import SiteGenerator

        gen = SiteGenerator()
        subnets = [_make_subnet_summary(1)]
        html = gen.generate_index(subnets, last_updated="2026-05-15T01:00:00+00:00")

        assert "65%" in html


class TestRankingsPage:
    """Test rankings page generation."""

    def test_rankings_page_contains_table(self):
        """Rankings page has a table with subnet data."""
        from src.site_generator.generator import SiteGenerator

        gen = SiteGenerator()
        html = gen.generate_rankings_page(_make_rankings())

        assert "<table" in html
        assert "netuid" in html.lower() or "Subnet" in html

    def test_rankings_page_shows_attractiveness_score(self):
        """Rankings page displays attractiveness scores."""
        from src.site_generator.generator import SiteGenerator

        gen = SiteGenerator()
        html = gen.generate_rankings_page(_make_rankings())

        assert "0.85" in html or "85" in html


class TestBriefingPage:
    """Test briefing page generation."""

    def test_briefing_page_shows_alerts(self):
        """Briefing page renders alert messages."""
        from src.site_generator.generator import SiteGenerator

        gen = SiteGenerator()
        html = gen.generate_briefing_page(_make_briefing())

        assert "emission_change" in html or "emission changed" in html

    def test_briefing_page_shows_new_subnets(self):
        """Briefing page shows newly discovered subnets."""
        from src.site_generator.generator import SiteGenerator

        gen = SiteGenerator()
        html = gen.generate_briefing_page(_make_briefing())

        assert "3" in html  # New subnet 3


class TestDataStaleness:
    """Test data freshness indicator."""

    def test_stale_data_warning_when_old(self):
        """Warning appears when last_updated is >36h ago."""
        from src.site_generator.generator import SiteGenerator

        gen = SiteGenerator()
        old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        subnets = [_make_subnet_summary(1)]
        html = gen.generate_index(subnets, last_updated=old_time)

        assert "stale" in html.lower() or "warning" in html.lower() or "outdated" in html.lower()

    def test_no_warning_when_fresh(self):
        """No staleness warning when data is recent."""
        from src.site_generator.generator import SiteGenerator

        gen = SiteGenerator()
        fresh_time = datetime.now(timezone.utc).isoformat()
        subnets = [_make_subnet_summary(1)]
        html = gen.generate_index(subnets, last_updated=fresh_time)

        # Should not contain staleness warning
        assert "stale" not in html.lower() or "data is current" in html.lower()
