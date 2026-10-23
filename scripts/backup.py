"""Daily backup and a restore that proves the backup works.

    ./.venv/Scripts/python.exe -m scripts.backup            # write a backup
    ./.venv/Scripts/python.exe -m scripts.backup --restore PATH

Uses SQLite's online backup API, so it is safe while the app is running.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.settings import Settings  # noqa: E402


def backup(db_path: str, out_dir: str | None = None) -> Path:
    source = Path(db_path)
    if not source.exists():
        raise FileNotFoundError(f"No database at {db_path}")
    target_dir = Path(out_dir or source.parent / "backups")
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"nivora-{stamp}.db"
    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    check = sqlite3.connect(target)
    try:
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"Backup failed its integrity check: {result}")
    finally:
        check.close()
    return target


def restore(backup_path: str, db_path: str) -> dict:
    """Replace the live database with the backup, after checking it opens."""
    source = Path(backup_path)
    if not source.exists():
        raise FileNotFoundError(f"No backup at {backup_path}")
    check = sqlite3.connect(source)
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("The backup is not a healthy database")
        orders = check.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='orders'"
        ).fetchone()[0]
        if not orders:
            raise RuntimeError("The backup has no NIVORA tables")
    finally:
        check.close()
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    for suffix in ("-wal", "-shm"):
        stale = Path(str(target) + suffix)
        if stale.exists():
            stale.unlink()
    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return {"restored": str(target), "from": str(source)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up or restore the NIVORA database")
    parser.add_argument("--db", default=None, help="database path (default: DATABASE_PATH)")
    parser.add_argument("--out", default=None, help="backup directory")
    parser.add_argument("--restore", default=None, help="restore from this backup file")
    args = parser.parse_args()
    settings = Settings.from_env()
    db_path = args.db or settings.database_path
    if args.restore:
        print(restore(args.restore, db_path))
    else:
        path = backup(db_path, args.out)
        print({"backup": str(path), "bytes": path.stat().st_size})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
