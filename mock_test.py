"""
Mock test engine for SSC CGL — assembly, scoring, and analytics.
"""

import random
from collections import defaultdict
from typing import Callable, Optional

from models import MCQQuestion
import db


# =========================================================
# Configuration
# =========================================================

# SSC CGL Tier-1 marking scheme
MARK_CORRECT = 2.0
MARK_WRONG = -0.5

SECTIONS = [
    "Quantitative Aptitude",
    "Reasoning",
    "English",
    "General Awareness",
]

TOPIC_TO_SUBJECT = {
    # Quantitative Aptitude
    "Profit & Loss": "Quantitative Aptitude",
    "Percentage": "Quantitative Aptitude",
    "Simple Interest": "Quantitative Aptitude",
    "Compound Interest": "Quantitative Aptitude",
    "Ratio & Proportion": "Quantitative Aptitude",
    "Average": "Quantitative Aptitude",
    "Time & Work": "Quantitative Aptitude",
    "Speed & Distance": "Quantitative Aptitude",
    "Algebra": "Quantitative Aptitude",
    "Geometry": "Quantitative Aptitude",
    # Reasoning
    "Number Series": "Reasoning",
    "Coding-Decoding": "Reasoning",
    "Blood Relations": "Reasoning",
    "Direction Sense": "Reasoning",
    "Syllogism": "Reasoning",
    # English
    "Synonyms": "English",
    "Antonyms": "English",
    "Idioms & Phrases": "English",
    "One Word Substitution": "English",
    "Spotting Errors": "English",
    "Spelling": "English",
    # General Awareness
    "Geography": "General Awareness",
    "History": "General Awareness",
    "Polity": "General Awareness",
    "Science": "General Awareness",
}


def subject_of(topic: str) -> str:
    return TOPIC_TO_SUBJECT.get(topic, "General Awareness")


# =========================================================
# Bank inspection
# =========================================================

def bank_availability() -> dict[str, int]:
    """How many questions we currently have in the bank, per subject."""
    counts = {s: 0 for s in SECTIONS}
    for q in db.get_all_questions():
        subj = subject_of(q["topic"])
        if subj in counts:
            counts[subj] += 1
    return counts


# =========================================================
# Test assembly
# =========================================================

def assemble_test(
    per_section: int,
    generator_fn: Callable,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> list[MCQQuestion]:
    """
    Build a mock test with `per_section` questions per subject.

    Pulls from the local cache first. When the cache is short, calls
    `generator_fn(topic, difficulty, prefer_cache=False)` to fill the gap.

    `progress_cb(done, total, message)` is called periodically for UI updates.
    """
    all_q = db.get_all_questions()
    by_subject: dict[str, list] = {s: [] for s in SECTIONS}
    for q in all_q:
        subj = subject_of(q["topic"])
        if subj in by_subject:
            by_subject[subj].append(q)

    total_needed = per_section * len(SECTIONS)
    selected: list[MCQQuestion] = []
    done = 0

    for subj in SECTIONS:
        pool = by_subject[subj][:]
        random.shuffle(pool)
        picked = [item["data"] for item in pool[:per_section]]
        done += len(picked)

        if progress_cb:
            progress_cb(done, total_needed, f"Loading {subj}…")

        deficit = per_section - len(picked)
        if deficit > 0:
            topics = [t for t, s in TOPIC_TO_SUBJECT.items() if s == subj]
            for _ in range(deficit):
                topic = random.choice(topics)
                diff = random.choice(["Easy", "Medium", "Hard"])
                try:
                    q, _src = generator_fn(topic, diff, prefer_cache=False)
                except Exception:
                    q = None
                if q:
                    picked.append(q)
                done += 1
                if progress_cb:
                    progress_cb(done, total_needed, f"Generating {subj}…")

        selected.extend(picked)

    return selected


# =========================================================
# Scoring
# =========================================================

def score_attempt(questions: list[MCQQuestion], answers: list[dict]) -> dict:
    """
    Compute overall + section-wise + topic-wise stats.

    `answers[i]` = {"selected": int|None, "marked": bool, "visited": bool}
    """
    overall = {"correct": 0, "wrong": 0, "skipped": 0}
    by_section = defaultdict(lambda: {"correct": 0, "wrong": 0, "skipped": 0, "total": 0})
    by_topic = defaultdict(lambda: {"correct": 0, "wrong": 0, "skipped": 0, "total": 0})

    for q, a in zip(questions, answers):
        subj = subject_of(q.topic)
        bucket = None
        if a["selected"] is None:
            result = "skipped"
        elif a["selected"] == q.answer_index:
            result = "correct"
        else:
            result = "wrong"

        overall[result] += 1
        by_section[subj][result] += 1
        by_section[subj]["total"] += 1
        by_topic[q.topic][result] += 1
        by_topic[q.topic]["total"] += 1

    score = overall["correct"] * MARK_CORRECT + overall["wrong"] * MARK_WRONG
    max_score = len(questions) * MARK_CORRECT
    attempted = overall["correct"] + overall["wrong"]
    accuracy = (overall["correct"] / attempted * 100) if attempted else 0

    return {
        "overall": overall,
        "score": score,
        "max_score": max_score,
        "accuracy": accuracy,
        "by_section": dict(by_section),
        "by_topic": dict(by_topic),
    }

def build_section(section_name: str, per_section: int, generator_fn) -> list[MCQQuestion]:
    """
    Build ONE section's worth of questions.
    Tries cache first; generates the rest to fill the deficit.
    """
    all_q = db.get_all_questions()
    pool = [q for q in all_q if subject_of(q["topic"]) == section_name]
    random.shuffle(pool)
    picked = [item["data"] for item in pool[:per_section]]

    deficit = per_section - len(picked)
    if deficit > 0:
        topics = [t for t, s in TOPIC_TO_SUBJECT.items() if s == section_name]
        for _ in range(deficit):
            topic = random.choice(topics)
            diff = random.choice(["Easy", "Medium", "Hard"])
            try:
                q, _src = generator_fn(topic, diff, prefer_cache=False)
            except Exception:
                q = None
            if q:
                picked.append(q)

    return picked