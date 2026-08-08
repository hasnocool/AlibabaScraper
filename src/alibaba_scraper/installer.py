# src/alibaba_scraper/installer.py
"""systemd unit rendering and install/uninstall/status helpers."""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SERVICE_NAME = "alibaba-scraper.service"


@dataclass(frozen=True)
class ServiceInstallResult:
    unit_path: Path
    user_mode: bool
    enabled: bool
    started: bool


def render_systemd_unit(
    *,
    executable: Path,
    working_directory: Path,
    env_file: Path,
    database_path: Path,
) -> str:
    """Render a hardened but home-directory-compatible systemd service unit."""
    return f"""[Unit]
Description=AlibabaScraper sourcing intelligence service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={working_directory}
EnvironmentFile=-{env_file}
ExecStart={executable}
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectControlGroups=true
ProtectKernelModules=true
ProtectKernelTunables=true
RestrictSUIDSGID=true
ReadWritePaths={database_path.parent}

[Install]
WantedBy=default.target
"""


def install_systemd_service(
    *,
    user_mode: bool = True,
    env_file: Path = Path(".env"),
    database_path: Path = Path("data/alibaba.sqlite3"),
    start: bool = True,
) -> ServiceInstallResult:
    executable = Path(shutil.which("alibaba-service") or sys.executable).resolve()
    if executable.name.startswith("python"):
        raise RuntimeError("alibaba-service console entrypoint is not installed in PATH")
    working_directory = Path.cwd().resolve()
    env_path = env_file.expanduser().resolve()
    db_path = database_path.expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if user_mode:
        unit_dir = Path.home() / ".config/systemd/user"
    else:
        unit_dir = Path("/etc/systemd/system")
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / SERVICE_NAME
    unit_path.write_text(
        render_systemd_unit(
            executable=executable,
            working_directory=working_directory,
            env_file=env_path,
            database_path=db_path,
        ),
        encoding="utf-8",
    )
    _systemctl(["daemon-reload"], user_mode)
    _systemctl(["enable", SERVICE_NAME], user_mode)
    if start:
        _systemctl(["restart", SERVICE_NAME], user_mode)
    return ServiceInstallResult(unit_path, user_mode, True, start)


def uninstall_systemd_service(*, user_mode: bool = True) -> Path:
    unit_path = (
        Path.home() / ".config/systemd/user" / SERVICE_NAME
        if user_mode
        else Path("/etc/systemd/system") / SERVICE_NAME
    )
    _systemctl(["disable", "--now", SERVICE_NAME], user_mode, check=False)
    if unit_path.exists():
        unit_path.unlink()
    _systemctl(["daemon-reload"], user_mode)
    return unit_path


def systemd_status(*, user_mode: bool = True) -> subprocess.CompletedProcess[str]:
    return _systemctl(["status", SERVICE_NAME, "--no-pager"], user_mode, check=False)


def _systemctl(
    args: list[str], user_mode: bool, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    command = ["systemctl"]
    if user_mode:
        command.append("--user")
    command.extend(args)
    return subprocess.run(
        command,
        check=check,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )
