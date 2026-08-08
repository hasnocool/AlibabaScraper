from pathlib import Path

from alibaba_scraper.database import Database
from alibaba_scraper.database_maintenance import backup_database, integrity_check, restore_database


async def test_backup_integrity_and_restore_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "live.sqlite3"
    async with Database(path) as database:
        first = await database.create_job("first", 1, 1)
        assert first == 1

    backup = await backup_database(path, tmp_path / "backup.sqlite3")
    assert backup.integrity == "ok"
    assert backup.bytes > 0
    assert len(backup.sha256) == 64
    assert (await integrity_check(backup.path))["status"] == "ok"

    async with Database(path) as database:
        await database.create_job("second", 1, 1)
        assert len(await database.list_jobs()) == 2

    restored = await restore_database(backup.path, path)
    assert restored.integrity == "ok"
    assert restored.safety_backup is not None
    async with Database(path) as database:
        jobs = await database.list_jobs()
        assert [job.query for job in jobs] == ["first"]
