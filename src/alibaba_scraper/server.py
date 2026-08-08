# src/alibaba_scraper/server.py
"""Direct console entrypoint for the local FastAPI dashboard service."""

import uvicorn

from .config import Settings
from .service import create_app


def main() -> None:
    settings = Settings()
    uvicorn.run(
        create_app(settings.database_path),
        host=settings.service_host,
        port=settings.service_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
