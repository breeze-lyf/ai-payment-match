import sqlite3
import os
from datetime import datetime

class DatabaseManager:
    def __init__(self, db_path="data/paymatch.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversion_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_filename TEXT,
                    output_filename TEXT,
                    month TEXT,
                    total_rows INTEGER,
                    total_amount REAL,
                    status TEXT,
                    timestamp DATETIME
                )
            """)
            conn.commit()

    def add_record(self, original_filename, output_filename, month, total_rows, total_amount, status="SUCCESS"):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO conversion_history 
                (original_filename, output_filename, month, total_rows, total_amount, status, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (original_filename, output_filename, month, total_rows, total_amount, status, datetime.now()))
            conn.commit()

    def get_history(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM conversion_history ORDER BY timestamp DESC")
            return [dict(row) for row in cursor.fetchall()]

    def delete_record(self, record_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM conversion_history WHERE id = ?", (record_id,))
            conn.commit()
