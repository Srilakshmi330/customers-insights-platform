import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from werkzeug.security import generate_password_hash

DB_PATH = Path(__file__).parent / "users.db"

FAILED_ATTEMPT_LIMIT = 5
LOCKOUT_MINUTES = 5

# Old username -> (new username, new branch), for upgrading a users.db seeded
# before the Infinity Central/North/South -> city rename.
BRANCH_RENAME_MAP = {
    "manager_central": ("manager_la", "Los Angeles"),
    "manager_north": ("manager_ny", "New York"),
    "manager_south": ("manager_chicago", "Chicago"),
}


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


ROLE_SCHEMA = """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin', 'analyst', 'manager')),
        branch TEXT,
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        locked_until TEXT
    )
"""


def init_db():
    conn = get_connection()
    conn.execute(ROLE_SCHEMA.replace("CREATE TABLE users", "CREATE TABLE IF NOT EXISTS users"))
    conn.commit()
    _migrate_role_constraint(conn)
    _migrate_add_security_columns(conn)
    _migrate_remove_staff_role(conn)
    _migrate_branch_names(conn)
    conn.close()


def _migrate_role_constraint(conn):
    """Rebuild the users table if it predates the 'analyst' role (old CHECK constraint)."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    if row and "analyst" in row["sql"]:
        return

    conn.execute("ALTER TABLE users RENAME TO users_old")
    conn.execute(ROLE_SCHEMA)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, role, branch) "
        "SELECT id, username, password_hash, role, branch FROM users_old WHERE role != 'staff'"
    )
    conn.execute("DROP TABLE users_old")
    conn.commit()


def _migrate_add_security_columns(conn):
    """Add lockout-tracking columns to users tables predating the auth hardening pass."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "failed_attempts" not in existing:
        conn.execute("ALTER TABLE users ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0")
    if "locked_until" not in existing:
        conn.execute("ALTER TABLE users ADD COLUMN locked_until TEXT")
    conn.commit()


def _migrate_remove_staff_role(conn):
    """Drop the 'staff' role: delete any staff accounts and rebuild the CHECK constraint
    to only allow admin/analyst/manager."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    if not row or "'staff'" not in row["sql"]:
        return

    conn.execute("DELETE FROM users WHERE role = 'staff'")
    conn.execute("ALTER TABLE users RENAME TO users_old")
    conn.execute(ROLE_SCHEMA)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, role, branch, failed_attempts, locked_until) "
        "SELECT id, username, password_hash, role, branch, failed_attempts, locked_until FROM users_old"
    )
    conn.execute("DROP TABLE users_old")
    conn.commit()


def _migrate_branch_names(conn):
    """Rename any accounts still using the old Infinity Central/North/South usernames/branches."""
    for old_username, (new_username, new_branch) in BRANCH_RENAME_MAP.items():
        row = conn.execute("SELECT 1 FROM users WHERE username = ?", (old_username,)).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET username = ?, branch = ? WHERE username = ?",
                (new_username, new_branch, old_username),
            )
    conn.commit()


def seed_default_users():
    """Create any starter accounts that don't already exist yet."""
    conn = get_connection()
    defaults = [
        ("admin", "admin123", "admin", None),
        ("analyst", "analyst123", "analyst", None),
        ("manager_la", "manager123", "manager", "Los Angeles"),
        ("manager_ny", "manager123", "manager", "New York"),
        ("manager_chicago", "manager123", "manager", "Chicago"),
    ]
    for username, password, role, branch in defaults:
        exists = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, branch) VALUES (?, ?, ?, ?)",
                (username, generate_password_hash(password), role, branch),
            )
    conn.commit()
    conn.close()


class User:
    def __init__(self, row):
        self.id = str(row["id"])
        self.username = row["username"]
        self.password_hash = row["password_hash"]
        self.role = row["role"]
        self.branch = row["branch"]
        self.failed_attempts = row["failed_attempts"]
        self.locked_until = row["locked_until"]

    @staticmethod
    def get_by_id(user_id):
        conn = get_connection()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        return User(row) if row else None

    @staticmethod
    def get_by_username(username):
        conn = get_connection()
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        return User(row) if row else None

    @staticmethod
    def list_all():
        conn = get_connection()
        rows = conn.execute("SELECT * FROM users ORDER BY role, username").fetchall()
        conn.close()
        return [User(row) for row in rows]

    @staticmethod
    def create(username, password, role, branch):
        """Returns (user_or_none, error_or_none)."""
        username = username.strip()
        if not username or not password:
            return None, "Username and password are required."
        if len(password) < 6:
            return None, "Password must be at least 6 characters."
        conn = get_connection()
        exists = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        if exists:
            conn.close()
            return None, "That username is already taken."
        conn.execute(
            "INSERT INTO users (username, password_hash, role, branch) VALUES (?, ?, ?, ?)",
            (username, generate_password_hash(password), role, branch),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        return User(row), None

    @staticmethod
    def set_role_branch(user_id, role, branch):
        conn = get_connection()
        conn.execute("UPDATE users SET role = ?, branch = ? WHERE id = ?", (role, branch, user_id))
        conn.commit()
        conn.close()

    @staticmethod
    def set_password(user_id, new_password):
        conn = get_connection()
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new_password), user_id),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def delete(user_id):
        conn = get_connection()
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()

    @staticmethod
    def is_locked(user):
        if not user.locked_until:
            return False
        return datetime.fromisoformat(user.locked_until) > datetime.now()

    @staticmethod
    def register_failed_login(username):
        conn = get_connection()
        row = conn.execute("SELECT failed_attempts FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            conn.close()
            return
        attempts = row["failed_attempts"] + 1
        locked_until = None
        if attempts >= FAILED_ATTEMPT_LIMIT:
            locked_until = (datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
            attempts = 0
        conn.execute(
            "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE username = ?",
            (attempts, locked_until, username),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def register_successful_login(username):
        conn = get_connection()
        conn.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE username = ?",
            (username,),
        )
        conn.commit()
        conn.close()
