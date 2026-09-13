"""
PostgreSQL persistence layer for the SSC CGL practice platform.
Uses SQLAlchemy with psycopg2 for Streamlit compatibility.
"""

import json
import hashlib
from typing import Optional, List
from contextlib import contextmanager

import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from config import DATABASE_URL
from models import MCQQuestion


# =========================================================
# Engine + session factory
# =========================================================

@st.cache_resource
def _get_engine():
    """
    Create the SQLAlchemy engine once per process.
    pool_pre_ping validates connections before use (important for serverless DBs).
    """
    return create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=300,   # Recycle connections every 5 min (Neon may close idle ones)
    )


@contextmanager
def _session():
    """Yield a session and guarantee cleanup."""
    engine = _get_engine()
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def _parse_question(raw) -> MCQQuestion:
    """
    Accept either a JSON string (SQLite) or a dict (PostgreSQL JSONB).
    This makes the code backward-compatible with both backends.
    """
    if isinstance(raw, dict):
        return MCQQuestion.model_validate(raw)
    return MCQQuestion.model_validate_json(raw)

    
# =========================================================
# Schema initialization
# =========================================================

def init_db():
    """Create tables if they don't exist. Called once at app startup."""
    with _session() as s:
        s.execute(text("""
            CREATE TABLE IF NOT EXISTS questions (
                id            SERIAL PRIMARY KEY,
                question_hash TEXT UNIQUE NOT NULL,
                topic         TEXT NOT NULL,
                difficulty    TEXT NOT NULL,
                question_json JSONB NOT NULL,
                verified_at   TIMESTAMPTZ DEFAULT NOW(),
                times_served  INTEGER DEFAULT 0
            )
        """))
        s.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_topic_diff
            ON questions(topic, difficulty)
        """))
        s.execute(text("""
            CREATE TABLE IF NOT EXISTS attempts (
                id           SERIAL PRIMARY KEY,
                topic        TEXT NOT NULL,
                difficulty   TEXT NOT NULL,
                correct      INTEGER NOT NULL,
                time_taken   REAL,
                attempted_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        s.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_attempt_topic
            ON attempts(topic)
        """))
        s.execute(text("""
            CREATE TABLE IF NOT EXISTS mock_results (
                id           SERIAL PRIMARY KEY,
                total_q      INTEGER NOT NULL,
                correct      INTEGER NOT NULL,
                wrong        INTEGER NOT NULL,
                skipped      INTEGER NOT NULL,
                score        REAL NOT NULL,
                time_taken   REAL NOT NULL,
                details_json JSONB NOT NULL,
                attempted_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))


# =========================================================
# Questions
# =========================================================

def _hash_question(q: MCQQuestion) -> str:
    return hashlib.sha256(q.question.strip().lower().encode("utf-8")).hexdigest()


def save_question(q: MCQQuestion) -> Optional[int]:
    """Insert a verified question. Returns row id, or None if duplicate."""
    h = _hash_question(q)
    with _session() as s:
        row = s.execute(text("""
            INSERT INTO questions (question_hash, topic, difficulty, question_json)
            VALUES (:h, :topic, :diff, CAST(:json AS JSONB))
            ON CONFLICT (question_hash) DO NOTHING
            RETURNING id
        """), {
            "h": h,
            "topic": q.topic,
            "diff": q.difficulty,
            "json": q.model_dump_json(),
        }).fetchone()
        return row[0] if row else None


def get_random_question(topic: str, difficulty: str) -> Optional[dict]:
    with _session() as s:
        row = s.execute(text("""
            SELECT id, question_json FROM questions
            WHERE LOWER(topic) = LOWER(:topic)
              AND LOWER(difficulty) = LOWER(:diff)
            ORDER BY RANDOM() LIMIT 1
        """), {"topic": topic, "diff": difficulty}).fetchone()

    if not row:
        return None
    return {
        "id": row[0],
        "data": _parse_question(row[1]),
    }


def mark_served(question_id: int):
    with _session() as s:
        s.execute(text(
            "UPDATE questions SET times_served = times_served + 1 WHERE id = :id"
        ), {"id": question_id})


def count_by_topic() -> List[dict]:
    with _session() as s:
        rows = s.execute(text("""
            SELECT topic, difficulty, COUNT(*) AS n, COALESCE(SUM(times_served), 0) AS served
            FROM questions
            GROUP BY topic, difficulty
            ORDER BY topic, difficulty
        """)).fetchall()
    return [{"topic": r[0], "difficulty": r[1], "n": r[2], "served": r[3]} for r in rows]


def total_count() -> int:
    with _session() as s:
        return s.execute(text("SELECT COUNT(*) FROM questions")).scalar()


def get_all_questions() -> List[dict]:
    with _session() as s:
        rows = s.execute(text(
            "SELECT id, topic, difficulty, question_json FROM questions"
        )).fetchall()
    return [
        {
            "id": r[0],
            "topic": r[1],
            "difficulty": r[2],
            "data": _parse_question(r[3]),
        }
        for r in rows
    ]


# =========================================================
# Attempts
# =========================================================

def log_attempt(topic: str, difficulty: str, correct: bool, time_taken: float):
    with _session() as s:
        s.execute(text("""
            INSERT INTO attempts (topic, difficulty, correct, time_taken)
            VALUES (:topic, :diff, :correct, :time)
        """), {
            "topic": topic, "diff": difficulty,
            "correct": 1 if correct else 0, "time": time_taken,
        })


def get_user_stats() -> List[dict]:
    with _session() as s:
        rows = s.execute(text("""
            SELECT topic,
                   COUNT(*) AS total,
                   SUM(correct) AS correct,
                   AVG(time_taken) AS avg_time
            FROM attempts
            GROUP BY topic
            ORDER BY total DESC
        """)).fetchall()
    result = []
    for r in rows:
        total = r[1]
        correct = r[2] or 0
        result.append({
            "topic": r[0],
            "total": total,
            "correct": correct,
            "accuracy": (correct / total * 100) if total else 0,
            "avg_time": r[3] or 0,
        })
    return result


def suggest_difficulty(topic: str, current: str) -> Optional[str]:
    order = ["Easy", "Medium", "Hard"]
    if current not in order:
        return None
    with _session() as s:
        rows = s.execute(text("""
            SELECT correct FROM attempts
            WHERE LOWER(topic) = LOWER(:topic)
            ORDER BY attempted_at DESC LIMIT 10
        """), {"topic": topic}).fetchall()
    if len(rows) < 5:
        return None
    acc = sum(r[0] for r in rows) / len(rows)
    idx = order.index(current)
    if acc >= 0.75 and idx < len(order) - 1:
        return order[idx + 1]
    if acc <= 0.40 and idx > 0:
        return order[idx - 1]
    return None


# =========================================================
# Mock results
# =========================================================

def log_mock_result(
    total_q: int, correct: int, wrong: int, skipped: int,
    score: float, time_taken: float, details: dict,
):
    with _session() as s:
        s.execute(text("""
            INSERT INTO mock_results
                (total_q, correct, wrong, skipped, score, time_taken, details_json)
            VALUES (:tq, :c, :w, :s, :sc, :time, :details)
        """), {
            "tq": total_q, "c": correct, "w": wrong, "s": skipped,
            "sc": score, "time": time_taken,
            "details": json.dumps(details),
        })


def get_mock_history(limit: int = 20) -> List[dict]:
    with _session() as s:
        rows = s.execute(text("""
            SELECT id, total_q, correct, wrong, skipped, score, time_taken,
                   details_json, attempted_at
            FROM mock_results
            ORDER BY attempted_at DESC LIMIT :lim
        """), {"lim": limit}).fetchall()
    return [{
        "id": r[0], "total_q": r[1], "correct": r[2], "wrong": r[3],
        "skipped": r[4], "score": r[5], "time_taken": r[6],
        "details_json": r[7], "attempted_at": str(r[8]),
    } for r in rows]