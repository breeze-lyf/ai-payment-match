import sqlite3
import os
import pandas as pd
from datetime import datetime

class DatabaseManager:
    def __init__(self, db_path="data/paymatch.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # 1. 转换记录表
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
            # 2. 员工信息表 (身份证号作为唯一主键)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS employees (
                    id_card TEXT PRIMARY KEY,
                    name TEXT,
                    emp_id TEXT,
                    pc_id TEXT,
                    bank_card TEXT,
                    project TEXT,
                    dept TEXT,
                    last_updated DATETIME
                )
            """)
            conn.commit()

    # --- 员工管理方法 ---
    def upsert_employees(self, df: pd.DataFrame):
        """批量插入或更新员工 (身份证号相同则覆盖)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for _, row in df.iterrows():
                # 统一列名映射
                id_card = str(row.get('身份证号', row.get('id_card', ''))).strip()
                name = str(row.get('姓名', row.get('name', ''))).strip()
                emp_id = str(row.get('工号', row.get('emp_id', ''))).strip()
                pc_id = str(row.get('电脑号', row.get('pc_id', ''))).strip()
                bank_card = str(row.get('银行卡号', row.get('bank_card', ''))).strip()
                project = str(row.get('项目', row.get('project', ''))).strip()
                dept = str(row.get('部门', row.get('dept', row.get('片区', '')))).strip()
                
                if not id_card: continue

                cursor.execute("""
                    INSERT INTO employees (id_card, name, emp_id, pc_id, bank_card, project, dept, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id_card) DO UPDATE SET
                        name=excluded.name,
                        emp_id=excluded.emp_id,
                        pc_id=excluded.pc_id,
                        bank_card=excluded.bank_card,
                        project=excluded.project,
                        dept=excluded.dept,
                        last_updated=excluded.last_updated
                """, (id_card, name, emp_id, pc_id, bank_card, project, dept, now))
            conn.commit()

    def get_all_employees(self):
        import pandas as pd
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query("SELECT * FROM employees", conn)

    def delete_all_employees(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM employees")
            conn.commit()

    # --- 转换历史方法 ---
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
