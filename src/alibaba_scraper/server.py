# src/alibaba_scraper/server.py
"""Direct console entrypoint for the authenticated FastAPI dashboard service."""

import uvicorn

from .config import Settings
from .service import create_app


def main() -> None:
    settings = Settings()
    uvicorn.run(
        create_app(settings.database_path, auth_required=settings.auth_required),
        host=settings.service_host,
        port=settings.service_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
