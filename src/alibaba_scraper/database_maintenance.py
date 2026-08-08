# src/alibaba_scraper/database_maintenance.py
"""SQLite backup, integrity-check, and restore helpers for operator workflows."""

import asyncio
import hashlib
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class BackupResult:
    path: str
    bytes: int
    sha256: str
    integrity: str
    created_at: str


@dataclass(frozen=True)
class RestoreResult:
    target: str
    restored_from: str
    safety_backup: str | None
    integrity: str


async def integrity_check(path: Path | str) -> dict[str, object]:
    return await asyncio.to_thread(_integrity_check_sync, Path(path))


async def backup_database(
    source: Path | str,
    destination: Path | str | None = None,
) -> BackupResult:
    source_path = Path(source)
    destination_path = Path(destination) if destination else _default_backup_path(source_path)
    return await asyncio.to_thread(_backup_sync, source_path, destination_path)


async def restore_database(
    backup: Path | str,
    target: Path | str,
    *,
    create_safety_backup: bool = True,
) -> RestoreResult:
    return await asyncio.to_thread(
        _restore_sync,
        Path(backup),
        Path(target),
        create_safety_backup,
    )


def _backup_sync(source: Path, destination: Path) -> BackupResult:
    if not source.exists():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.resolve() == source.resolve():
        raise ValueError("backup destination must differ from the live database")
    if destination.exists():
        destination.unlink()
    source_db = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    target_db = sqlite3.connect(destination)
    try:
        source_db.backup(target_db)
        target_db.commit()
    finally:
        target_db.close()
        source_db.close()
    check = _integrity_check_sync(destination)
    if check["status"] != "ok":
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"backup integrity check failed: {check['details']}")
    return BackupResult(
        path=str(destination),
        bytes=destination.stat().st_size,
        sha256=_sha256(destination),
        integrity="ok",
        created_at=datetime.now(UTC).isoformat(),
    )


def _integrity_check_sync(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"status": "missing", "details": [f"database does not exist: {path}"]}
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = connection.execute("PRAGMA integrity_check").fetchall()
        details = [str(row[0]) for row in rows]
    finally:
        connection.close()
    ok = details == ["ok"]
    return {"status": "ok" if ok else "failed", "details": details}


def _restore_sync(backup: Path, target: Path, create_safety_backup: bool) -> RestoreResult:
    check = _integrity_check_sync(backup)
    if check["status"] != "ok":
        raise RuntimeError(f"refusing restore from invalid backup: {check['details']}")
    target.parent.mkdir(parents=True, exist_ok=True)
    safety: Path | None = None
    if target.exists() and create_safety_backup:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        safety = target.with_name(
            f"{target.stem}.pre-restore-{stamp}{target.suffix}"
        )
        shutil.copy2(target, safety)
    temporary = target.with_name(f".{target.name}.restore-{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    source_db = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    temp_db = sqlite3.connect(temporary)
    try:
        source_db.backup(temp_db)
        temp_db.commit()
    finally:
        temp_db.close()
        source_db.close()
    restored_check = _integrity_check_sync(temporary)
    if restored_check["status"] != "ok":
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"restored database failed integrity check: {restored_check['details']}")
    os.replace(temporary, target)
    return RestoreResult(
        target=str(target),
        restored_from=str(backup),
        safety_backup=str(safety) if safety else None,
        integrity="ok",
    )


def _default_backup_path(source: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return source.parent / "backups" / f"{source.stem}-{stamp}{source.suffix}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
