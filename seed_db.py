import sqlite3
import pandas as pd

# === Load your CSV ===
df = pd.read_csv("Workout - Sheet1.csv", header=None)
workout_data = df.iloc[4:113].reset_index(drop=True)

# === Parse sessions and exercises ===
sessions = []
current_session = {"name": None, "sets_reps": None, "exercises": []}

for _, row in workout_data.iterrows():
    if isinstance(row[0], str) and row[0].strip().upper() == "DAY":
        continue
    elif pd.notna(row[0]):
        if current_session["name"] and current_session["exercises"]:
            sessions.append(current_session)
        current_session = {
            "name": f"Session {len(sessions) + 1}",
            "sets_reps": row[2],
            "exercises": []
        }
    elif pd.isna(row[0]) and pd.notna(row[1]):
        current_session["exercises"].append(row[1])

if current_session["name"] and current_session["exercises"]:
    sessions.append(current_session)

# === Create DB and tables ===
conn = sqlite3.connect("workouts.db")
c = conn.cursor()

c.execute("DROP TABLE IF EXISTS set_logs")
c.execute("DROP TABLE IF EXISTS exercise_logs")
c.execute("DROP TABLE IF EXISTS workout_logs")
c.execute("DROP TABLE IF EXISTS session_exercises")
c.execute("DROP TABLE IF EXISTS sessions")

c.execute('''
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_index INTEGER UNIQUE,
    name TEXT
)
''')

c.execute('''
CREATE TABLE session_exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    exercise_name TEXT,
    sets INTEGER,
    reps INTEGER,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
)
''')

c.execute('''
CREATE TABLE workout_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_index INTEGER,
    username TEXT,
    date TEXT
)
''')

c.execute('''
CREATE TABLE exercise_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_log_id INTEGER,
    exercise_name TEXT,
    FOREIGN KEY (workout_log_id) REFERENCES workout_logs(id)
)
''')

c.execute('''
CREATE TABLE set_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_log_id INTEGER,
    set_number INTEGER,
    weight REAL,
    completed BOOLEAN,
    FOREIGN KEY (exercise_log_id) REFERENCES exercise_logs(id)
)
''')

# === Seed 12 sessions and their exercises ===
for i, session in enumerate(sessions, start=1):
    c.execute("INSERT INTO sessions (session_index, name) VALUES (?, ?)", (i, session["name"]))
    session_id = c.lastrowid

    try:
        sets, reps = [int(s.strip().split()[0]) for s in session["sets_reps"].split("x")]
    except:
        sets, reps = 5, 5  # fallback

    for exercise in session["exercises"]:
        c.execute("""
            INSERT INTO session_exercises (session_id, exercise_name, sets, reps)
            VALUES (?, ?, ?, ?)
        """, (session_id, exercise, sets, reps))

conn.commit()
conn.close()

print("✅ Database seeded successfully!")
