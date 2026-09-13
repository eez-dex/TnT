"""
SQLite caching layer for verified questions.
Prevents regenerating the same topic twice and builds a growing bank over time.
"""

import sqlite3
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, List

from models import MCQQuestion

DB_PATH = Path(__file__).parent / "questions.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # access columns by name
    return conn


def init_db():
    """Create the questions and attempts tables if they don't exist."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                question_hash TEXT UNIQUE NOT NULL,
                topic         TEXT NOT NULL,
                difficulty    TEXT NOT NULL,
                question_json TEXT NOT NULL,
                verified_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                times_served  INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_topic_diff ON questions(topic, difficulty)")

        # ---- NEW: track user attempts ----
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attempts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                topic       TEXT NOT NULL,
                difficulty  TEXT NOT NULL,
                correct     INTEGER NOT NULL,
                time_taken  REAL,
                attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_attempt_topic ON attempts(topic)")

                # ---- NEW: mock test results ----
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mock_results (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                total_q      INTEGER NOT NULL,
                correct      INTEGER NOT NULL,
                wrong        INTEGER NOT NULL,
                skipped      INTEGER NOT NULL,
                score        REAL NOT NULL,
                time_taken   REAL NOT NULL,
                details_json TEXT NOT NULL,
                attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def _hash_question(q: MCQQuestion) -> str:
    """Stable hash of the question text to prevent exact duplicates."""
    return hashlib.sha256(q.question.strip().lower().encode("utf-8")).hexdigest()


def save_question(q: MCQQuestion) -> Optional[int]:
    """
    Insert a verified question. Returns the row id, or None if it was a duplicate.
    """
    h = _hash_question(q)
    try:
        with _connect() as conn:
            cur = conn.execute(
                """INSERT INTO questions (question_hash, topic, difficulty, question_json)
                   VALUES (?, ?, ?, ?)""",
                (h, q.topic, q.difficulty, q.model_dump_json())
            )
            conn.commit()
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None  # duplicate


def get_random_question(topic: str, difficulty: str) -> Optional[dict]:
    """
    Fetch one random question for the given topic/difficulty.
    Returns dict with keys: id, data (MCQQuestion), or None if cache miss.
    """
    with _connect() as conn:
        row = conn.execute(
            """SELECT id, question_json FROM questions
               WHERE LOWER(topic) = LOWER(?) AND LOWER(difficulty) = LOWER(?)
               ORDER BY RANDOM() LIMIT 1""",
            (topic, difficulty)
        ).fetchone()

    if not row:
        return None

    return {
        "id": row["id"],
        "data": MCQQuestion.model_validate_json(row["question_json"]),
    }


def mark_served(question_id: int):
    """Increment the served counter for analytics."""
    with _connect() as conn:
        conn.execute("UPDATE questions SET times_served = times_served + 1 WHERE id = ?", (question_id,))
        conn.commit()


def count_by_topic() -> List[dict]:
    """Return a breakdown of the bank by topic and difficulty."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT topic, difficulty, COUNT(*) as n, SUM(times_served) as served
               FROM questions
               GROUP BY topic, difficulty
               ORDER BY topic, difficulty"""
        ).fetchall()
    return [dict(r) for r in rows]


def total_count() -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]

def log_attempt(topic: str, difficulty: str, correct: bool, time_taken: float):
    """Record a user answer attempt."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO attempts (topic, difficulty, correct, time_taken)
               VALUES (?, ?, ?, ?)""",
            (topic, difficulty, 1 if correct else 0, time_taken),
        )
        conn.commit()


def get_user_stats() -> List[dict]:
    """Per-topic accuracy across all attempts."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT topic,
                      COUNT(*) AS total,
                      SUM(correct) AS correct,
                      AVG(time_taken) AS avg_time
               FROM attempts
               GROUP BY topic
               ORDER BY total DESC"""
        ).fetchall()
    result = []
    for r in rows:
        total = r["total"]
        correct = r["correct"] or 0
        result.append({
            "topic": r["topic"],
            "total": total,
            "correct": correct,
            "accuracy": (correct / total * 100) if total else 0,
            "avg_time": r["avg_time"] or 0,
        })
    return result

def get_all_questions() -> List[dict]:
    """Return every question in the bank — used for assembling mock tests."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, topic, difficulty, question_json FROM questions"
        ).fetchall()
    return [
        {
            "id": r["id"],
            "topic": r["topic"],
            "difficulty": r["difficulty"],
            "data": MCQQuestion.model_validate_json(r["question_json"]),
        }
        for r in rows
    ]


def log_mock_result(
    total_q: int, correct: int, wrong: int, skipped: int,
    score: float, time_taken: float, details: dict,
):
    with _connect() as conn:
        conn.execute(
            """INSERT INTO mock_results
               (total_q, correct, wrong, skipped, score, time_taken, details_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (total_q, correct, wrong, skipped, score, time_taken, json.dumps(details)),
        )
        conn.commit()


def get_mock_history(limit: int = 20) -> List[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM mock_results ORDER BY attempted_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]

def suggest_difficulty(topic: str, current: str) -> Optional[str]:
    """
    Suggest an adjusted difficulty based on the last 10 attempts on this topic.
    Returns None if no adjustment is warranted.
    """
    order = ["Easy", "Medium", "Hard"]
    if current not in order:
        return None

    with _connect() as conn:
        rows = conn.execute(
            """SELECT correct FROM attempts
               WHERE LOWER(topic) = LOWER(?)
               ORDER BY attempted_at DESC LIMIT 10""",
            (topic,),
        ).fetchall()

    if len(rows) < 5:
        return None

    acc = sum(r["correct"] for r in rows) / len(rows)
    idx = order.index(current)

    if acc >= 0.75 and idx < len(order) - 1:
        return order[idx + 1]      # upgrade
    if acc <= 0.40 and idx > 0:
        return order[idx - 1]      # downgrade
    return None