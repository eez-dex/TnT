"""
Streamlit UI — Practice, Sectional Mock Test, and History.
Run with: streamlit run app.py
"""

import time
import uuid
import threading
import streamlit as st

import db
import mock_test as mt
from question_generator import get_question, explain_mistake

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
# Background section builder
# =========================================================
# Module-level cache keyed by test_id, so the daemon thread can write
# without touching st.session_state (which is main-thread only).
_section_cache: dict = {}
_section_lock = threading.Lock()


def _bg_build_worker(test_id: str, per_section: int, start_idx: int, total_sections: int):
    """Populate sections start_idx..total_sections-1 in the background."""
    for idx in range(start_idx, total_sections):
        try:
            qs = mt.build_section(mt.SECTIONS[idx], per_section, get_question)
            with _section_lock:
                _section_cache.setdefault(test_id, {})[idx] = qs
        except Exception as e:
            with _section_lock:
                _section_cache.setdefault(test_id, {})[idx] = {"error": str(e)}


def _get_or_build_section(test_id: str, idx: int, per_section: int) -> list:
    """Return the section — from cache if ready, otherwise build now (blocking)."""
    with _section_lock:
        cached = _section_cache.get(test_id, {}).get(idx)
    if cached is not None and not isinstance(cached, dict):
        return cached

    # Not ready: build synchronously (rare — happens if bg thread is slow)
    qs = mt.build_section(mt.SECTIONS[idx], per_section, get_question)
    with _section_lock:
        _section_cache.setdefault(test_id, {})[idx] = qs
    return qs


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
            db.log_attempt(q.topic, q.difficulty, choice == q.answer_index, elapsed)
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
            if st.button("➡️ Next Question", type="primary",
                         use_container_width=True, key="p_next"):
                with st.spinner("Preparing next..."):
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
def _mock_init():
    """Initialize a fresh mock session."""
    for k in list(st.session_state.keys()):
        if k.startswith("mock_"):
            del st.session_state[k]


def render_mock_setup():
    st.title("📝 Mock Test")
    st.caption("Full-length SSC CGL Tier-1 pattern · Sectional timers · +2 correct · −0.5 wrong")

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
    per_section, total_minutes = presets[preset]
    total_q = per_section * 4
    per_sec_min = total_minutes // 4

    col1, col2, col3 = st.columns(3)
    col1.metric("Questions", total_q)
    col2.metric("Total time", f"{total_minutes} min")
    col3.metric("Per section", f"{per_sec_min} min")

    st.divider()
    st.subheader("Question bank readiness")
    avail = mt.bank_availability()
    cols = st.columns(4)
    for i, sec in enumerate(mt.SECTIONS):
        with cols[i]:
            have, need = avail[sec], per_section
            st.metric(sec, f"{have}", delta=f"{have - need:+d} vs needed",
                      delta_color="normal" if have >= need else "inverse")

    st.info(
        "Sections will be prepared **progressively**: "
        "Section 1 loads now; Sections 2–4 generate in the background while you attempt Section 1."
    )

    if st.button("▶️ Start Mock Test", type="primary", use_container_width=True):
        _mock_init()
        test_id = str(uuid.uuid4())[:8]

        # Build Section 1 only (blocking, brief)
        progress = st.progress(0.0, text="Preparing Section 1 — Quantitative Aptitude…")
        sec0 = mt.build_section(mt.SECTIONS[0], per_section, get_question)
        progress.progress(1.0, text="Section 1 ready ✔")
        progress.empty()

        # Kick off background builder for Sections 2-4
        threading.Thread(
            target=_bg_build_worker,
            args=(test_id, per_section, 1, len(mt.SECTIONS)),
            daemon=True,
        ).start()

        # Set state
        st.session_state.mock_test_id = test_id
        st.session_state.mock_phase = "in_progress"
        st.session_state.mock_per_section = per_section
        st.session_state.mock_per_sec_min = per_sec_min
        st.session_state.mock_current_section = 0
        st.session_state.mock_current_q = 0
        st.session_state.mock_section_start_ts = time.time()
        st.session_state.mock_sections = [{
            "name": mt.SECTIONS[0],
            "questions": sec0,
            "answers": [{"selected": None, "marked": False, "visited": False} for _ in sec0],
            "elapsed": 0.0,
        }]
        st.session_state.mock_timeout_handled = False
        st.rerun()


def _current_section():
    return st.session_state.mock_sections[st.session_state.mock_current_section]


def _advance_section():
    """Move to the next section (or submit if last)."""
    sec_idx = st.session_state.mock_current_section
    elapsed = time.time() - st.session_state.mock_section_start_ts
    st.session_state.mock_sections[sec_idx]["elapsed"] = elapsed

    next_idx = sec_idx + 1
    if next_idx >= len(mt.SECTIONS):
        _mock_submit()
        return

    # Fetch (or build) next section
    test_id = st.session_state.mock_test_id
    per_section = st.session_state.mock_per_section

    with _section_lock:
        ready = _section_cache.get(test_id, {}).get(next_idx)
    if ready is None or isinstance(ready, dict):
        with st.spinner(f"Preparing Section {next_idx+1} — {mt.SECTIONS[next_idx]}…"):
            ready = mt.build_section(mt.SECTIONS[next_idx], per_section, get_question)
        with _section_lock:
            _section_cache.setdefault(test_id, {})[next_idx] = ready

    st.session_state.mock_sections.append({
        "name": mt.SECTIONS[next_idx],
        "questions": ready,
        "answers": [{"selected": None, "marked": False, "visited": False} for _ in ready],
        "elapsed": 0.0,
    })
    st.session_state.mock_current_section = next_idx
    st.session_state.mock_current_q = 0
    st.session_state.mock_section_start_ts = time.time()
    st.session_state.mock_timeout_handled = False
    st.rerun()


def _mock_submit():
    """Finalize test: score, log, and move to result phase."""
    all_q, all_a, all_t = [], [], []
    for sec in st.session_state.mock_sections:
        all_q.extend(sec["questions"])
        all_a.extend(sec["answers"])
        all_t.append(sec["elapsed"])

    result = mt.score_attempt(all_q, all_a)
    total_time = sum(all_t)

    # Log practice attempts too
    for q, a in zip(all_q, all_a):
        if a["selected"] is not None:
            db.log_attempt(q.topic, q.difficulty,
                           a["selected"] == q.answer_index,
                           total_time / max(len(all_q), 1))

    # Save with full question + answer data for later review
    details = {
        "by_section": result["by_section"],
        "by_topic": result["by_topic"],
        "questions": [q.model_dump() for q in all_q],
        "answers": all_a,
        "section_names": [s["name"] for s in st.session_state.mock_sections],
        "section_times": all_t,
    }
    db.log_mock_result(
        total_q=len(all_q),
        correct=result["overall"]["correct"],
        wrong=result["overall"]["wrong"],
        skipped=result["overall"]["skipped"],
        score=result["score"],
        time_taken=total_time,
        details=details,
    )

    result["time_taken"] = total_time
    st.session_state.mock_result = result
    st.session_state.mock_phase = "result"
    st.rerun()


def render_mock_in_progress():
    if HAS_AUTOREFRESH:
        st_autorefresh(interval=1000, key="mock_tick")

    sec_idx = st.session_state.mock_current_section
    sec = _current_section()
    questions = sec["questions"]
    answers = sec["answers"]
    current = st.session_state.mock_current_q
    n = len(questions)

    # ---- Section timer ----
    per_sec_secs = st.session_state.mock_per_sec_min * 60
    elapsed_in_sec = time.time() - st.session_state.mock_section_start_ts
    remaining = max(0, per_sec_secs - elapsed_in_sec)

    if remaining <= 0 and not st.session_state.get("mock_timeout_handled"):
        st.session_state.mock_timeout_handled = True
        st.warning(f"⏰ Time's up for {sec['name']}! Moving to next section…")
        time.sleep(1.2)
        _advance_section()
        return

    # ---- Header ----
    top_l, top_r = st.columns([3, 1])
    with top_l:
        st.markdown(f"### Section {sec_idx + 1}/4 — {sec['name']}")
        st.caption(f"Question {current + 1} of {n}")
    with top_r:
        color = "🔴" if remaining <= 60 else "⏱"
        st.markdown(f"### {color} {format_time(remaining)}")
        st.caption(f"Section {sec_idx + 1}/4")

    st.progress((current + 1) / n)

    # ---- Layout: question | palette ----
    q_col, p_col = st.columns([3, 1])

    with q_col:
        q = questions[current]
        a = answers[current]
        a["visited"] = True

        st.markdown(f"#### {q.question}")
        letters = "ABCD"
        choice = st.radio(
            "Your answer:",
            options=list(range(len(q.options))),
            format_func=lambda i: f"{letters[i]}. {q.options[i]}",
            index=a["selected"],
            key=f"mock_radio_{sec_idx}_{current}",
            label_visibility="collapsed",
        )
        a["selected"] = choice

        st.divider()
        b1, b2, b3, b4 = st.columns(4)
        with b1:
            if st.button("← Prev", use_container_width=True,
                         disabled=current == 0, key=f"mock_prev_{sec_idx}"):
                st.session_state.mock_current_q = current - 1
                st.rerun()
        with b2:
            mark_label = "🔖 Unmark" if a["marked"] else "🔖 Mark"
            if st.button(mark_label, use_container_width=True,
                         key=f"mock_mark_{sec_idx}_{current}"):
                a["marked"] = not a["marked"]
                st.rerun()
        with b3:
            if st.button("Clear", use_container_width=True,
                         key=f"mock_clear_{sec_idx}_{current}"):
                a["selected"] = None
                st.session_state[f"mock_radio_{sec_idx}_{current}"] = None
                st.rerun()
        with b4:
            if st.button("Next →", use_container_width=True, type="primary",
                         disabled=current == n - 1, key=f"mock_next_{sec_idx}"):
                st.session_state.mock_current_q = current + 1
                st.rerun()

    with p_col:
        st.markdown("**Section palette**")
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
                    if st.button(f"{marker}{icon}{i+1}",
                                 key=f"pal_{sec_idx}_{i}",
                                 use_container_width=True):
                        st.session_state.mock_current_q = i
                        st.rerun()

        answered = sum(1 for a in answers if a["selected"] is not None)
        st.divider()
        st.caption(f"✅ Answered: {answered}/{n}")
        st.caption(f"🔖 Marked: {sum(1 for a in answers if a['marked'])}")

        # Submit current section
        if st.button("✅ Submit Section", type="primary",
                     use_container_width=True, key=f"submit_sec_{sec_idx}"):
            _advance_section()


def render_mock_result():
    result = st.session_state.mock_result
    secs = st.session_state.mock_sections
    all_q, all_a = [], []
    for sec in secs:
        all_q.extend(sec["questions"])
        all_a.extend(sec["answers"])

    st.title("📊 Mock Test Result")
    o = result["overall"]
    st.markdown(f"### Score: **{result['score']:.2f} / {result['max_score']:.0f}**")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Correct", o["correct"])
    c2.metric("Wrong", o["wrong"])
    c3.metric("Skipped", o["skipped"])
    c4.metric("Accuracy", f"{result['accuracy']:.1f}%")
    c5.metric("Time", format_time(result["time_taken"]))
    c6.metric("Avg/Q", f"{result['time_taken'] / max(len(all_q), 1):.1f}s")

    # ---- Section-wise (with per-section time) ----
    st.divider()
    st.subheader("Section-wise breakdown")
    rows = []
    for i, sec in enumerate(secs):
        d = result["by_section"].get(sec["name"], {"correct": 0, "wrong": 0, "skipped": 0, "total": 0})
        acc = (d["correct"] / d["total"] * 100) if d["total"] else 0
        rows.append({
            "Section": sec["name"],
            "Correct": d["correct"],
            "Wrong": d["wrong"],
            "Skipped": d["skipped"],
            "Accuracy": f"{acc:.0f}%",
            "Time used": format_time(sec["elapsed"]),
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)

    # ---- Topic-wise ----
    st.subheader("Topic-wise breakdown")
    top_rows = []
    for topic, d in sorted(result["by_topic"].items(), key=lambda x: -x[1]["total"]):
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

    # ---- Review (all questions, tagged by section) ----
    st.divider()
    st.subheader("Review & Solutions")
    letters = "ABCD"
    for sec in secs:
        st.markdown(f"**{sec['name']}**")
        for i, (q, a) in enumerate(zip(sec["questions"], sec["answers"])):
            if a["selected"] is None:
                icon = "⚪"
                tag = "skipped"
            elif a["selected"] == q.answer_index:
                icon = "✅"
                tag = "correct"
            else:
                icon = "❌"
                tag = "incorrect"
            with st.expander(f"{icon} {sec['name'][:3]} Q{i+1} · {q.topic} · {tag}"):
                _render_question_review(q, a, letters)

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔁 Take another mock", type="primary",
                     use_container_width=True, key="result_retake"):
            _mock_init()
            st.rerun()
    with col2:
        if st.button("🏠 Back to practice", use_container_width=True,
                     key="result_home"):
            _mock_init()
            st.rerun()


def _render_question_review(q, a, letters: str = "ABCD"):
    """Render one question in review mode with solution + optional AI tutor."""
    st.markdown(f"**{q.question}**")
    for j, opt in enumerate(q.options):
        if j == q.answer_index:
            st.success(f"✅ **{letters[j]}.** {opt}")
        elif j == a.get("selected"):
            st.error(f"❌ **{letters[j]}.** {opt}  *(your answer)*")
        else:
            st.write(f"**{letters[j]}.** {opt}")

    st.info(f"💡 **Solution:** {q.explanation}")

    # AI personalized explanation — only for wrong attempts
    if a.get("selected") is not None and a["selected"] != q.answer_index:
        qhash = f"ai_expl_{abs(hash(q.question))}_{a['selected']}"
        if st.button("🧠 Get personalized explanation", key=qhash):
            with st.spinner("Asking your AI tutor…"):
                try:
                    text = explain_mistake(q, a["selected"])
                    st.session_state[qhash + "_text"] = text
                except Exception as e:
                    st.error(f"Could not generate explanation: {e}")
        if st.session_state.get(qhash + "_text"):
            st.success(st.session_state[qhash + "_text"])


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
        for m in mocks:
            score_pct = (m["score"] / (m["total_q"] * 2) * 100) if m["total_q"] else 0
            header = (
                f"📝 {m['attempted_at'][:16]}  ·  "
                f"Score {m['score']:.2f}/{m['total_q'] * 2}  ·  "
                f"{score_pct:.0f}%  ·  "
                f"{m['correct']}✅ {m['wrong']}❌ {m['skipped']}⚪"
            )
            with st.expander(header):
                details = m.get("details_json")
                if isinstance(details, str):
                    import json
                    details = json.loads(details)

                questions = details.get("questions", [])
                answers = details.get("answers", [])

                if not questions:
                    st.caption("Detailed review not available for this attempt.")
                    continue

                letters = "ABCD"
                wrong_items = [
                    (i, q, a) for i, (q, a) in enumerate(zip(questions, answers))
                    if a.get("selected") is not None and a["selected"] != q["answer_index"]
                ]

                st.markdown(f"**Wrong answers ({len(wrong_items)})**")
                if not wrong_items:
                    st.success("No wrong answers — well done! 🎉")
                else:
                    for idx, qdict, adict in wrong_items:
                        q = type("Q", (), qdict)()  # lightweight namespace
                        q.question = qdict["question"]
                        q.options = qdict["options"]
                        q.answer_index = qdict["answer_index"]
                        q.explanation = qdict["explanation"]
                        q.topic = qdict["topic"]
                        q.difficulty = qdict["difficulty"]

                        st.markdown(f"**Q{idx+1} · {q.topic}**")
                        _render_question_review(q, adict, letters)
                        st.divider()

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