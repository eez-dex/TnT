"""
SSC CGL Question Generator — Groq + SQLite cache.
Pipeline: cache lookup → generate → verify → cache → serve.
"""

import argparse
import sys
import time
from openai import OpenAI
import json

from config import GROQ_API_KEY, GROQ_MODEL, GROQ_BASE_URL
from models import MCQQuestion, VerificationResult
import db

client = OpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL)

MAX_RETRIES = 3
VERBOSE = True


# =========================================================
# PROMPTS
# =========================================================

def _schema_prompt(schema_class) -> str:
    return (
        f"Output ONLY a valid JSON object matching this schema:\n"
        f"{json.dumps(schema_class.model_json_schema(), indent=2)}\n"
        f"Do not include any other text or markdown."
    )


def _generation_prompt(topic: str, difficulty: str) -> str:
    return f"""You are an expert SSC CGL exam question setter with 15+ years of experience.

Generate ONE original multiple-choice question on the topic "{topic}" with "{difficulty}" difficulty.

STRICT REQUIREMENTS:
1. Factually correct, exactly ONE correct answer.
2. Exactly 4 options (A, B, C, D), all distinct and non-empty.
3. Plausible distractors that are clearly incorrect to an expert.
4. Clear step-by-step explanation for the correct answer.
5. SSC CGL exam style — concise, calculation-based, unambiguous.
6. Do NOT copy from any existing source.
7. Clean numbers that produce calculable answers.

{_schema_prompt(MCQQuestion)}"""


def _verification_prompt(q: MCQQuestion) -> str:
    opts = "\n".join(f"{'ABCD'[i]}. {o}" for i, o in enumerate(q.options))
    return f"""You are an independent, skeptical SSC CGL exam auditor.

AUDIT this question. Be critical — do not rubber-stamp it.

QUESTION: {q.question}

OPTIONS:
{opts}

STATED ANSWER: {'ABCD'[q.answer_index] if 0 <= q.answer_index <= 3 else 'INVALID'}

STATED EXPLANATION: {q.explanation}

YOUR TASKS:
1. Solve the question COMPLETELY INDEPENDENTLY.
2. Compare your answer to the stated answer.
3. Does the explanation justify the correct answer?
4. Is the question unambiguous?
5. Are all 4 options distinct and non-empty?

Mark INVALID if: wrong answer, faulty explanation, multiple interpretations, duplicate options.
List every specific issue in quality_issues.

{_schema_prompt(VerificationResult)}"""


# =========================================================
# LLM CALLS
# =========================================================

def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return text.strip()


def generate_question(topic: str, difficulty: str) -> MCQQuestion:
    r = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": "You are an expert SSC CGL question setter. Output only valid JSON."},
            {"role": "user", "content": _generation_prompt(topic, difficulty)},
        ],
        temperature=0.9,
        response_format={"type": "json_object"},
    )
    return MCQQuestion.model_validate_json(_extract_json(r.choices[0].message.content))


def verify_question(q: MCQQuestion) -> VerificationResult:
    r = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": "You are a skeptical exam auditor. Output only valid JSON."},
            {"role": "user", "content": _verification_prompt(q)},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    return VerificationResult.model_validate_json(_extract_json(r.choices[0].message.content))


# =========================================================
# PIPELINE
# =========================================================

def generate_verified_question(topic: str, difficulty: str) -> MCQQuestion | None:
    """Generate → verify → retry. Does NOT touch the cache."""
    for attempt in range(1, MAX_RETRIES + 1):
        if VERBOSE:
            print(f"── Attempt {attempt}/{MAX_RETRIES} ──")

        try:
            q = generate_question(topic, difficulty)
        except Exception as e:
            print(f"⚠️  Generation failed: {e}")
            time.sleep(1)
            continue

        try:
            v = verify_question(q)
        except Exception as e:
            print(f"⚠️  Verification failed: {e}")
            time.sleep(1)
            continue

        if VERBOSE:
            print(f"🔍 Verdict: {v.verdict} | Issues: {v.quality_issues or 'none'}")

        if v.verdict == "VALID":
            if VERBOSE:
                print("✅ Verified.")
            return q

        if VERBOSE:
            print("❌ Rejected. Retrying...")
        time.sleep(0.5)

    return None


def get_question(topic: str, difficulty: str, prefer_cache: bool = True) -> tuple[MCQQuestion | None, str]:
    """
    Main entry point.
    Returns (question, source) where source is 'cache' or 'generated' or 'failed'.
    """
    if prefer_cache:
        cached = db.get_random_question(topic, difficulty)
        if cached:
            db.mark_served(cached["id"])
            return cached["data"], "cache"

    q = generate_verified_question(topic, difficulty)
    if q:
        row_id = db.save_question(q)
        if row_id and VERBOSE:
            print(f"💾 Saved to cache (id={row_id}).")
        return q, "generated"

    return None, "failed"

def explain_mistake(q: MCQQuestion, chosen_index: int) -> str:
    """
    Ask the AI to generate a personalized explanation of why the user's
    choice was wrong and how to avoid it in future.
    """
    letters = "ABCD"
    prompt = f"""A student answered this SSC CGL question incorrectly.

QUESTION: {q.question}

OPTIONS:
A. {q.options[0]}
B. {q.options[1]}
C. {q.options[2]}
D. {q.options[3]}

CORRECT ANSWER: {letters[q.answer_index]}. {q.options[q.answer_index]}
STUDENT'S CHOICE: {letters[chosen_index]}. {q.options[chosen_index]}

Write a helpful personalized explanation for the student in 3-4 short paragraphs:
1. Walk through the correct method step by step.
2. Point out the specific mistake — why would someone likely choose {letters[chosen_index]}?
3. Give one exam tip to avoid this trap next time.

Keep it concise, warm, and encouraging. Plain text only, no markdown headers."""

    r = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": "You are a patient, encouraging SSC CGL tutor."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    return r.choices[0].message.content.strip()
    
# =========================================================
# DISPLAY
# =========================================================

def display_question(q: MCQQuestion, source: str):
    src = "📦 FROM CACHE" if source == "cache" else "🆕 FRESHLY GENERATED"
    print("\n" + "=" * 60)
    print(f"{src}  |  {q.topic}  |  {q.difficulty}")
    print("=" * 60)
    print(f"\n{q.question}\n")
    for i, opt in enumerate(q.options):
        marker = "✓" if i == q.answer_index else " "
        print(f"  {marker} {'ABCD'[i]}. {opt}")
    print(f"\n💡 {q.explanation}")
    print("=" * 60)


# =========================================================
# CLI
# =========================================================

def cmd_stats():
    db.init_db()
    total = db.total_count()
    print(f"\n📊 Question Bank: {total} verified question(s)\n")
    if total == 0:
        print("   (empty — generate some questions first)")
        return
    print(f"{'Topic':<30} {'Difficulty':<10} {'Count':<8} {'Served'}")
    print("-" * 60)
    for row in db.count_by_topic():
        print(f"{row['topic']:<30} {row['difficulty']:<10} {row['n']:<8} {row['served'] or 0}")


def cmd_build(topic: str, difficulty: str, n: int):
    db.init_db()
    print(f"\n🏗️  Building bank: {n} × {topic} / {difficulty}\n")
    saved = 0
    for i in range(1, n + 1):
        print(f"\n[{i}/{n}]")
        q = generate_verified_question(topic, difficulty)
        if q:
            row_id = db.save_question(q)
            if row_id:
                saved += 1
                print(f"💾 Saved (id={row_id}).")
            else:
                print("⚠️  Duplicate — skipped.")
        else:
            print("⚠️  Failed to generate a verified question this round.")
    print(f"\n✅ Done. {saved}/{n} new questions added to the bank.")


def cmd_interactive():
    db.init_db()
    print("🎯 SSC CGL Question Generator — Cache-enabled")
    print(f"   Bank size: {db.total_count()} questions\n")

    topic = input("Topic (e.g., Profit & Loss): ").strip() or "Profit & Loss"
    difficulty = input("Difficulty (Easy/Medium/Hard): ").strip() or "Easy"
    use_cache = input("Use cache first? [Y/n]: ").strip().lower() != "n"

    q, source = get_question(topic, difficulty, prefer_cache=use_cache)

    if q:
        display_question(q, source)
    else:
        print("\n😔 Could not generate a verified question. Try a different topic.")


def main():
    parser = argparse.ArgumentParser(description="SSC CGL Question Generator")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("stats", help="Show the question bank breakdown")

    p_build = sub.add_parser("build", help="Pre-generate questions into the bank")
    p_build.add_argument("topic")
    p_build.add_argument("difficulty", choices=["Easy", "Medium", "Hard"])
    p_build.add_argument("count", type=int)

    sub.add_parser("start", help="Interactive: generate or fetch a question")

    args = parser.parse_args()

    if args.cmd == "stats":
        cmd_stats()
    elif args.cmd == "build":
        cmd_build(args.topic, args.difficulty, args.count)
    elif args.cmd == "start" or args.cmd is None:
        cmd_interactive()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()