"""Encrypted connection metadata only; never chart data or conversations."""

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet


class ConnectionStore:
    """Local single-instance storage with an operator-managed encryption key."""

    def __init__(self, path: Path, key_path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Exclusive creation preserves the key across restarts without overwrites.
        try:
            with key_path.open("xb") as key_file:
                key_path.chmod(0o600)
                key_file.write(Fernet.generate_key())
        except FileExistsError:
            pass
        if key_path.stat().st_mode & 0o077:
            raise ValueError("Connection encryption key must have private permissions.")
        self._cipher = Fernet(key_path.read_bytes().strip())
        self._path = path
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS connections "
                "(id TEXT PRIMARY KEY, expires REAL NOT NULL, payload BLOB NOT NULL)"
            )
        path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10)

    @staticmethod
    def _id(namespace: str, session_id: str) -> str:
        return hashlib.sha256(f"{namespace}:{session_id}".encode()).hexdigest()

    def save(
        self, namespace: str, session_id: str, payload: dict[str, Any], expires: float
    ) -> None:
        envelope = {"namespace": namespace, "session_id": session_id, "data": payload}
        encrypted = self._cipher.encrypt(json.dumps(envelope).encode())
        with self._connect() as db:
            db.execute("DELETE FROM connections WHERE expires <= ?", (time.time(),))
            db.execute(
                "INSERT OR REPLACE INTO connections VALUES (?, ?, ?)",
                (self._id(namespace, session_id), expires, encrypted),
            )

    def load(self, namespace: str, session_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            db.execute("DELETE FROM connections WHERE expires <= ?", (time.time(),))
            row = db.execute(
                "SELECT payload FROM connections WHERE id = ?",
                (self._id(namespace, session_id),),
            ).fetchone()
        if row is None:
            return
        envelope = json.loads(self._cipher.decrypt(row[0]))
        if envelope["namespace"] != namespace or envelope["session_id"] != session_id:
            raise ValueError("Connection storage binding mismatch.")
        return envelope["data"]

    def delete(self, namespace: str, session_id: str) -> None:
        with self._connect() as db:
            db.execute(
                "DELETE FROM connections WHERE id = ?",
                (self._id(namespace, session_id),),
            )


def connection_store() -> ConnectionStore | None:
    path = os.environ.get("FOLIUM_AGENTS_CONNECTION_DB")
    key_path = os.environ.get("FOLIUM_AGENTS_CONNECTION_KEY_FILE")
    if not path and not key_path:
        return
    if not path or not key_path:
        raise ValueError("Connection persistence requires both database and key paths.")
    return ConnectionStore(Path(path), Path(key_path))
