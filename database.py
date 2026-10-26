import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
import pandas as pd

DB_PATH = os.getenv("TRACKER_DB_PATH", str(Path(__file__).with_name("tracker.db")))


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS students (
            student_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL UNIQUE,
            profile_url TEXT NOT NULL,
            batch TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            snapshot_date TEXT NOT NULL,
            total_solved INTEGER NOT NULL CHECK(total_solved >= 0),
            easy_solved INTEGER,
            medium_solved INTEGER,
            hard_solved INTEGER,
            collected_at TEXT NOT NULL,
            UNIQUE(student_id, snapshot_date),
            FOREIGN KEY(student_id) REFERENCES students(student_id)
        );
        CREATE TABLE IF NOT EXISTS fetch_errors (
            error_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            username TEXT NOT NULL,
            attempted_at TEXT NOT NULL,
            error_message TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_student_date ON snapshots(student_id, snapshot_date);
        """)


def sync_roster(csv_path=None):
    csv_path = csv_path or str(Path(__file__).with_name("students.csv"))
    if not os.path.exists(csv_path):
        return 0
    df = pd.read_csv(csv_path).fillna("")
    required = {"name", "username", "profile_url", "batch"}
    if not required.issubset(df.columns):
        raise ValueError(f"students.csv must contain columns: {', '.join(sorted(required))}")
    changed = 0
    with get_connection() as conn:
        for row in df.to_dict("records"):
            username = str(row["username"]).strip().lstrip("@").strip()
            if not username or username.lower() in {"username", "your_username"}:
                continue
            profile_url = str(row["profile_url"]).strip() or f"https://leetcode.com/u/{username}/"
            conn.execute("""INSERT INTO students(name, username, profile_url, batch) VALUES(?,?,?,?)
                ON CONFLICT(username) DO UPDATE SET name=excluded.name, profile_url=excluded.profile_url, batch=excluded.batch""",
                (str(row["name"]).strip(), username, profile_url, str(row["batch"]).strip()))
            changed += 1
    return changed


def list_students():
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM students ORDER BY batch, name, username").fetchall()]


def get_snapshots():
    with get_connection() as conn:
        return pd.read_sql_query("SELECT * FROM snapshots ORDER BY snapshot_date", conn)


def get_latest_snapshot_date():
    with get_connection() as conn:
        row = conn.execute("SELECT MAX(snapshot_date) AS d FROM snapshots").fetchone()
        return row["d"] if row else None


def _get_total_as_of(student_id, as_of):
    with get_connection() as conn:
        row = conn.execute("SELECT total_solved FROM snapshots WHERE student_id=? AND snapshot_date<=? ORDER BY snapshot_date DESC LIMIT 1", (student_id, as_of.isoformat())).fetchone()
        return int(row["total_solved"]) if row else None


def _latest_total(student_id):
    with get_connection() as conn:
        row = conn.execute("SELECT total_solved FROM snapshots WHERE student_id=? ORDER BY snapshot_date DESC LIMIT 1", (student_id,)).fetchone()
        return int(row["total_solved"]) if row else None


def _get_first_total_in_range(student_id, start_date, end_date):
    """Return the first observed total in an inclusive date range, used to bootstrap a baseline."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT total_solved FROM snapshots WHERE student_id=? AND snapshot_date>=? AND snapshot_date<=? ORDER BY snapshot_date ASC LIMIT 1",
            (student_id, start_date.isoformat(), end_date.isoformat())
        ).fetchone()
        return int(row["total_solved"]) if row else None


def _nonnegative_delta(current, baseline):
    if current is None or baseline is None:
        return None
    # Counts can decrease due to profile changes; don't show a negative progress score.
    return max(0, current - baseline)


def get_weekly_progress(student_id):
    today = date.today()
    # Current week begins Monday; baseline is the latest snapshot on or before the prior Sunday.
    days_since_monday = today.weekday()
    week_start = today - timedelta(days=days_since_monday)
    baseline_date = week_start - timedelta(days=1)
    current = _latest_total(student_id)
    baseline = _get_total_as_of(student_id, baseline_date)
    if baseline is None:
        # First-time setup midweek: establish a zero-progress baseline from the first snapshot this week.
        baseline = _get_first_total_in_range(student_id, week_start, today)
    return _nonnegative_delta(current, baseline)


def get_monthly_progress(student_id, previous_month=False):
    today = date.today()
    if previous_month:
        first_current_month = today.replace(day=1)
        last_month_end = first_current_month - timedelta(days=1)
        month_start = last_month_end.replace(day=1)
        current = _get_total_as_of(student_id, last_month_end)
        baseline = _get_total_as_of(student_id, month_start - timedelta(days=1))
        if baseline is None:
            baseline = _get_first_total_in_range(student_id, month_start, last_month_end)
    else:
        month_start = today.replace(day=1)
        current = _latest_total(student_id)
        baseline = _get_total_as_of(student_id, month_start - timedelta(days=1))
        if baseline is None:
            baseline = _get_first_total_in_range(student_id, month_start, today)
    return _nonnegative_delta(current, baseline)


def get_badge_for_progress(progress):
    if progress is None:
        return "Pending baseline"
    if progress >= 40:
        return "🏆 Platinum"
    if progress >= 20:
        return "🥇 Gold"
    if progress >= 10:
        return "🥈 Silver"
    return "🥉 Bronze"


def record_snapshot(student_id, total_solved, easy_solved=None, medium_solved=None, hard_solved=None, snapshot_date=None):
    snapshot_date = snapshot_date or date.today().isoformat()
    collected_at = datetime.now().astimezone().isoformat(timespec="seconds")
    with get_connection() as conn:
        existing = conn.execute("SELECT snapshot_id FROM snapshots WHERE student_id=? AND snapshot_date=?", (student_id, snapshot_date)).fetchone()
        if existing:
            conn.execute("UPDATE snapshots SET total_solved=?, easy_solved=?, medium_solved=?, hard_solved=?, collected_at=? WHERE snapshot_id=?",
                         (int(total_solved), easy_solved, medium_solved, hard_solved, collected_at, existing["snapshot_id"]))
        else:
            conn.execute("INSERT INTO snapshots(student_id, snapshot_date, total_solved, easy_solved, medium_solved, hard_solved, collected_at) VALUES(?,?,?,?,?,?,?)",
                         (student_id, snapshot_date, int(total_solved), easy_solved, medium_solved, hard_solved, collected_at))


def record_error(student_id, username, message):
    with get_connection() as conn:
        conn.execute("INSERT INTO fetch_errors(student_id, username, attempted_at, error_message) VALUES(?,?,?,?)",
                     (student_id, username, datetime.now().astimezone().isoformat(timespec="seconds"), str(message)[:1000]))
