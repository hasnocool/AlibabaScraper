import json
import logging
from pathlib import Path

from alibaba_scraper.proxy import render_caddyfile, render_nginx_config, write_proxy_config
from alibaba_scraper.structured_logging import JsonFormatter


def test_tls_proxy_rendering_and_safe_json_logging(tmp_path: Path) -> None:
    caddy = render_caddyfile("scraper.example.com", email="ops@example.com")
    assert "scraper.example.com" in caddy
    assert "reverse_proxy 127.0.0.1:8787" in caddy
    assert "Strict-Transport-Security" in caddy

    nginx = render_nginx_config(
        "scraper.example.com",
        "/etc/ssl/cert.pem",
        "/etc/ssl/key.pem",
    )
    assert "ssl_protocols TLSv1.2 TLSv1.3" in nginx
    assert "proxy_pass http://127.0.0.1:8787" in nginx
    target = write_proxy_config(tmp_path / "Caddyfile", caddy)
    assert target.read_text(encoding="utf-8") == caddy

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)
    record.event = "test_event"
    record.api_key = "must-not-leak"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["event"] == "test_event"
    assert "api_key" not in payload
