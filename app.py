import sqlite3
from datetime import date

import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth


# Convert to plain dicts
credentials = dict(st.secrets["credentials"])
credentials["usernames"] = dict(credentials["usernames"])
for user in credentials["usernames"]:
    credentials["usernames"][user] = dict(credentials["usernames"][user])  # flatten nested dict

cookie = dict(st.secrets["cookie"])

authenticator = stauth.Authenticate(
    credentials,
    cookie["name"],
    cookie["key"],
    cookie["expiry_days"]
)

authenticator.login("main")

if st.session_state["authentication_status"]:
    # Screen routing setup
    if "screen" not in st.session_state:
        st.session_state["screen"] = "home"

    st.title("🏋️ Workout Tracker")

    # Top nav buttons
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🏠 Home"):
            st.session_state["screen"] = "home"
    with col2:
        if st.button("📅 Workout History"):
            st.session_state["screen"] = "history"
    with col3:
        if st.button("🏆 Personal Bests"):
            st.session_state["screen"] = "bests"

    # Force home screen if workout was just finished
    if st.session_state.get("show_home"):
        st.session_state.pop("show_home")  # Clear flag after one use
        st.session_state["active_workout"] = None
        st.session_state["ready_to_start"] = False

    if st.session_state["screen"] == "home":
        if not st.session_state.get("active_workout") and not st.session_state.get("ready_to_start"):
            st.title("🏠 Home")
            st.markdown(f"Welcome back, **{st.session_state['name']}**!")

            authenticator.logout(location='sidebar')
            st.sidebar.write(f"Welcome, {st.session_state['name']}!")

            username = st.session_state["username"]
            conn = sqlite3.connect("workouts.db")
            c = conn.cursor()

            # === RESUME INCOMPLETE WORKOUT (only if started today)
            c.execute("""
                SELECT wl.id, wl.session_index
                FROM workout_logs wl
                JOIN exercise_logs el ON wl.id = el.workout_log_id
                JOIN session_exercises se ON el.exercise_name = se.exercise_name
                LEFT JOIN set_logs sl ON el.id = sl.exercise_log_id
                WHERE wl.username = ? AND wl.date = DATE('now')
                GROUP BY wl.id
                HAVING COUNT(sl.id) < SUM(se.sets)
                ORDER BY wl.id DESC LIMIT 1
            """, (username,))
            resume = c.fetchone()

            if resume:
                st.subheader("⏳ Incomplete Workout")
                workout_log_id, session_index = resume
                if st.button(f"🔄 Resume Incomplete Session (Session {session_index})"):
                    c.execute("SELECT id, exercise_name FROM exercise_logs WHERE workout_log_id = ?", (workout_log_id,))
                    rows = c.fetchall()
                    exercise_log_ids = {name: eid for eid, name in rows}

                    exercises = []
                    for exercise_name, sets, reps in c.execute("""
                        SELECT exercise_name, sets, reps
                        FROM session_exercises
                        WHERE session_id = (SELECT id FROM sessions WHERE session_index = ?)
                    """, (session_index,)).fetchall():
                        exercise_log_id = exercise_log_ids.get(exercise_name.strip())
                        if exercise_log_id:
                            c.execute("""
                                SELECT el.id FROM workout_logs wl
                                JOIN exercise_logs el ON wl.id = el.workout_log_id
                                WHERE wl.username = ? AND wl.session_index = ?
                                  AND el.exercise_name = ? AND wl.date < DATE('now')
                                ORDER BY wl.date DESC LIMIT 1
                            """, (username, session_index, exercise_name))
                            row = c.fetchone()
                            if row:
                                prev_log_id = row[0]
                                c.execute("SELECT weight FROM set_logs WHERE exercise_log_id = ?", (prev_log_id,))
                                set_weights = [r[0] for r in c.fetchall()]
                                target_weight = min(set_weights) + 5 if len(set_weights) == sets else min(
                                    set_weights or [0.0])
                            else:
                                target_weight = 0.0
                        else:
                            target_weight = 0.0
                        exercises.append((exercise_name, sets, reps, target_weight))

                    st.session_state["active_workout"] = {
                        "session_index": session_index,
                        "workout_log_id": workout_log_id,
                        "exercise_log_ids": exercise_log_ids,
                        "exercises": exercises
                    }

            # === PREVIEW NEXT SESSION
            if st.button("📋 Preview Next Session"):
                c.execute("SELECT COUNT(*) FROM workout_logs WHERE username = ?", (username,))
                completed_sessions = c.fetchone()[0]
                next_session_index = (completed_sessions % 12) + 1

                c.execute("SELECT id FROM sessions WHERE session_index = ?", (next_session_index,))
                session_id = c.fetchone()[0]

                c.execute("SELECT exercise_name, sets, reps FROM session_exercises WHERE session_id = ?", (session_id,))
                exercises = c.fetchall()

                progressed_exercises = []
                for exercise_name, sets, reps in exercises:
                    c.execute("""
                        SELECT el.id FROM workout_logs wl
                        JOIN exercise_logs el ON wl.id = el.workout_log_id
                        WHERE wl.username = ? AND wl.session_index = ? AND el.exercise_name = ?
                        ORDER BY wl.date DESC LIMIT 1
                    """, (username, next_session_index, exercise_name))
                    row = c.fetchone()

                    target_weight = 0.0
                    if row:
                        exercise_log_id = row[0]
                        c.execute("SELECT weight FROM set_logs WHERE exercise_log_id = ?", (exercise_log_id,))
                        set_weights = [r[0] for r in c.fetchall()]
                        if len(set_weights) == sets:
                            target_weight = min(set_weights) + 5
                        elif set_weights:
                            target_weight = min(set_weights)

                    progressed_exercises.append((exercise_name, sets, reps, target_weight))

                st.session_state["previewed_session_index"] = next_session_index
                st.session_state["previewed_session_exercises"] = progressed_exercises
                st.session_state["ready_to_start"] = True

                st.subheader(f"Session {next_session_index}")
                for ex, s, r, w in progressed_exercises:
                    st.write(f"• **{ex}** — {s}x{r}, target: {w} lbs")

            conn.close()

    if st.session_state["screen"] == "history":
        st.subheader("📅 Workout History")
        username = st.session_state["username"]

        conn = sqlite3.connect("workouts.db")
        c = conn.cursor()

        # Pull complete set log history for the user
        c.execute("""
            SELECT wl.id AS workout_id, wl.date, wl.session_index,
                   el.exercise_name, sl.set_number, sl.weight, sl.id AS set_log_id
            FROM workout_logs wl
            JOIN exercise_logs el ON wl.id = el.workout_log_id
            JOIN set_logs sl ON el.id = sl.exercise_log_id
            WHERE wl.username = ?
            ORDER BY wl.date DESC, wl.session_index, el.exercise_name, sl.set_number
        """, (username,))
        rows = c.fetchall()
        conn.close()

        if not rows:
            st.info("No workout history yet.")
        else:
            df = pd.DataFrame(rows, columns=[
                "WorkoutID", "Date", "Session", "Exercise", "SetNum", "Weight", "SetLogID"
            ])

            # Group by Workout (Date + Session)
            grouped = df.groupby(["WorkoutID", "Date", "Session"])

            for (workout_id, date, session), group in grouped:
                # Fetch planned sets/reps from session_exercises table
                conn = sqlite3.connect("workouts.db")
                c = conn.cursor()
                c.execute("""
                    SELECT sets, reps
                    FROM sessions
                    JOIN session_exercises ON sessions.id = session_exercises.session_id
                    WHERE session_index = ?
                    LIMIT 1
                """, (int(session),))
                row = c.fetchone()
                conn.close()

                if row:
                    planned_sets, planned_reps = row
                    title = f"{date} - Session {session} ({planned_sets}x{planned_reps})"
                else:
                    title = f"{date} - Session {session}"

                with st.expander(title):
                    # Build editable table: one row per exercise
                    exercise_groups = group.groupby("Exercise")
                    exercise_rows = []
                    for exercise, sets in exercise_groups:
                        weights = sets.sort_values("SetNum")["Weight"].tolist()
                        set_ids = sets.sort_values("SetNum")["SetLogID"].tolist()
                        weight_str = ", ".join(str(w) for w in weights)
                        key = f"{workout_id}_{exercise}_weights"
                        new_weight_str = st.text_input(f"{exercise}", value=weight_str, key=key)
                        exercise_rows.append((exercise, set_ids, new_weight_str))

                    if st.button(f"💾 Save Changes for {title}", key=f"save_{workout_id}"):
                        conn = sqlite3.connect("workouts.db")
                        c = conn.cursor()
                        updates = 0
                        for _, set_ids, weight_str in exercise_rows:
                            new_weights = [float(w.strip()) for w in weight_str.split(",") if w.strip()]
                            if len(new_weights) == len(set_ids):
                                for set_id, weight in zip(set_ids, new_weights):
                                    c.execute("UPDATE set_logs SET weight = ? WHERE id = ?", (weight, set_id))
                                updates += len(set_ids)
                            else:
                                st.warning("⚠️ Weight count doesn't match number of sets for an exercise.")
                        conn.commit()
                        conn.close()
                        if updates:
                            st.success(f"✅ Updated {updates} weights for Session {session}")
                            st.rerun()

    # === PERSONAL BESTS
    if st.session_state["screen"] == "bests":
        username = st.session_state["username"]
        conn = sqlite3.connect("workouts.db")
        c = conn.cursor()

        st.subheader("🏆 Personal Bests (5x5)")
        c.execute("""
            SELECT el.exercise_name, MAX(sl.weight)
            FROM workout_logs wl
            JOIN exercise_logs el ON wl.id = el.workout_log_id
            JOIN set_logs sl ON el.id = sl.exercise_log_id
            WHERE wl.username = ? AND sl.completed = 1
            GROUP BY el.exercise_name
        """, (username,))
        bests = c.fetchall()
        if bests:
            for ex, w in bests:
                st.write(f"- **{ex}**: {w} lbs")
        else:
            st.info("No personal bests yet. Start your first session!")

    # After preview, show "Begin" button
    if st.session_state.get("ready_to_start"):
        if st.button("✅ Begin This Workout"):
            session_index = st.session_state["previewed_session_index"]
            exercises = st.session_state["previewed_session_exercises"]
            username = st.session_state["username"]

            conn = sqlite3.connect("workouts.db")
            c = conn.cursor()

            # Create workout log
            c.execute("INSERT INTO workout_logs (session_index, username, date) VALUES (?, ?, ?)",
                      (session_index, username, str(date.today())))
            workout_log_id = c.lastrowid

            # Create exercise logs and save their IDs
            exercise_log_ids = {}
            for ex in exercises:
                c.execute("INSERT INTO exercise_logs (workout_log_id, exercise_name) VALUES (?, ?)",
                          (workout_log_id, ex[0]))
                exercise_log_ids[ex[0]] = c.lastrowid

            conn.commit()
            conn.close()

            # Store in session state
            st.session_state["active_workout"] = {
                "session_index": session_index,
                "workout_log_id": workout_log_id,
                "exercise_log_ids": exercise_log_ids,
                "exercises": exercises
            }
            st.session_state["ready_to_start"] = False

    # === Active Workout UI ===
    if st.session_state.get("active_workout"):
        st.subheader(f"Logging: Session {st.session_state['active_workout']['session_index']}")

        for exercise_name, sets, reps, target_weight in st.session_state["active_workout"]["exercises"]:
            st.markdown(f"### {exercise_name} — {sets} sets x {reps} reps")

            if target_weight > 0:
                st.markdown(f"➡️ **Target:** {target_weight} lbs")
                if target_weight % 5 == 0:
                    st.caption(f"💪 Weight increased to {target_weight}")
                else:
                    st.caption(f"🔁 Let’s try {target_weight} again")
            else:
                st.caption("🎯 New exercise — pick your starting weight!")

            exercise_log_id = st.session_state["active_workout"]["exercise_log_ids"][exercise_name]

            for set_num in range(1, sets + 1):
                key = f"{exercise_name}_set_{set_num}"
                # Look up existing value first
                conn = sqlite3.connect("workouts.db")
                c = conn.cursor()
                c.execute("""
                    SELECT weight FROM set_logs
                    WHERE exercise_log_id = ? AND set_number = ?
                """, (exercise_log_id, set_num))
                row = c.fetchone()
                conn.close()

                default_weight = row[0] if row else 0.0

                # Show input with previously saved weight
                weight = st.number_input(
                    f"Set {set_num} weight (lbs)",
                    min_value=0.0,
                    value=default_weight,
                    step=1.0,
                    key=key
                )

                # Save only if it's changed or not saved yet
                if weight > 0.0 and (not row or row[0] != weight):
                    conn = sqlite3.connect("workouts.db")
                    c = conn.cursor()
                    if row:
                        c.execute("""
                            UPDATE set_logs
                            SET weight = ?, completed = 1
                            WHERE exercise_log_id = ? AND set_number = ?
                        """, (weight, exercise_log_id, set_num))
                    else:
                        c.execute("""
                            INSERT INTO set_logs (exercise_log_id, set_number, weight, completed)
                            VALUES (?, ?, ?, 1)
                        """, (exercise_log_id, set_num, weight))
                    conn.commit()
                    conn.close()

        # Don't show the "Finish Workout" button if we're in confirmation mode
        if not st.session_state.get("confirm_finish_requested"):
            if st.button("✅ Finish Workout", key="finish_workout_btn"):
                conn = sqlite3.connect("workouts.db")
                c = conn.cursor()

                workout_log_id = st.session_state["active_workout"]["workout_log_id"]
                incomplete_exercises = []

                for exercise_name, sets, reps, target_weight in st.session_state["active_workout"]["exercises"]:
                    exercise_log_id = st.session_state["active_workout"]["exercise_log_ids"][exercise_name]

                    c.execute("""
                        SELECT COUNT(*) FROM set_logs
                        WHERE exercise_log_id = ?
                    """, (exercise_log_id,))
                    count = c.fetchone()[0]

                    if count < sets:
                        incomplete_exercises.append((exercise_name, count, sets))

                conn.close()

                # Set flag to enter confirmation step
                st.session_state["confirm_finish_requested"] = True
                st.session_state["incomplete_exercises"] = incomplete_exercises
                st.rerun()  # 🔁 force rerender to cleanly hide the button

        # Confirmation section
        if st.session_state.get("confirm_finish_requested"):
            incomplete = st.session_state["incomplete_exercises"]
            if incomplete:
                st.warning("⚠️ Not all sets are filled in:")
                for ex, logged, total in incomplete:
                    st.write(f"- {ex}: {logged} of {total} sets completed")

            if st.button("✅✅ Confirm Finished", key="confirm_finish"):
                st.session_state.pop("active_workout", None)
                st.session_state.pop("confirm_finish_requested", None)
                st.session_state.pop("incomplete_exercises", None)
                st.session_state["show_home"] = True
                st.rerun()

            if st.button("⬅️ Cancel", key="cancel_finish"):
                st.session_state.pop("confirm_finish_requested", None)
                st.session_state.pop("incomplete_exercises", None)
                st.rerun()  # 🔁 bring back the finish button

elif st.session_state["authentication_status"] is False:
    st.error("Username or password is incorrect")
elif st.session_state["authentication_status"] is None:
    st.warning("Please enter your username and password")
