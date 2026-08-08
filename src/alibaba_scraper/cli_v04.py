# src/alibaba_scraper/cli_v04.py
"""AlibabaScraper CLI with service, production, and resilience commands."""

from .cli import app
from .cli_extensions import register_commands
from .production_cli import register_production_commands
from .resilience_cli import register_resilience_commands

register_commands(app)
register_production_commands(app)
register_resilience_commands(app)


if __name__ == "__main__":
    app()
