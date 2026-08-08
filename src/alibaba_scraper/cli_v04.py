# src/alibaba_scraper/cli_v04.py
"""AlibabaScraper CLI with v0.4 service/control-plane extensions registered."""

from .cli import app
from .cli_extensions import register_commands

register_commands(app)


if __name__ == "__main__":
    app()
