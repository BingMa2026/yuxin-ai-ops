"""独立于 PostgreSQL 和 Redis 的本地加密结果恢复日志。

这是私有恢复日志，不是业务 ORM 数据库。同一网关部署的所有工作进程
必须共用持久化路径和加密密钥。
"""

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from app.config.setting import settings
from app.core.exceptions import CustomException

from .secret_codec import decrypt_settings, encrypt_settings


def identity(auth, request_id):
    app_id, user_id = auth.app_id, getattr(getattr(auth, "user", None), "id", None)
    if type(app_id) is not int or app_id <= 0 or type(user_id) is not int or user_id <= 0:
        raise CustomException(msg="模型请求缺少有效的本人身份", status_code=401)
    return app_id, user_id, request_id


def fingerprint(data):
    return hashlib.sha256(json.dumps(data.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class ResultJournal:
    def __init__(self):
        self.path = Path(settings.MODEL_RESULT_JOURNAL_PATH).resolve()

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        db.execute("""CREATE TABLE IF NOT EXISTS results (
            app_id INTEGER NOT NULL, user_id INTEGER NOT NULL, request_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL, state TEXT NOT NULL, payload TEXT,
            attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
            lease_until REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL,
            PRIMARY KEY(app_id, request_id))""")
        db.commit()
        return db

    def claim(self, key, request_hash):
        app_id, user_id, request_id = key
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM results WHERE app_id=? AND request_id=?", (app_id, request_id)).fetchone()
            if row:
                if row["user_id"] != user_id or row["fingerprint"] != request_hash:
                    raise CustomException(msg="请求编号已使用，请勿用同一编号提交不同内容", status_code=409)
                if row["state"] not in {"GENERATED", "SETTLED"}:
                    raise CustomException(msg="原请求仍在执行或状态待核对，暂不重复生成", code=40906, status_code=409)
                return decrypt_settings(row["payload"])
            db.execute("INSERT INTO results(app_id,user_id,request_id,fingerprint,state,updated_at) VALUES(?,?,?,?,'CLAIMED',?)", (*key, request_hash, time.time()))
            return None

    def save(self, key, request_hash, payload):
        encrypted = encrypt_settings(payload)
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM results WHERE app_id=? AND request_id=?", (key[0], key[2])).fetchone()
            if row and (row["user_id"] != key[1] or row["fingerprint"] != request_hash):
                raise CustomException(msg="请求归属或内容已变化，不能覆盖生成结果", status_code=409)
            if row and row["state"] in {"GENERATED", "SETTLED"}:
                return  # 已持久化的生成结果不能覆盖。
            db.execute(
                """INSERT INTO results(app_id,user_id,request_id,fingerprint,state,payload,updated_at)
                VALUES(?,?,?,?,'GENERATED',?,?) ON CONFLICT(app_id,request_id) DO UPDATE SET
                state='GENERATED',payload=excluded.payload,updated_at=excluded.updated_at""",
                (*key, request_hash, encrypted, time.time()),
            )

    def fail(self, key):
        with closing(self._connect()) as db, db:
            db.execute("UPDATE results SET state='UNKNOWN',updated_at=? WHERE app_id=? AND user_id=? AND request_id=? AND state='CLAIMED'", (time.time(), *key))

    def read(self, key):
        with closing(self._connect()) as db:
            row = db.execute("SELECT payload FROM results WHERE app_id=? AND user_id=? AND request_id=? AND state IN ('GENERATED','SETTLED')", key).fetchone()
            return decrypt_settings(row[0]) if row else None

    def take(self, key, *, force=False):
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM results WHERE app_id=? AND user_id=? AND request_id=?", key).fetchone()
            now = time.time()
            if not row or row["state"] != "GENERATED" or row["lease_until"] > now or row["attempts"] >= 12 or (not force and row["retry_at"] > now):
                return None
            db.execute("UPDATE results SET lease_until=?,attempts=attempts+1 WHERE app_id=? AND user_id=? AND request_id=?", (now + 300, *key))
            return decrypt_settings(row["payload"])

    def finish(self, key, charged):
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM results WHERE app_id=? AND user_id=? AND request_id=?", key).fetchone()
            if not row or row["state"] == "SETTLED":
                return
            payload = decrypt_settings(row["payload"])
            payload["result"].update(charged_credits=charged, settlement_status="SETTLED")
            db.execute("UPDATE results SET state='SETTLED',payload=?,lease_until=0,updated_at=? WHERE app_id=? AND user_id=? AND request_id=?", (encrypt_settings(payload), time.time(), *key))

    def defer(self, key):
        with closing(self._connect()) as db, db:
            db.execute("UPDATE results SET lease_until=0,retry_at=?,updated_at=? WHERE app_id=? AND user_id=? AND request_id=? AND state='GENERATED'", (time.time() + 60, time.time(), *key))

    def due(self):
        with closing(self._connect()) as db:
            return [
                tuple(row)
                for row in db.execute(
                    "SELECT app_id,user_id,request_id FROM results WHERE state='GENERATED' AND attempts<12 AND retry_at<=? AND lease_until<=? ORDER BY updated_at LIMIT 32", (time.time(), time.time())
                )
            ]

    def prune(self):
        # 保留墓碑记录，结果过期后也不能把已付费请求当成新请求。
        with closing(self._connect()) as db, db:
            db.execute("UPDATE results SET state='EXPIRED',payload=NULL WHERE state='SETTLED' AND updated_at<?", (time.time() - settings.MODEL_RESULT_RETENTION_DAYS * 86400,))
