"""
Streamlit UI — Practice, Mock Test, and History.
Run with: streamlit run app.py
"""

import time
import random
import streamlit as st

import db
import mock_test as mt
from question_generator import get_question

# Optional auto-refresh for the mock timer
try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False


# =========================================================
# Page + bootstrap
# =========================================================
st.set_page_config(page_title="SSC CGL Practice", page_icon="🎯",
                   layout="wide", initial_sidebar_state="expanded")


@st.cache_resource
def _bootstrap():
    db.init_db()
    return True
_bootstrap()


def format_time(seconds) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# =========================================================
# Sidebar
# =========================================================
st.sidebar.title("🎯 SSC CGL Practice")
mode = st.sidebar.radio("Mode", ["📚 Practice", "📝 Mock Test", "📊 History"],
                        label_visibility="collapsed")
st.sidebar.divider()

TOPICS = list(mt.TOPIC_TO_SUBJECT.keys())


# =========================================================
# PRACTICE MODE
# =========================================================
def render_practice():
    topic = st.sidebar.selectbox("Topic", TOPICS)
    difficulty = st.sidebar.radio("Difficulty", ["Easy", "Medium", "Hard"], horizontal=True)

    suggestion = db.suggest_difficulty(topic, difficulty)
    if suggestion:
        st.sidebar.info(f"💡 Based on your accuracy, try **{suggestion}**.")

    use_cache = st.sidebar.checkbox("Prefer cached questions", value=True, key="p_cache")

    if st.sidebar.button("🚀 New Question", use_container_width=True,
                         type="primary", key="p_new"):
        with st.spinner("Preparing question..."):
            q, src = get_question(topic, difficulty, prefer_cache=use_cache)
        if q:
            st.session_state.pq = q
            st.session_state.psrc = src
            st.session_state.psel = None
            st.session_state.psub = False
            st.session_state.pstart = time.time()
        else:
            st.sidebar.error("Could not fetch a question.")
        st.rerun()

    # ---- Sidebar stats ----
    with st.sidebar.expander("📊 Question bank"):
        st.metric("Total verified", db.total_count())
        for row in db.count_by_topic()[:10]:
            st.caption(f"• {row['topic']} / {row['difficulty']}: {row['n']}")

    with st.sidebar.expander("📈 Your performance"):
        stats = db.get_user_stats()
        if not stats:
            st.caption("No attempts yet.")
        else:
            for s in stats[:10]:
                st.write(f"**{s['topic']}** — {s['correct']}/{s['total']} ({s['accuracy']:.0f}%)")

    # ---- Main area ----
    st.title("Practice Room")

    q = st.session_state.get("pq")
    if q is None:
        st.info("👈 Pick a topic, then click **New Question** to begin.")
        return

    badge = "📦 cached" if st.session_state.get("psrc") == "cache" else "🆕 freshly generated"
    st.caption(f"**{q.topic}** · {q.difficulty} · {badge}")
    st.markdown(f"### {q.question}")

    letters = "ABCD"

    if not st.session_state.get("psub"):
        choice = st.radio("Select your answer:",
                          options=list(range(len(q.options))),
                          format_func=lambda i: f"{letters[i]}. {q.options[i]}",
                          index=None, key="p_choice")
        if st.button("Submit Answer", type="primary",
                     disabled=choice is None, key="p_submit"):
            st.session_state.psel = choice
            st.session_state.psub = True
            elapsed = time.time() - st.session_state.pstart
            correct = choice == q.answer_index
            db.log_attempt(q.topic, q.difficulty, correct, elapsed)
            st.rerun()
    else:
        for i, opt in enumerate(q.options):
            if i == q.answer_index:
                st.success(f"✅ **{letters[i]}.** {opt}")
            elif i == st.session_state.psel:
                st.error(f"❌ **{letters[i]}.** {opt}  *(your answer)*")
            else:
                st.write(f"**{letters[i]}.** {opt}")

        st.divider()
        if st.session_state.psel == q.answer_index:
            st.markdown("### 🎉 Correct!")
        else:
            st.markdown(f"### ❌ Incorrect — correct was **{letters[q.answer_index]}**")

        with st.expander("💡 Explanation", expanded=True):
            st.write(q.explanation)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("➡️ Next Question", type="primary", use_container_width=True,
                         key="p_next"):
                with st.spinner("Preparing next question..."):
                    nq, nsrc = get_question(q.topic, q.difficulty,
                                            prefer_cache=st.session_state.p_cache)
                if nq:
                    st.session_state.pq = nq
                    st.session_state.psrc = nsrc
                    st.session_state.psel = None
                    st.session_state.psub = False
                    st.session_state.pstart = time.time()
                st.rerun()
        with col2:
            if st.button("🏠 Clear", use_container_width=True, key="p_clear"):
                st.session_state.pq = None
                st.rerun()


# =========================================================
# MOCK TEST MODE
# =========================================================
def _mock_reset():
    for k in list(st.session_state.keys()):
        if k.startswith("mock_"):
            del st.session_state[k]


def render_mock_setup():
    st.title("📝 Mock Test")
    st.caption("Full-length SSC CGL Tier-1 pattern · +2 correct · −0.5 wrong")

    avail = mt.bank_availability()
    total_avail = sum(avail.values())

    col1, col2 = st.columns(2)

    with col1:
        preset = st.radio("Preset", [
            "Quick (20 Q · 20 min)",
            "Half length (40 Q · 40 min)",
            "Full length (100 Q · 60 min)",
        ])

    presets = {
        "Quick (20 Q · 20 min)":        (5,  20),
        "Half length (40 Q · 40 min)":  (10, 40),
        "Full length (100 Q · 60 min)": (25, 60),
    }
    per_section, minutes = presets[preset]
    total_q = per_section * 4

    with col2:
        st.metric("Total questions", total_q)
        st.metric("Time limit", f"{minutes} min")
        st.metric("Max score", total_q * mt.MARK_CORRECT)

    st.divider()
    st.subheader("Question bank readiness")
    cols = st.columns(4)
    for i, section in enumerate(mt.SECTIONS):
        with cols[i]:
            have = avail[section]
            need = per_section
            delta = have - need
            st.metric(section, f"{have}", delta=f"{delta:+d} vs needed",
                      delta_color="normal" if delta >= 0 else "inverse")

    if total_avail < total_q:
        st.info(
            f"Bank has **{total_avail}** questions; you need **{total_q}**. "
            f"The remaining **{total_q - total_avail}** will be generated — "
            f"this may take 1-3 minutes."
        )

    if st.button("▶️ Start Mock Test", type="primary", use_container_width=True):
        progress = st.progress(0.0, text="Assembling test…")

        def cb(done, total, msg):
            progress.progress(min(done / total, 1.0), text=msg)

        questions = mt.assemble_test(per_section, get_question, progress_cb=cb)

        if len(questions) < total_q:
            st.warning(f"Only assembled {len(questions)} questions. Starting anyway.")

        progress.empty()

        st.session_state.mock_phase = "in_progress"
        st.session_state.mock_questions = questions
        st.session_state.mock_answers = [
            {"selected": None, "marked": False, "visited": False}
            for _ in questions
        ]
        st.session_state.mock_current = 0
        st.session_state.mock_start = time.time()
        st.session_state.mock_time_limit = minutes * 60
        st.session_state.mock_force_submit = False
        st.rerun()


def _mock_submit():
    questions = st.session_state.mock_questions
    answers = st.session_state.mock_answers
    elapsed = time.time() - st.session_state.mock_start

    result = mt.score_attempt(questions, answers)
    result["time_taken"] = elapsed

    # Log individual attempts + the overall result
    for q, a in zip(questions, answers):
        if a["selected"] is not None:
            db.log_attempt(q.topic, q.difficulty,
                           a["selected"] == q.answer_index, elapsed / len(questions))

    details = {
        "by_section": result["by_section"],
        "by_topic": result["by_topic"],
    }
    db.log_mock_result(
        total_q=len(questions),
        correct=result["overall"]["correct"],
        wrong=result["overall"]["wrong"],
        skipped=result["overall"]["skipped"],
        score=result["score"],
        time_taken=elapsed,
        details=details,
    )

    st.session_state.mock_result = result
    st.session_state.mock_phase = "result"
    st.rerun()


def render_mock_in_progress():
    questions = st.session_state.mock_questions
    answers = st.session_state.mock_answers
    current = st.session_state.mock_current
    n = len(questions)

    # ---- Timer ----
    if HAS_AUTOREFRESH:
        st_autorefresh(interval=1000, key="mock_tick")

    elapsed = time.time() - st.session_state.mock_start
    remaining = max(0, st.session_state.mock_time_limit - elapsed)

    if remaining <= 0 and not st.session_state.mock_force_submit:
        st.session_state.mock_force_submit = True
        st.warning("⏰ Time's up! Auto-submitting…")
        _mock_submit()
        return

    top_l, top_r = st.columns([3, 1])
    with top_l:
        st.markdown(f"### Question {current + 1} of {n}")
    with top_r:
        color = "🔴" if remaining <= 60 else "⏱"
        st.markdown(f"### {color} {format_time(remaining)}")

    st.progress((current + 1) / n)

    # ---- Layout: question | palette ----
    q_col, p_col = st.columns([3, 1])

    with q_col:
        q = questions[current]
        a = answers[current]
        a["visited"] = True

        st.caption(f"**{mt.subject_of(q.topic)}** · {q.topic} · {q.difficulty}")
        st.markdown(f"#### {q.question}")

        letters = "ABCD"
        choice = st.radio(
            "Your answer:",
            options=list(range(len(q.options))),
            format_func=lambda i: f"{letters[i]}. {q.options[i]}",
            index=a["selected"],
            key=f"mock_radio_{current}",
            label_visibility="collapsed",
        )
        a["selected"] = choice

        st.divider()
        b1, b2, b3, b4 = st.columns(4)
        with b1:
            if st.button("← Prev", use_container_width=True,
                         disabled=current == 0, key="mock_prev"):
                st.session_state.mock_current = current - 1
                st.rerun()
        with b2:
            mark_label = "🔖 Unmark" if a["marked"] else "🔖 Mark"
            if st.button(mark_label, use_container_width=True, key="mock_mark"):
                a["marked"] = not a["marked"]
                st.rerun()
        with b3:
            if st.button("Clear", use_container_width=True, key="mock_clear"):
                a["selected"] = None
                st.session_state[f"mock_radio_{current}"] = None
                st.rerun()
        with b4:
            if st.button("Next →", use_container_width=True, type="primary",
                         disabled=current == n - 1, key="mock_next"):
                st.session_state.mock_current = current + 1
                st.rerun()

    with p_col:
        st.markdown("**Palette**")
        cols_per_row = 5
        for row_start in range(0, n, cols_per_row):
            cols = st.columns(cols_per_row)
            for j in range(cols_per_row):
                i = row_start + j
                if i >= n:
                    break
                aa = answers[i]
                if aa["marked"]:
                    icon = "🟣"
                elif aa["selected"] is not None:
                    icon = "🟢"
                else:
                    icon = "⚪"
                marker = "▶" if i == current else " "
                with cols[j]:
                    if st.button(f"{marker}{icon}{i+1}", key=f"pal_{i}",
                                 use_container_width=True):
                        st.session_state.mock_current = i
                        st.rerun()

        answered = sum(1 for a in answers if a["selected"] is not None)
        st.divider()
        st.caption(f"✅ Answered: {answered}/{n}")
        st.caption(f"🔖 Marked: {sum(1 for a in answers if a['marked'])}")

        if st.button("🚨 Submit Test", type="primary", use_container_width=True,
                     key="mock_submit_btn"):
            unanswered = sum(1 for a in answers if a["selected"] is None)
            if unanswered > 0:
                st.warning(f"⚠️ {unanswered} unanswered. Click again to confirm.")
                # Two-step confirm
                if st.button("Yes, submit now", type="primary",
                             use_container_width=True, key="mock_confirm"):
                    _mock_submit()
            else:
                _mock_submit()


def render_mock_result():
    result = st.session_state.mock_result
    questions = st.session_state.mock_questions
    answers = st.session_state.mock_answers

    st.title("📊 Mock Test Result")

    o = result["overall"]
    st.markdown(
        f"### Score: **{result['score']:.2f} / {result['max_score']:.0f}**"
    )

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Correct", o["correct"])
    c2.metric("Wrong", o["wrong"])
    c3.metric("Skipped", o["skipped"])
    c4.metric("Accuracy", f"{result['accuracy']:.1f}%")
    c5.metric("Time", format_time(result["time_taken"]))
    c6.metric("Avg/Q", f"{result['time_taken'] / len(questions):.1f}s")

    st.divider()

    # ---- Section-wise ----
    st.subheader("Section-wise breakdown")
    sec_rows = []
    for sec in mt.SECTIONS:
        d = result["by_section"].get(sec, {"correct": 0, "wrong": 0, "skipped": 0, "total": 0})
        if d["total"] == 0:
            continue
        acc = (d["correct"] / d["total"] * 100) if d["total"] else 0
        sec_rows.append({
            "Section": sec,
            "Correct": d["correct"],
            "Wrong": d["wrong"],
            "Skipped": d["skipped"],
            "Accuracy": f"{acc:.0f}%",
        })
    if sec_rows:
        st.dataframe(sec_rows, use_container_width=True, hide_index=True)

    # ---- Topic-wise ----
    st.subheader("Topic-wise breakdown")
    top_rows = []
    for topic, d in sorted(result["by_topic"].items(),
                           key=lambda x: -x[1]["total"]):
        acc = (d["correct"] / d["total"] * 100) if d["total"] else 0
        top_rows.append({
            "Topic": topic,
            "Correct": d["correct"],
            "Wrong": d["wrong"],
            "Skipped": d["skipped"],
            "Total": d["total"],
            "Accuracy": f"{acc:.0f}%",
        })
    st.dataframe(top_rows, use_container_width=True, hide_index=True)

    st.divider()

    # ---- Review ----
    st.subheader("Review & Solutions")
    letters = "ABCD"
    for i, (q, a) in enumerate(zip(questions, answers)):
        if a["selected"] is None:
            icon = "⚪"
            label = f"{icon} Q{i+1} · {q.topic} · *skipped*"
        elif a["selected"] == q.answer_index:
            icon = "✅"
            label = f"{icon} Q{i+1} · {q.topic} · correct"
        else:
            icon = "❌"
            label = f"{icon} Q{i+1} · {q.topic} · incorrect"

        with st.expander(label):
            st.markdown(f"**{q.question}**")
            for j, opt in enumerate(q.options):
                if j == q.answer_index:
                    st.success(f"✅ **{letters[j]}.** {opt}")
                elif j == a["selected"]:
                    st.error(f"❌ **{letters[j]}.** {opt}  *(your answer)*")
                else:
                    st.write(f"**{letters[j]}.** {opt}")
            st.info(f"💡 {q.explanation}")

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔁 Take another mock", type="primary", use_container_width=True,
                     key="result_retake"):
            _mock_reset()
            st.rerun()
    with col2:
        if st.button("🏠 Back to practice", use_container_width=True, key="result_home"):
            _mock_reset()
            st.rerun()


def render_mock_test():
    phase = st.session_state.get("mock_phase")
    if phase == "in_progress":
        render_mock_in_progress()
    elif phase == "result":
        render_mock_result()
    else:
        render_mock_setup()


# =========================================================
# HISTORY MODE
# =========================================================
def render_history():
    st.title("📊 History")

    st.subheader("Mock tests")
    mocks = db.get_mock_history(20)
    if not mocks:
        st.caption("No mock tests yet.")
    else:
        rows = []
        for m in mocks:
            rows.append({
                "Date": m["attempted_at"][:16],
                "Questions": m["total_q"],
                "Correct": m["correct"],
                "Wrong": m["wrong"],
                "Skipped": m["skipped"],
                "Score": f"{m['score']:.2f}",
                "Time": format_time(m["time_taken"]),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)

    st.divider()

    st.subheader("Practice attempts (per topic)")
    stats = db.get_user_stats()
    if not stats:
        st.caption("No practice attempts yet.")
    else:
        rows = [{
            "Topic": s["topic"],
            "Attempts": s["total"],
            "Correct": s["correct"],
            "Accuracy": f"{s['accuracy']:.0f}%",
            "Avg time": f"{s['avg_time']:.1f}s",
        } for s in stats]
        st.dataframe(rows, use_container_width=True, hide_index=True)


# =========================================================
# Route
# =========================================================
if mode == "📚 Practice":
    render_practice()
elif mode == "📝 Mock Test":
    render_mock_test()
else:
    render_history()