import sqlite3
import re
import uuid
from contextlib import contextmanager
from werkzeug.security import generate_password_hash
import config

def normalize_mac(mac_str: str) -> str:
    """
    Normalizes any MAC address string into standard uppercase XX:XX:XX:XX:XX:XX format.
    Handles colons, hyphens, dots, or unseparated 12-char hex strings.
    Returns normalized string, or raises ValueError if invalid.
    """
    if not mac_str:
        return ""
    
    # Strip spaces and punctuation
    cleaned = re.sub(r'[^0-9A-Fa-f]', '', mac_str.strip())
    if len(cleaned) != 12:
        raise ValueError(f"Invalid MAC address format: '{mac_str}'. Expected 12 hexadecimal characters.")
    
    # Format as XX:XX:XX:XX:XX:XX
    return ':'.join(cleaned[i:i+2].upper() for i in range(0, 12, 2))

def is_valid_mac(mac_str: str) -> bool:
    """Returns True if the MAC address can be normalized to a valid 6-byte hardware address."""
    if not mac_str:
        return False
    try:
        normalize_mac(mac_str)
        return True
    except ValueError:
        return False

@contextmanager
def get_db():
    """
    Context manager for database connections.
    Enables foreign keys and uses sqlite3.Row for dict-like column access.
    """
    conn = sqlite3.connect(config.DATABASE_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    """Initializes tables, indexes, and default settings if not already present."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # 1. Students / Users Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                name TEXT,
                roll_number TEXT UNIQUE NOT NULL,
                email TEXT NOT NULL,
                device_token TEXT UNIQUE,
                mac_address TEXT DEFAULT '',
                registered_at TEXT NOT NULL,
                registered_date TEXT
            );
        """)

        # Check and migrate columns in students table if upgrading an existing DB
        cursor.execute("PRAGMA table_info(students)")
        cols_info = {r["name"]: dict(r) for r in cursor.fetchall()}
        cols = list(cols_info.keys())
        
        # Ensure full_name column exists
        if "full_name" not in cols:
            cursor.execute("ALTER TABLE students ADD COLUMN full_name TEXT")
            cursor.execute("UPDATE students SET full_name = name WHERE full_name IS NULL")

        # Ensure device_token column exists
        if "device_token" not in cols:
            cursor.execute("ALTER TABLE students ADD COLUMN device_token TEXT")

        # Ensure registered_at column exists
        if "registered_at" not in cols:
            cursor.execute("ALTER TABLE students ADD COLUMN registered_at TEXT")
            cursor.execute("UPDATE students SET registered_at = registered_date WHERE registered_at IS NULL")

        # If mac_address was created with NOT NULL, migrate table so mac_address is nullable
        if cols_info.get("mac_address", {}).get("notnull") == 1:
            conn.execute("PRAGMA foreign_keys = OFF")
            cursor.execute("""
                CREATE TABLE students_migrated (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    name TEXT,
                    roll_number TEXT UNIQUE NOT NULL,
                    email TEXT NOT NULL,
                    device_token TEXT UNIQUE,
                    mac_address TEXT DEFAULT '',
                    registered_at TEXT NOT NULL,
                    registered_date TEXT
                );
            """)
            cursor.execute("""
                INSERT INTO students_migrated (id, full_name, name, roll_number, email, device_token, mac_address, registered_at, registered_date)
                SELECT id,
                       COALESCE(full_name, name, 'Student'),
                       COALESCE(name, full_name, 'Student'),
                       roll_number,
                       email,
                       device_token,
                       COALESCE(mac_address, ''),
                       COALESCE(registered_at, registered_date, datetime('now')),
                       COALESCE(registered_date, registered_at, datetime('now'))
                FROM students;
            """)
            cursor.execute("DROP TABLE students")
            cursor.execute("ALTER TABLE students_migrated RENAME TO students")
            conn.execute("PRAGMA foreign_keys = ON")

        # Populate device_token for existing students without one
        cursor.execute("SELECT id FROM students WHERE device_token IS NULL")
        for s in cursor.fetchall():
            cursor.execute("UPDATE students SET device_token = ? WHERE id = ?", (str(uuid.uuid4()), s["id"]))

        # 2. Courses Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS courses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_code TEXT UNIQUE NOT NULL,
                course_name TEXT NOT NULL,
                instructor TEXT NOT NULL
            );
        """)

        # 3. Timetable Slots / Class Periods Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS timetable_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id INTEGER NOT NULL,
                day_of_week TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                room_number TEXT NOT NULL,
                FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
            );
        """)

        # 4. Course Enrollments Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS course_enrollments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                course_id INTEGER NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
                FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE,
                UNIQUE(student_id, course_id)
            );
        """)
        
        # 5. Attendance Logs Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                student_id INTEGER,
                course_id INTEGER DEFAULT 1,
                date TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Present',
                client_ip TEXT DEFAULT '127.0.0.1',
                detection_method TEXT NOT NULL DEFAULT 'Device Token Wi-Fi',
                FOREIGN KEY (user_id) REFERENCES students(id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
                FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE SET NULL,
                UNIQUE(student_id, date, course_id)
            );
        """)

        # Check and migrate columns in attendance_logs
        cursor.execute("PRAGMA table_info(attendance_logs)")
        att_cols = [r["name"] for r in cursor.fetchall()]
        if "user_id" not in att_cols:
            cursor.execute("ALTER TABLE attendance_logs ADD COLUMN user_id INTEGER")
            cursor.execute("UPDATE attendance_logs SET user_id = student_id WHERE user_id IS NULL")
        if "client_ip" not in att_cols:
            cursor.execute("ALTER TABLE attendance_logs ADD COLUMN client_ip TEXT DEFAULT '127.0.0.1'")
            cursor.execute("UPDATE attendance_logs SET client_ip = '192.168.1.100' WHERE client_ip IS NULL")
        if "course_id" not in att_cols:
            cursor.execute("ALTER TABLE attendance_logs ADD COLUMN course_id INTEGER DEFAULT 1")
        if "detection_method" not in att_cols:
            cursor.execute("ALTER TABLE attendance_logs ADD COLUMN detection_method TEXT DEFAULT 'Device Token Wi-Fi'")

        # 6. Admins Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        
        # 7. System Config Table & System Settings Table (Key/Value)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        
        # 8. Scan Events Audit History Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scan_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                method TEXT NOT NULL,
                active_macs_found INTEGER NOT NULL,
                students_marked INTEGER NOT NULL,
                details TEXT
            );
        """)

        # 9. Email Alerts Log Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_alerts_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                course_id INTEGER,
                date TEXT NOT NULL,
                recipient_email TEXT NOT NULL,
                subject TEXT NOT NULL,
                status TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                details TEXT,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
                FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE SET NULL
            );
        """)
        
        # Performance Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_user_date ON attendance_logs(user_id, date);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_student_date ON attendance_logs(student_id, date);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance_logs(date);")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_students_device_token ON students(device_token);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_students_roll ON students(roll_number);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timetable_day ON timetable_slots(day_of_week);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_student ON email_alerts_log(student_id);")
        
        # Seed initial admin if admins table is empty
        cursor.execute("SELECT COUNT(*) AS cnt FROM admins")
        if cursor.fetchone()["cnt"] == 0:
            cursor.execute(
                "INSERT INTO admins (username, password_hash, created_at) VALUES (?, ?, datetime('now'))",
                (config.DEFAULT_ADMIN_USERNAME, generate_password_hash(config.DEFAULT_ADMIN_PASSWORD))
            )
            print(f"[Database] Default admin '{config.DEFAULT_ADMIN_USERNAME}' created.")

        # Ensure default course exists (General Campus Session)
        cursor.execute("SELECT COUNT(*) AS cnt FROM courses")
        if cursor.fetchone()["cnt"] == 0:
            cursor.execute(
                "INSERT INTO courses (id, course_code, course_name, instructor) VALUES (1, 'GEN-100', 'General Campus Session', 'Campus Faculty')"
            )
            
        # Seed default settings if not exists
        settings_defaults = {
            # Network Subnet & Verification
            "authorized_subnet": "192.168.1.0/24, 192.168.29.0/24",
            "subnet_range": "192.168.1.0/24, 192.168.29.0/24",
            "allow_localhost": "1",  # 1 = Allow testing from 127.0.0.1 / localhost, 0 = strict Wi-Fi subnet only
            
            # Attendance Time Window Enforcement
            "checkin_start_time": "08:00",       # Window opens daily at 08:00 AM
            "checkin_cutoff_time": "09:30",      # On-time cutoff (marked 'Present')
            "checkin_late_cutoff_time": "10:30", # Late cutoff (marked 'Late'); closed thereafter
            
            # Scanner engine settings (optional / legacy background scan)
            "scan_interval": str(config.DEFAULT_SCAN_INTERVAL),
            "scanner_active": "0",
            "preferred_engine": "auto",
            
            # Email alerts
            "smtp_host": "smtp.gmail.com",
            "smtp_port": "587",
            "smtp_user": "",
            "smtp_password": "",
            "smtp_from": "attendance@campus.edu",
            "smtp_mock_mode": "1",
            "auto_email_absentees": "0"
        }
        for k, v in settings_defaults.items():
            cursor.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)", (k, v))
            cursor.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)", (k, v))
            
    print("[Database] Initialization complete.")

if __name__ == "__main__":
    init_db()
