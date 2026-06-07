"""Jinja2 static site generator for TAO Mining Intelligence.

Generates HTML pages from pipeline data using Jinja2 templates with
Tailwind CSS (via CDN). No external build tools needed.
"""

import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from jinja2 import Environment, FileSystemLoader


# Default template directory (relative to this file in Lambda container)
_DEFAULT_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "templates"
)


class SiteGenerator:
    """Generate static HTML site from pipeline data."""

    def __init__(self, template_dir: str = None):
        """Initialize Jinja2 environment.

        Args:
            template_dir: Path to templates directory. Defaults to lambda/templates/.
        """
        template_dir = template_dir or _DEFAULT_TEMPLATE_DIR
        self._env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=True,
        )

    def generate_index(self, subnets: list[dict],
                       last_updated: Optional[str] = None) -> str:
        """Generate index.html with all subnets listed."""
        staleness = self._check_staleness(last_updated)
        template = self._env.get_template("index.html")
        return template.render(
            subnets=subnets,
            staleness_warning=staleness,
            last_updated=last_updated or "",
        )

    def generate_rankings_page(self, rankings: list[dict]) -> str:
        """Generate rankings.html with sortable table."""
        template = self._env.get_template("rankings.html")
        return template.render(
            rankings=rankings,
            staleness_warning=False,
            last_updated="",
        )

    def generate_briefing_page(self, briefing: dict) -> str:
        """Generate briefing page."""
        template = self._env.get_template("briefing.html")
        return template.render(
            briefing=briefing,
            staleness_warning=False,
            last_updated="",
        )

    def generate_strategy_page(self) -> str:
        """Generate strategy.html — client-side interactive strategy dashboard."""
        template = self._env.get_template("strategy.html")
        return template.render(staleness_warning=False, last_updated="")

    @staticmethod
    def _check_staleness(last_updated: Optional[str]) -> bool:
        """Check if data is stale (>36h old)."""
        if not last_updated:
            return False
        try:
            updated_dt = datetime.fromisoformat(last_updated)
            if updated_dt.tzinfo is None:
                updated_dt = updated_dt.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - updated_dt
            return age > timedelta(hours=36)
        except (ValueError, TypeError):
            return False
