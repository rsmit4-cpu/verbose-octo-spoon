"""SQLite-opslag voor taken, herinneringen en geheugen."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    due TEXT,
    notes TEXT,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    due_at_utc TEXT NOT NULL,
    repeat TEXT NOT NULL DEFAULT 'none',
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    fact TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

REPEAT_STEPS = {"daily": timedelta(days=1), "weekly": timedelta(weeks=1)}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------- taken ----------
    def add_task(self, title: str, due: str | None, notes: str | None) -> int:
        cur = self.conn.execute(
            "INSERT INTO tasks (title, due, notes, created_at) VALUES (?, ?, ?, ?)",
            (title, due, notes, _now().isoformat()),
        )
        self.conn.commit()
        return cur.lastrowid

    def list_tasks(self, include_done: bool = False) -> list[dict]:
        sql = "SELECT * FROM tasks" + ("" if include_done else " WHERE done = 0")
        sql += " ORDER BY done, due IS NULL, due, id"
        return [dict(r) for r in self.conn.execute(sql)]

    def complete_task(self, task_id: int) -> bool:
        cur = self.conn.execute("UPDATE tasks SET done = 1 WHERE id = ?", (task_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def delete_task(self, task_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # ---------- herinneringen ----------
    def add_reminder(self, chat_id: int, text: str, due_at: datetime, repeat: str = "none") -> int:
        if repeat not in ("none", *REPEAT_STEPS):
            raise ValueError(f"Onbekende herhaling: {repeat}")
        cur = self.conn.execute(
            "INSERT INTO reminders (chat_id, text, due_at_utc, repeat) VALUES (?, ?, ?, ?)",
            (chat_id, text, due_at.astimezone(timezone.utc).isoformat(), repeat),
        )
        self.conn.commit()
        return cur.lastrowid

    def list_reminders(self, chat_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM reminders WHERE chat_id = ? AND active = 1 ORDER BY due_at_utc",
            (chat_id,),
        )
        return [dict(r) for r in rows]

    def cancel_reminder(self, chat_id: int, reminder_id: int) -> bool:
        cur = self.conn.execute(
            "UPDATE reminders SET active = 0 WHERE id = ? AND chat_id = ?", (reminder_id, chat_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def due_reminders(self, now: datetime | None = None) -> list[dict]:
        now = (now or _now()).astimezone(timezone.utc).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM reminders WHERE active = 1 AND due_at_utc <= ? ORDER BY due_at_utc", (now,)
        )
        return [dict(r) for r in rows]

    def mark_reminder_sent(self, reminder: dict, now: datetime | None = None) -> None:
        """Eenmalig: deactiveren. Herhalend: doorschuiven naar de eerstvolgende keer in de toekomst."""
        step = REPEAT_STEPS.get(reminder["repeat"])
        if step is None:
            self.conn.execute("UPDATE reminders SET active = 0 WHERE id = ?", (reminder["id"],))
        else:
            now = now or _now()
            nxt = datetime.fromisoformat(reminder["due_at_utc"])
            while nxt <= now:
                nxt += step
            self.conn.execute(
                "UPDATE reminders SET due_at_utc = ? WHERE id = ?", (nxt.isoformat(), reminder["id"])
            )
        self.conn.commit()

    # ---------- geheugen ----------
    def remember(self, fact: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO memories (fact, created_at) VALUES (?, ?)", (fact, _now().isoformat())
        )
        self.conn.commit()
        return cur.lastrowid

    def memories(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT id, fact FROM memories ORDER BY id")]

    def forget(self, memory_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.conn.commit()
        return cur.rowcount > 0
