"""SQLite 기록 저장소(runs, inspections)와 CSV 내보내기."""
from __future__ import annotations

import csv
import io
import json
import sqlite3
from contextlib import closing
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
# 코드 폴더(OneDrive 등 동기화 폴더일 수 있음) 밖에 둔다
DEFAULT_DB = Path.home() / "PAC2026_data" / "station.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session TEXT, specimen_id TEXT, started_at TEXT, finished_at TEXT,
  final_verdict TEXT, bin TEXT, retakes_used INTEGER, elapsed_ms INTEGER,
  state TEXT, error TEXT, decision_status TEXT, routing_status TEXT, placed_bin TEXT
);
CREATE TABLE IF NOT EXISTS inspections (
  run_id INTEGER, face TEXT, attempt INTEGER, status TEXT, verdict TEXT,
  reasons TEXT, features TEXT, capture_id TEXT, images TEXT, elapsed_ms INTEGER,
  advisor TEXT, sensor_data TEXT, artifacts TEXT, trigger_id TEXT, error TEXT, persistence_error TEXT
);
"""

RUN_COLS = ["id", "session", "specimen_id", "started_at", "finished_at", "final_verdict",
            "bin", "retakes_used", "elapsed_ms", "state", "error", "decision_status", "routing_status", "placed_bin"]


class Store:
    def __init__(self, path=DEFAULT_DB):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with closing(self._conn()) as c, c:
            c.executescript(SCHEMA)
            run_cols = {r[1] for r in c.execute("PRAGMA table_info(runs)")}
            for column in ("decision_status", "routing_status", "placed_bin"):
                if column not in run_cols:
                    c.execute(f"ALTER TABLE runs ADD COLUMN {column} TEXT")
            cols = [r[1] for r in c.execute("PRAGMA table_info(inspections)")]
            if "advisor" not in cols:  # 조언자 기록 열이 생기기 전에 만든 DB
                c.execute("ALTER TABLE inspections ADD COLUMN advisor TEXT")
            for column in ("sensor_data", "artifacts", "trigger_id", "error", "persistence_error"):
                if column not in cols:
                    c.execute(f"ALTER TABLE inspections ADD COLUMN {column} TEXT")

    def _conn(self) -> sqlite3.Connection:
        # 스레드마다 새 연결을 쓰므로 check_same_thread 문제가 없다
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def save_run(self, r: dict) -> int:
        conn = self._conn()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT INTO runs (session, specimen_id, started_at, finished_at, final_verdict,"
                    " bin, retakes_used, elapsed_ms, state, error, decision_status, routing_status, placed_bin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (r["session"], r["specimen_id"], r["started_at"], r["finished_at"],
                     r["final_verdict"], r["bin"], r["retakes_used"], r["elapsed_ms"],
                     r["state"], r["error"], r.get("decision_status"), r.get("routing_status"), r.get("placed_bin")))
                run_id = cur.lastrowid
                for i in r["inspections"]:
                    conn.execute(
                        "INSERT INTO inspections (run_id, face, attempt, status, verdict, reasons,"
                        " features, capture_id, images, elapsed_ms, advisor, sensor_data, artifacts, trigger_id, error, persistence_error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (run_id, i["face"], i["attempt"], i["status"], i["verdict"],
                         json.dumps(i["reasons"], ensure_ascii=False),
                         json.dumps(i["features"], ensure_ascii=False),
                         i["capture_id"], json.dumps(i["images"]), i["elapsed_ms"],
                         json.dumps(i["advisor"], ensure_ascii=False) if i.get("advisor") else None,
                         json.dumps(i.get("sensor_data", {}), ensure_ascii=False),
                         json.dumps(i.get("artifacts", {}), ensure_ascii=False), i.get("trigger_id"),
                         i.get("error"), i.get("persistence_error")))
            return run_id
        finally:
            conn.close()

    def list_runs(self, limit: int = 100) -> list:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_inspections(self, run_id: int) -> list:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM inspections WHERE run_id=? ORDER BY face, attempt",
                                (run_id,)).fetchall()
        finally:
            conn.close()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("reasons", "features", "images", "advisor", "sensor_data", "artifacts"):
                d[k] = json.loads(d[k]) if d[k] else None
            out.append(d)
        return out

    def runs_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(RUN_COLS)
        for r in reversed(self.list_runs(limit=100000)):  # 오래된 순
            w.writerow([r[c] for c in RUN_COLS])
        return buf.getvalue()
