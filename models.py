import uuid
from datetime import datetime, date, time
from werkzeug.security import check_password_hash, generate_password_hash
from database import get_db, normalize_mac, is_valid_mac

class Student:
    @staticmethod
    def create(full_name: str, roll_number: str, email: str, device_token: str = None, mac_address: str = ""):
        """Registers a new student with permanent browser device token and auto-enrolls in default courses."""
        token = device_token.strip() if device_token else str(uuid.uuid4())
        norm_mac = ""
        if mac_address and is_valid_mac(mac_address):
            norm_mac = normalize_mac(mac_address)

        clean_name = full_name.strip()
        clean_roll = roll_number.strip().upper()
        clean_email = email.strip().lower()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO students (full_name, name, roll_number, email, device_token, mac_address, registered_at, registered_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (clean_name, clean_name, clean_roll, clean_email, token, norm_mac, now_str, now_str)
            )
            student_id = cursor.lastrowid
            
            # Auto-enroll in all existing courses
            cursor.execute(
                """
                INSERT OR IGNORE INTO course_enrollments (student_id, course_id)
                SELECT ?, id FROM courses
                """,
                (student_id,)
            )
            return student_id

    @staticmethod
    def get_by_id(student_id: int):
        with get_db() as conn:
            row = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["full_name"] = d.get("full_name") or d.get("name") or "Student"
            d["name"] = d["full_name"]
            return d

    @staticmethod
    def get_by_roll(roll_number: str):
        if not roll_number:
            return None
        with get_db() as conn:
            row = conn.execute("SELECT * FROM students WHERE UPPER(roll_number) = UPPER(?)", (roll_number.strip(),)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["full_name"] = d.get("full_name") or d.get("name") or "Student"
            d["name"] = d["full_name"]
            return d

    @staticmethod
    def get_by_device_token(device_token: str):
        if not device_token:
            return None
        with get_db() as conn:
            row = conn.execute("SELECT * FROM students WHERE device_token = ?", (device_token.strip(),)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["full_name"] = d.get("full_name") or d.get("name") or "Student"
            d["name"] = d["full_name"]
            return d

    @staticmethod
    def get_by_mac(mac_address: str):
        if not mac_address:
            return None
        norm_mac = normalize_mac(mac_address)
        with get_db() as conn:
            row = conn.execute("SELECT * FROM students WHERE mac_address = ?", (norm_mac,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["full_name"] = d.get("full_name") or d.get("name") or "Student"
            d["name"] = d["full_name"]
            return d

    @staticmethod
    def reset_device_token(student_id: int):
        """Clears student's browser device token so they can re-register on a new device."""
        with get_db() as conn:
            conn.execute("UPDATE students SET device_token = NULL WHERE id = ?", (student_id,))

    @staticmethod
    def bind_device_token(student_id: int, device_token: str, full_name: str = None, email: str = None):
        """Pairs a new device token to an existing student."""
        with get_db() as conn:
            if full_name and email:
                clean_name = full_name.strip()
                conn.execute(
                    """
                    UPDATE students 
                    SET device_token = ?, full_name = ?, name = ?, email = ?
                    WHERE id = ?
                    """,
                    (device_token.strip(), clean_name, clean_name, email.strip().lower(), student_id)
                )
            else:
                conn.execute("UPDATE students SET device_token = ? WHERE id = ?", (device_token.strip(), student_id))

    @staticmethod
    def get_all(search_query: str = None):
        with get_db() as conn:
            if search_query:
                q = f"%{search_query.strip()}%"
                rows = conn.execute(
                    """
                    SELECT s.*, 
                           (SELECT COUNT(*) FROM attendance_logs WHERE (user_id = s.id OR student_id = s.id) AND status = 'Present') AS total_present,
                           (SELECT COUNT(*) FROM attendance_logs WHERE (user_id = s.id OR student_id = s.id) AND status = 'Late') AS total_late,
                           (SELECT COUNT(*) FROM attendance_logs WHERE (user_id = s.id OR student_id = s.id)) AS total_attended
                    FROM students s
                    WHERE s.full_name LIKE ? OR s.name LIKE ? OR s.roll_number LIKE ? OR s.email LIKE ? OR s.device_token LIKE ?
                    ORDER BY s.roll_number ASC
                    """,
                    (q, q, q, q, q)
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT s.*, 
                           (SELECT COUNT(*) FROM attendance_logs WHERE (user_id = s.id OR student_id = s.id) AND status = 'Present') AS total_present,
                           (SELECT COUNT(*) FROM attendance_logs WHERE (user_id = s.id OR student_id = s.id) AND status = 'Late') AS total_late,
                           (SELECT COUNT(*) FROM attendance_logs WHERE (user_id = s.id OR student_id = s.id)) AS total_attended
                    FROM students s
                    ORDER BY s.roll_number ASC
                    """
                ).fetchall()
            
            result = []
            for r in rows:
                d = dict(r)
                d["full_name"] = d.get("full_name") or d.get("name") or "Student"
                d["name"] = d["full_name"]
                result.append(d)
            return result

    @staticmethod
    def update(student_id: int, name: str, roll_number: str, email: str, mac_address: str = "", device_token: str = None):
        norm_mac = ""
        if mac_address and is_valid_mac(mac_address):
            norm_mac = normalize_mac(mac_address)
        clean_name = name.strip()
        with get_db() as conn:
            if device_token is not None:
                conn.execute(
                    """
                    UPDATE students
                    SET full_name = ?, name = ?, roll_number = ?, email = ?, mac_address = ?, device_token = ?
                    WHERE id = ?
                    """,
                    (clean_name, clean_name, roll_number.strip().upper(), email.strip().lower(), norm_mac, device_token, student_id)
                )
            else:
                conn.execute(
                    """
                    UPDATE students
                    SET full_name = ?, name = ?, roll_number = ?, email = ?, mac_address = ?
                    WHERE id = ?
                    """,
                    (clean_name, clean_name, roll_number.strip().upper(), email.strip().lower(), norm_mac, student_id)
                )

    @staticmethod
    def delete(student_id: int):
        with get_db() as conn:
            conn.execute("DELETE FROM students WHERE id = ?", (student_id,))

    @staticmethod
    def count() -> int:
        with get_db() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM students").fetchone()
            return row["cnt"] if row else 0


class Attendance:
    @staticmethod
    def mark_attendance(user_id: int, client_ip: str = "127.0.0.1", status: str = "Present", 
                        date_str: str = None, time_str: str = None, course_id: int = 1, 
                        detection_method: str = "Device Token Wi-Fi") -> tuple[bool, str, dict]:
        """
        Marks attendance for user on given date and course.
        Prevents duplicate daily check-ins.
        Returns (is_new: bool, message: str, log_dict: dict).
        """
        today = date_str or date.today().isoformat()
        current_time = time_str or datetime.now().strftime("%H:%M:%S")

        with get_db() as conn:
            # Check if attendance already recorded today for this student
            existing = conn.execute(
                """
                SELECT * FROM attendance_logs 
                WHERE (user_id = ? OR student_id = ?) 
                  AND date = ? 
                  AND (course_id = ? OR course_id IS NULL)
                """,
                (user_id, user_id, today, course_id)
            ).fetchone()

            if existing:
                ex_dict = dict(existing)
                return False, f"Attendance already recorded today as {ex_dict['status']} at {ex_dict['timestamp']}.", ex_dict

            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO attendance_logs (user_id, student_id, course_id, date, timestamp, status, client_ip, detection_method)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, user_id, course_id, today, current_time, status, client_ip, detection_method)
                )
                log_id = cursor.lastrowid
                created_log = {
                    "id": log_id,
                    "user_id": user_id,
                    "student_id": user_id,
                    "course_id": course_id,
                    "date": today,
                    "timestamp": current_time,
                    "status": status,
                    "client_ip": client_ip,
                    "detection_method": detection_method
                }
                return True, f"Attendance successfully recorded as {status}!", created_log
            except Exception as e:
                return False, f"Database error recording attendance: {str(e)}", {}

    @staticmethod
    def mark_present(student_id: int, course_id: int = 1, date_str: str = None, time_str: str = None, detection_method: str = "Device Token Wi-Fi") -> bool:
        """Legacy helper for backward compatibility."""
        success, _, _ = Attendance.mark_attendance(
            user_id=student_id,
            client_ip="127.0.0.1",
            status="Present",
            date_str=date_str,
            time_str=time_str,
            course_id=course_id,
            detection_method=detection_method
        )
        return success

    @staticmethod
    def get_student_today_log(user_id: int, date_str: str = None):
        """Returns today's attendance record for student if marked, else None."""
        today = date_str or date.today().isoformat()
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT a.*, COALESCE(c.course_code, 'GEN-100') AS course_code, COALESCE(c.course_name, 'General Session') AS course_name
                FROM attendance_logs a
                LEFT JOIN courses c ON a.course_id = c.id
                WHERE (a.user_id = ? OR a.student_id = ?) AND a.date = ?
                ORDER BY a.timestamp DESC
                LIMIT 1
                """,
                (user_id, user_id, today)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_today_logs():
        today = date.today().isoformat()
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT a.id, COALESCE(a.user_id, a.student_id) AS user_id, a.course_id, a.date, a.timestamp, a.status, 
                       a.client_ip, a.detection_method,
                       s.full_name, s.name, s.roll_number, s.email, s.device_token, s.mac_address,
                       COALESCE(c.course_code, 'GEN-100') AS course_code,
                       COALESCE(c.course_name, 'General Session') AS course_name
                FROM attendance_logs a
                JOIN students s ON (a.user_id = s.id OR a.student_id = s.id)
                LEFT JOIN courses c ON a.course_id = c.id
                WHERE a.date = ?
                ORDER BY a.timestamp DESC
                """,
                (today,)
            ).fetchall()
            
            result = []
            for r in rows:
                d = dict(r)
                d["full_name"] = d.get("full_name") or d.get("name") or "Student"
                d["name"] = d["full_name"]
                result.append(d)
            return result

    @staticmethod
    def get_logs(date_filter: str = None, roll_number: str = None, status_filter: str = None, course_id: int = None, limit: int = 500):
        with get_db() as conn:
            query = """
                SELECT a.id, COALESCE(a.user_id, a.student_id) AS user_id, a.course_id, a.date, a.timestamp, a.status, 
                       a.client_ip, a.detection_method,
                       s.full_name, s.name, s.roll_number, s.email, s.device_token, s.mac_address,
                       COALESCE(c.course_code, 'GEN-100') AS course_code,
                       COALESCE(c.course_name, 'General Session') AS course_name
                FROM attendance_logs a
                JOIN students s ON (a.user_id = s.id OR a.student_id = s.id)
                LEFT JOIN courses c ON a.course_id = c.id
                WHERE 1=1
            """
            params = []
            if date_filter:
                query += " AND a.date = ?"
                params.append(date_filter.strip())
            if roll_number:
                query += " AND UPPER(s.roll_number) LIKE UPPER(?)"
                params.append(f"%{roll_number.strip()}%")
            if status_filter:
                query += " AND a.status = ?"
                params.append(status_filter.strip())
            if course_id:
                query += " AND a.course_id = ?"
                params.append(course_id)

            query += " ORDER BY a.date DESC, a.timestamp DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, tuple(params)).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["full_name"] = d.get("full_name") or d.get("name") or "Student"
                d["name"] = d["full_name"]
                result.append(d)
            return result

    @staticmethod
    def get_student_history(student_id: int):
        """Calculates student attendance metrics, present vs late days, and logs."""
        today = date.today().isoformat()
        with get_db() as conn:
            # Distinct session dates in the system
            distinct_days_row = conn.execute("SELECT COUNT(DISTINCT date) AS total_days FROM attendance_logs").fetchone()
            total_active_days = distinct_days_row["total_days"] if distinct_days_row and distinct_days_row["total_days"] > 0 else 1

            # Student attendance logs
            rows = conn.execute(
                """
                SELECT a.id, a.date, a.timestamp, a.status, a.client_ip, a.detection_method,
                       COALESCE(c.course_code, 'GEN-100') AS course_code,
                       COALESCE(c.course_name, 'General Session') AS course_name
                FROM attendance_logs a
                LEFT JOIN courses c ON a.course_id = c.id
                WHERE a.user_id = ? OR a.student_id = ?
                ORDER BY a.date DESC, a.timestamp DESC
                """,
                (student_id, student_id)
            ).fetchall()
            logs = [dict(r) for r in rows]
            
            present_days = sum(1 for l in logs if l["status"] == "Present")
            late_days = sum(1 for l in logs if l["status"] == "Late")
            total_attended = len(logs)
            rate = round((total_attended / total_active_days) * 100, 1) if total_active_days > 0 else 0.0

            # Today's check-in record
            today_log = next((l for l in logs if l["date"] == today), None)

            return {
                "logs": logs,
                "present_days": present_days,
                "late_days": late_days,
                "total_attended": total_attended,
                "total_active_days": total_active_days,
                "attendance_percentage": rate,
                "is_eligible": rate >= 75.0,
                "today_log": today_log
            }

    @staticmethod
    def get_today_metrics():
        """Returns Total Enrolled, Present Today, Late Today, Absent Today, Turnout Rate."""
        today = date.today().isoformat()
        with get_db() as conn:
            total_students_row = conn.execute("SELECT COUNT(*) AS cnt FROM students").fetchone()
            total_students = total_students_row["cnt"] if total_students_row else 0

            present_today_row = conn.execute(
                "SELECT COUNT(DISTINCT COALESCE(user_id, student_id)) AS cnt FROM attendance_logs WHERE date = ? AND status = 'Present'",
                (today,)
            ).fetchone()
            present_today = present_today_row["cnt"] if present_today_row else 0

            late_today_row = conn.execute(
                "SELECT COUNT(DISTINCT COALESCE(user_id, student_id)) AS cnt FROM attendance_logs WHERE date = ? AND status = 'Late'",
                (today,)
            ).fetchone()
            late_today = late_today_row["cnt"] if late_today_row else 0

            attended_today = present_today + late_today
            absent_today = max(0, total_students - attended_today)
            rate = round((attended_today / total_students * 100), 1) if total_students > 0 else 0.0

            return {
                "total_students": total_students,
                "present_today": present_today,
                "late_today": late_today,
                "attended_today": attended_today,
                "absent_today": absent_today,
                "attendance_rate": rate,
                "today_date": today
            }

    @staticmethod
    def get_absentees_for_date(date_str: str = None, course_id: int = None):
        """Returns list of enrolled students who are absent on the given date."""
        target_date = date_str or date.today().isoformat()
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT s.id, s.full_name, s.name, s.roll_number, s.email, s.device_token, s.mac_address,
                       1 AS course_id, 'GEN-100' AS course_code, 'General Campus Session' AS course_name
                FROM students s
                WHERE s.id NOT IN (
                    SELECT DISTINCT COALESCE(user_id, student_id) FROM attendance_logs WHERE date = ?
                )
                ORDER BY s.roll_number ASC
                """,
                (target_date,)
            ).fetchall()
            
            result = []
            for r in rows:
                d = dict(r)
                d["full_name"] = d.get("full_name") or d.get("name") or "Student"
                d["name"] = d["full_name"]
                result.append(d)
            return result


class Course:
    @staticmethod
    def create(course_code: str, course_name: str, instructor: str):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO courses (course_code, course_name, instructor)
                VALUES (?, ?, ?)
                """,
                (course_code.strip().upper(), course_name.strip(), instructor.strip())
            )
            course_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT OR IGNORE INTO course_enrollments (student_id, course_id)
                SELECT id, ? FROM students
                """,
                (course_id,)
            )
            return course_id

    @staticmethod
    def get_all():
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT c.*,
                       (SELECT COUNT(*) FROM course_enrollments WHERE course_id = c.id) AS enrolled_count,
                       (SELECT COUNT(*) FROM timetable_slots WHERE course_id = c.id) AS slots_count
                FROM courses c
                ORDER BY c.id ASC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_by_id(course_id: int):
        with get_db() as conn:
            row = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
            return dict(row) if row else None


class Timetable:
    @staticmethod
    def create_slot(course_id: int, day_of_week: str, start_time: str, end_time: str, room_number: str):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO timetable_slots (course_id, day_of_week, start_time, end_time, room_number)
                VALUES (?, ?, ?, ?, ?)
                """,
                (course_id, day_of_week.strip(), start_time.strip(), end_time.strip(), room_number.strip())
            )
            return cursor.lastrowid

    @staticmethod
    def get_all_slots():
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT t.*, c.course_code, c.course_name, c.instructor
                FROM timetable_slots t
                JOIN courses c ON t.course_id = c.id
                ORDER BY 
                    CASE t.day_of_week
                        WHEN 'Monday' THEN 1
                        WHEN 'Tuesday' THEN 2
                        WHEN 'Wednesday' THEN 3
                        WHEN 'Thursday' THEN 4
                        WHEN 'Friday' THEN 5
                        WHEN 'Saturday' THEN 6
                        WHEN 'Sunday' THEN 7
                        ELSE 8
                    END,
                    t.start_time ASC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def delete_slot(slot_id: int):
        with get_db() as conn:
            conn.execute("DELETE FROM timetable_slots WHERE id = ?", (slot_id,))

    @staticmethod
    def get_current_active_period(now_dt: datetime = None):
        now = now_dt or datetime.now()
        current_time_str = now.strftime("%H:%M")
        current_day_str = now.strftime("%A")

        with get_db() as conn:
            row = conn.execute(
                """
                SELECT t.*, c.course_code, c.course_name, c.instructor
                FROM timetable_slots t
                JOIN courses c ON t.course_id = c.id
                WHERE (t.day_of_week = ? OR t.day_of_week = 'Daily')
                  AND t.start_time <= ?
                  AND t.end_time >= ?
                ORDER BY t.start_time ASC
                LIMIT 1
                """,
                (current_day_str, current_time_str, current_time_str)
            ).fetchone()
            return dict(row) if row else None


class Admin:
    @staticmethod
    def authenticate(username: str, password: str):
        with get_db() as conn:
            row = conn.execute("SELECT * FROM admins WHERE username = ?", (username.strip(),)).fetchone()
            if row and check_password_hash(row["password_hash"], password):
                return dict(row)
            return None

    @staticmethod
    def get_by_username(username: str):
        with get_db() as conn:
            row = conn.execute("SELECT * FROM admins WHERE username = ?", (username.strip(),)).fetchone()
            return dict(row) if row else None


class Settings:
    @staticmethod
    def get(key: str, default=None):
        with get_db() as conn:
            row = conn.execute("SELECT value FROM system_config WHERE key = ?", (key,)).fetchone()
            if not row:
                row = conn.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    @staticmethod
    def set(key: str, value: str):
        with get_db() as conn:
            val_str = str(value).strip()
            conn.execute(
                "INSERT INTO system_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, val_str)
            )
            conn.execute(
                "INSERT INTO system_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, val_str)
            )

    @staticmethod
    def get_all():
        with get_db() as conn:
            rows = conn.execute("SELECT key, value FROM system_config").fetchall()
            d = {r["key"]: r["value"] for r in rows}
            # Fallback to system_settings if any missing
            extra_rows = conn.execute("SELECT key, value FROM system_settings").fetchall()
            for r in extra_rows:
                if r["key"] not in d:
                    d[r["key"]] = r["value"]
            return d

    @staticmethod
    def get_time_window_settings():
        return {
            "checkin_start_time": Settings.get("checkin_start_time", "08:00"),
            "checkin_cutoff_time": Settings.get("checkin_cutoff_time", "09:30"),
            "checkin_late_cutoff_time": Settings.get("checkin_late_cutoff_time", "10:30"),
            "authorized_subnet": Settings.get("authorized_subnet", "192.168.1.0/24"),
            "allow_localhost": Settings.get("allow_localhost", "1") == "1"
        }

    @staticmethod
    def update_time_window_settings(start_time: str, cutoff_time: str, late_cutoff_time: str, 
                                   authorized_subnet: str = None, allow_localhost: bool = None):
        if start_time:
            Settings.set("checkin_start_time", start_time.strip())
        if cutoff_time:
            Settings.set("checkin_cutoff_time", cutoff_time.strip())
        if late_cutoff_time:
            Settings.set("checkin_late_cutoff_time", late_cutoff_time.strip())
        if authorized_subnet:
            Settings.set("authorized_subnet", authorized_subnet.strip())
            Settings.set("subnet_range", authorized_subnet.strip())
        if allow_localhost is not None:
            Settings.set("allow_localhost", "1" if allow_localhost else "0")


class EmailAlert:
    @staticmethod
    def log(student_id: int, course_id: int, date_str: str, recipient_email: str, subject: str, status: str, details: str = ""):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO email_alerts_log (student_id, course_id, date, recipient_email, subject, status, sent_at, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (student_id, course_id, date_str, recipient_email, subject, status, now_str, details)
            )

    @staticmethod
    def get_recent(limit: int = 30):
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT e.*, COALESCE(s.full_name, s.name) AS student_name, s.roll_number,
                       COALESCE(c.course_code, 'General') AS course_code,
                       COALESCE(c.course_name, 'General Session') AS course_name
                FROM email_alerts_log e
                JOIN students s ON e.student_id = s.id
                LEFT JOIN courses c ON e.course_id = c.id
                ORDER BY e.id DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_today_count():
        today = date.today().isoformat()
        with get_db() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM email_alerts_log WHERE date = ?", (today,)).fetchone()
            return row["cnt"] if row else 0


class ScanEvent:
    @staticmethod
    def log(method: str, active_macs_found: int, students_marked: int, details: str = ""):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO scan_events (timestamp, method, active_macs_found, students_marked, details)
                VALUES (?, ?, ?, ?, ?)
                """,
                (now, method, active_macs_found, students_marked, details)
            )

    @staticmethod
    def get_recent(limit: int = 15):
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM scan_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
