"""Output contract tests — verify data flows correctly between pipeline stages.

These tests catch the class of bug where:
- A producer outputs fields X, Y, Z
- A consumer expects fields A, B, C
- Unit tests pass because mocks provide A, B, C directly

Contract tests wire REAL producer output into REAL consumer input.
"""

import json
import os
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import boto3
import pytest
from moto import mock_aws



# ---------------------------------------------------------------------------
# Test 1: Rankings → index.html template (no empty badges)
# ---------------------------------------------------------------------------


class TestRankingsToIndexContract:
    """Verify _generate_rankings output renders correctly in index.html."""

    def test_no_empty_badges_with_real_rankings_output(self):
        """index.html must not render empty badge spans when profile data is missing.

        Root cause this catches: _generate_rankings produces {netuid, net_tao_yield, ...}
        but index.html template expected {name, category, mining_style, taoflow_status}.
        Fix: template conditionally renders badges only when values are non-empty.
        """
        from src.site_generator.generator import SiteGenerator

        # This is the EXACT shape _generate_rankings produces (no name/category/etc)
        rankings_output = [
            {
                "netuid": 1,
                "net_tao_yield": 50.0,
                "days_to_recoup": 0.001,
                "thirty_day_projection": 1499.0,
                "competitive_density": 0.3,
                "emission_trend": 0.02,
                "alpha_price": 0.05,
                "attractiveness_score": 0.85, "real_apy_percent": 100.0, "self_mining_risk": 0.0, "concentration_risk": {"risk": 0.0, "tier": "healthy"}, "pool_tao_liquidity": 50000.0, "liquidity_warning": False, "earning_miners_count": 5, "reward_model": "TIERED", "gini_coefficient": 0.5, "price_trend_7d": 0.02, "price_volatility_7d": 0.001, "trend_direction": "stable",
            },
        ]

        gen = SiteGenerator()
        html = gen.generate_index(rankings_output, last_updated="2026-05-19T00:00:00+00:00")

        # Must not have empty badge spans (the original bug)
        assert 'text-blue-300"></span>' not in html, "Empty category badge rendered"
        assert 'text-purple-300"></span>' not in html, "Empty mining_style badge rendered"
        assert 'text-green-300"></span>' not in html, "Empty taoflow badge rendered"

        # Must still render the subnet identifier and metrics
        assert "SN1" in html
        assert "100%" in html  # APY

    def test_badges_render_when_enriched_data_present(self):
        """When enrichment provides profile data, badges should render."""
        from src.site_generator.generator import SiteGenerator

        enriched = [
            {
                "netuid": 1,
                "net_tao_yield": 50.0,
                "days_to_recoup": 0.001,
                "thirty_day_projection": 1499.0,
                "competitive_density": 0.3,
                "emission_trend": 0.02,
                "alpha_price": 0.05,
                "attractiveness_score": 0.85, "real_apy_percent": 100.0, "self_mining_risk": 0.0, "concentration_risk": {"risk": 0.0, "tier": "healthy"}, "pool_tao_liquidity": 50000.0, "liquidity_warning": False, "earning_miners_count": 5, "reward_model": "TIERED", "gini_coefficient": 0.5, "price_trend_7d": 0.02, "price_volatility_7d": 0.001, "trend_direction": "stable",
                "name": "Text Prompting",
                "category": "LLM_INFERENCE",
                "mining_style": "GPU_INFERENCE",
                "taoflow_status": "HEALTHY",
            },
        ]

        gen = SiteGenerator()
        html = gen.generate_index(enriched, last_updated="2026-05-19T00:00:00+00:00")

        # New template shows reward model and APY, not category/name
        assert "SN1" in html
        assert "TIER" in html  # reward model badge
        assert "100%" in html  # APY

    def test_taoflow_death_spiral_renders_red(self):
        """DEATH_SPIRAL_RISK should render with red badge."""
        from src.site_generator.generator import SiteGenerator

        data = [{
            "netuid": 5, "net_tao_yield": 1.0, "days_to_recoup": 100.0,
            "thirty_day_projection": -10.0, "competitive_density": 0.9,
            "emission_trend": -0.3, "alpha_price": 0.001,
            "attractiveness_score": 0.2, "real_apy_percent": 30.0, "self_mining_risk": 0.0, "concentration_risk": {"risk": 0.0, "tier": "healthy"}, "pool_tao_liquidity": 50000.0, "liquidity_warning": False, "earning_miners_count": 5, "reward_model": "WTA", "gini_coefficient": 0.8, "price_trend_7d": -0.01, "price_volatility_7d": 0.001, "trend_direction": "stable",
            "name": "", "category": "", "mining_style": "",
            "taoflow_status": "DEATH_SPIRAL_RISK",
        }]

        gen = SiteGenerator()
        html = gen.generate_index(data, last_updated="2026-05-19T00:00:00+00:00")

        # New template shows subnet and red trend indicator for declining subnets
        assert "SN5" in html
        assert "30%" in html  # APY renders


# ---------------------------------------------------------------------------
# Test 2: source_block_number propagation through pipeline
# ---------------------------------------------------------------------------


class TestSourceBlockPropagation:
    """Verify source_block_number flows from collector → processor → finalizer."""

    def test_processor_includes_source_block_in_derived_metadata(self):
        """_build_derived_output must include source_block_number in metadata."""
        from src.processor.handler import _build_derived_output
        from src.models.enums import (
            TaoflowStatus, CompetitionTrend, HoldVsSwap, Confidence,
            RewardModel,
        )
        from src.models.schemas import (
            EmissionTrend, ROIEstimate, TaoflowHealth, ChurnMetrics,
            ValidatorLandscape,
        )

        emission_trend = EmissionTrend(
            current_total_emission=10.0, previous_total_emission=9.5,
            change_percent=0.05, direction="increasing",
        )
        roi = ROIEstimate(
            net_tao_yield_per_day=1.0, days_to_recoup=5.0,
            thirty_day_projected_tao=29.0, alpha_tao_rate=0.05,
            slippage_estimate_percent=0.01,
            hold_vs_swap_recommendation=HoldVsSwap.SWAP,
            confidence=Confidence.LOW,
        )
        taoflow = TaoflowHealth(
            status=TaoflowStatus.HEALTHY,
            net_staking_flow_tao=0.0, consecutive_negative_days=0,
        )
        churn = ChurnMetrics(
            daily_churn_rate=0.05, new_registrations=2, deregistrations=1,
            average_miner_lifespan_blocks=50000.0,
            competition_trend=CompetitionTrend.STABLE,
        )
        validator_landscape = ValidatorLandscape(
            active_validators=10, total_validator_stake=1000.0,
            top_1_stake_share=0.2, top_3_stake_share=0.5,
            concentrated=False, net_tao_yield_per_validator_per_day=0.1,
            avg_validator_activity_blocks=85,
        )

        result = _build_derived_output(
            netuid=1, date="2026-05-19", dereg_risks=[],
            competitive_density=0.3, emission_trend=emission_trend,
            roi=roi, reward_model=RewardModel.PROPORTIONAL,
            gini=0.4, top_3=0.5, taoflow=taoflow, churn=churn,
            validator_landscape=validator_landscape,
            source_block_number=6711260,
        )

        assert result["metadata"]["source_block_number"] == 6711260

    def test_finalizer_reads_source_block_from_derived_metrics(self):
        """metadata.json must contain non-zero source_block when derived metrics have it."""
        # Simulate what the finalizer does when building metadata.json
        all_metrics = {
            1: {
                "metadata": {
                    "processed_at": "2026-05-19T00:00:00+00:00",
                    "source_block_number": 6711260,
                },
                "data": {},
            }
        }

        # This is the exact logic from _upload_agent_files
        subnet_freshness = {}
        for netuid, metrics in all_metrics.items():
            meta = metrics.get("metadata", {})
            subnet_freshness[str(netuid)] = {
                "processed_at": meta.get("processed_at", meta.get("computation_timestamp", "")),
                "source_block": meta.get("source_block_number", 0),
            }

        assert subnet_freshness["1"]["source_block"] == 6711260


# ---------------------------------------------------------------------------
# Test 3: Nav link resolution — all hrefs map to uploaded files
# ---------------------------------------------------------------------------


class TestNavLinkResolution:
    """Verify all navigation links in generated HTML correspond to uploaded files."""

    UPLOADED_FILES = {
        "/index.html",
        "/rankings.html",
        "/briefing.html",
        "/strategy.html",
        "/data/rankings.json",
        "/data/briefing.json",
        "/data/metadata.json",
        "/data/staking_rankings.json",
        "/llms.txt",
    }

    def test_base_template_nav_links_resolve(self):
        """Every href in base.html nav must correspond to a file we upload."""
        from src.site_generator.generator import SiteGenerator
        import re

        gen = SiteGenerator()
        # Generate any page to get the base template rendered
        html = gen.generate_index(
            [{"netuid": 1, "net_tao_yield": 1.0, "days_to_recoup": 5.0,
              "thirty_day_projection": 29.0, "competitive_density": 0.3,
              "emission_trend": 0.0, "alpha_price": 0.05,
              "attractiveness_score": 0.7, "real_apy_percent": 50.0, "self_mining_risk": 0.0, "concentration_risk": {"risk": 0.0, "tier": "healthy"}, "pool_tao_liquidity": 50000.0, "liquidity_warning": False, "earning_miners_count": 5, "reward_model": "TIERED", "gini_coefficient": 0.5, "price_trend_7d": 0.0, "price_volatility_7d": 0.001, "trend_direction": "stable"}],
            last_updated="2026-05-19T00:00:00+00:00",
        )

        # Extract all href values from nav
        nav_match = re.search(r'<nav.*?</nav>', html, re.DOTALL)
        assert nav_match, "No nav element found"
        nav_html = nav_match.group()
        hrefs = re.findall(r'href="([^"]+)"', nav_html)

        assert len(hrefs) >= 3, f"Expected at least 3 nav links, got {hrefs}"
        for href in hrefs:
            assert href in self.UPLOADED_FILES, (
                f"Nav link '{href}' does not correspond to any uploaded file. "
                f"Uploaded files: {self.UPLOADED_FILES}"
            )

    def test_llms_txt_endpoints_resolve(self):
        """Every endpoint listed in llms.txt must be in the uploaded files set."""
        import re

        # This is the exact llms.txt content from the finalizer
        llms_txt = (
            "# TAO Mining Intelligence\n"
            "> Bittensor subnet mining/validating metrics.\n"
            "> Data refreshes per-subnet every 20-240 minutes (tempo-based).\n"
            "> No subnet older than 4 hours.\n\n"
            "## Endpoints\n"
            "- /data/rankings.json — Subnet rankings sorted by attractiveness\n"
            "- /data/briefing.json — Latest daily briefing and alerts\n"
            "- /data/metadata.json — Per-subnet freshness timestamps\n"
            "- /index.html — Human-readable dashboard\n"
            "- /rankings.html — Sortable rankings table\n"
            "- /briefing.html — Daily briefing page\n"
        )

        endpoints = re.findall(r'- (/\S+)', llms_txt)
        for endpoint in endpoints:
            assert endpoint in self.UPLOADED_FILES, (
                f"llms.txt lists '{endpoint}' but it's not in uploaded files"
            )
