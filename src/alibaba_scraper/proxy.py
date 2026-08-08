# src/alibaba_scraper/proxy.py
"""TLS reverse-proxy configuration rendering for Caddy and Nginx."""

from pathlib import Path


def render_caddyfile(
    domain: str,
    upstream: str = "127.0.0.1:8787",
    email: str | None = None,
) -> str:
    domain = _clean_domain(domain)
    global_options = f"{{\n    email {email.strip()}\n}}\n\n" if email else ""
    return (
        global_options
        + f"{domain} {{\n"
        + "    encode zstd gzip\n"
        + f"    reverse_proxy {upstream} {{\n"
        + "        header_up X-Forwarded-Proto {scheme}\n"
        + "        header_up X-Forwarded-Host {host}\n"
        + "    }\n"
        + "    header {\n"
        + '        Strict-Transport-Security "max-age=31536000; includeSubDomains"\n'
        + '        X-Content-Type-Options "nosniff"\n'
        + '        X-Frame-Options "DENY"\n'
        + '        Referrer-Policy "same-origin"\n'
        + "    }\n"
        + "}\n"
    )


def render_nginx_config(
    domain: str,
    cert_file: Path | str,
    key_file: Path | str,
    upstream: str = "127.0.0.1:8787",
) -> str:
    domain = _clean_domain(domain)
    cert = str(Path(cert_file))
    key = str(Path(key_file))
    return f"""server {{
    listen 80;
    server_name {domain};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl http2;
    server_name {domain};

    ssl_certificate {cert};
    ssl_certificate_key {key};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:10m;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "same-origin" always;

    client_max_body_size 2m;

    location / {{
        proxy_pass http://{upstream};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }}
}}
"""


def write_proxy_config(path: Path | str, content: str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    target.chmod(0o640)
    return target


def _clean_domain(domain: str) -> str:
    value = domain.strip().lower()
    if not value or "/" in value or "://" in value or any(char.isspace() for char in value):
        raise ValueError("domain must be a hostname without scheme, path, or whitespace")
    return value
