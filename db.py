import sqlite3
import json

DATABASE_FILE = "users.db"

def get_db_connection():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def get_user_by_name(name):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, id, score, reminder_items, complete_times FROM users WHERE name = ?", (name,))
    row = cur.fetchone()
    conn.close()
    if row:
        reminder_items = []
        if row["reminder_items"]:
            reminder_items = json.loads(row["reminder_items"])
        return {
            "name": row["name"],
            "id": row["id"],
            "score": row["score"],           # can be None if first disposal not done yet
            "reminder_items": reminder_items,
            "complete_times": row["complete_times"]
        }
    return None

def create_user(name, user_id):
    # Create a new user with score=None means no disposal has been done yet
    conn = get_db_connection()
    cur = conn.cursor()
    reminder_items_json = json.dumps([])
    # initial: score = NULL, complete_times=0
    cur.execute("INSERT INTO users (name, id, score, reminder_items, complete_times) VALUES (?, ?, ?, ?, ?)",
                (name, user_id, None, reminder_items_json, 0))
    conn.commit()
    conn.close()

def update_user_score_and_times(name, new_score, new_times):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET score = ?, complete_times = ? WHERE name = ?",
                (new_score, new_times, name))
    conn.commit()
    conn.close()

def update_user_reminder_items(name, reminder_items):
    conn = get_db_connection()
    cur = conn.cursor()
    reminder_items_json = json.dumps(reminder_items)
    cur.execute("UPDATE users SET reminder_items = ? WHERE name = ?",
                (reminder_items_json, name))
    conn.commit()
    conn.close()

def set_user_first_disposal(name, correct):
    # For first disposal: if correct, score=100, times=1; if incorrect, score=0, times=1
    new_score = 100.0 if correct else 0.0
    new_times = 1
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET score = ?, complete_times = ? WHERE name = ?",
                (new_score, new_times, name))
    conn.commit()
    conn.close()