# tests/test_installer_v05.py
from pathlib import Path

from alibaba_scraper.installer import render_systemd_unit


def test_systemd_unit_has_restart_and_hardening() -> None:
    unit = render_systemd_unit(
        executable=Path("/opt/alibaba/bin/alibaba-service"),
        working_directory=Path("/srv/alibaba"),
        env_file=Path("/srv/alibaba/.env"),
        database_path=Path("/srv/alibaba/data/alibaba.sqlite3"),
    )
    assert "ExecStart=/opt/alibaba/bin/alibaba-service" in unit
    assert "Restart=on-failure" in unit
    assert "NoNewPrivileges=true" in unit
    assert "EnvironmentFile=-/srv/alibaba/.env" in unit
