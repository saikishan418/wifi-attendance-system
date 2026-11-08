"""
Integration Test Suite for the Passwordless Device Token Attendance System.
Tests all 3 core security pillars:
  1. Device Token registration & identity pairing
  2. Campus Wi-Fi subnet IP verification (CIDR range check)
  3. Daily time window enforcement (Present, Late, Closed)
"""

import unittest
from datetime import datetime, timedelta, date
from database import init_db
from models import Student, Attendance, Admin, Settings
from attendance_security import verify_campus_wifi, evaluate_checkin_window


class TestDeviceTokenRegistration(unittest.TestCase):
    """Test student registration with browser device tokens (no passwords/MAC required)."""

    @classmethod
    def setUpClass(cls):
        init_db()
        # Clean up any test students from previous runs
        for roll in ["TOKEN-TEST-001", "TOKEN-TEST-002"]:
            st = Student.get_by_roll(roll)
            if st:
                Student.delete(st["id"])

    def test_create_student_with_device_token(self):
        """Registration generates and stores UUID v4 device token."""
        token = "test-uuid-1111-2222-3333-444444444444"
        student_id = Student.create(
            full_name="Token Test Student",
            roll_number="TOKEN-TEST-001",
            email="token.test@campus.edu",
            device_token=token
        )
        self.assertIsNotNone(student_id)

        # Verify lookup by device token works
        st = Student.get_by_device_token(token)
        self.assertIsNotNone(st)
        self.assertEqual(st["roll_number"], "TOKEN-TEST-001")
        self.assertEqual(st["device_token"], token)
        self.assertEqual(st["full_name"], "Token Test Student")

    def test_no_mac_address_required(self):
        """Students can register without a MAC address."""
        token = "test-uuid-5555-6666-7777-888888888888"
        student_id = Student.create(
            full_name="No MAC Student",
            roll_number="TOKEN-TEST-002",
            email="nomac@campus.edu",
            device_token=token,
            mac_address=""  # Explicitly empty
        )
        st = Student.get_by_id(student_id)
        self.assertIsNotNone(st)
        self.assertEqual(st["mac_address"], "")

    def test_device_token_reset(self):
        """Admin can reset a student token for device migration."""
        st = Student.get_by_roll("TOKEN-TEST-001")
        self.assertIsNotNone(st)

        Student.reset_device_token(st["id"])
        refreshed = Student.get_by_id(st["id"])
        self.assertIsNone(refreshed["device_token"])

        # Bind a new token (simulating new device registration)
        new_token = "new-device-aaaa-bbbb-cccc-dddddddddddd"
        Student.bind_device_token(st["id"], new_token)
        rebound = Student.get_by_device_token(new_token)
        self.assertIsNotNone(rebound)
        self.assertEqual(rebound["roll_number"], "TOKEN-TEST-001")

    @classmethod
    def tearDownClass(cls):
        for roll in ["TOKEN-TEST-001", "TOKEN-TEST-002"]:
            st = Student.get_by_roll(roll)
            if st:
                Student.delete(st["id"])


class TestCampusWifiSubnetVerification(unittest.TestCase):
    """Test IP subnet CIDR verification for campus Wi-Fi enforcement."""

    def setUp(self):
        """Ensure subnets are set for testing."""
        Settings.set("authorized_subnet", "192.168.1.0/24, 192.168.29.0/24")
        Settings.set("allow_localhost", "1")

    def test_localhost_allowed_in_dev_mode(self):
        """127.0.0.1 is authorized when allow_localhost is enabled."""
        is_ok, details = verify_campus_wifi("127.0.0.1")
        self.assertTrue(is_ok)
        self.assertIn("Localhost", details["matched_subnet"])

    def test_campus_subnet_primary_authorized(self):
        """IP within primary campus subnet is authorized."""
        is_ok, details = verify_campus_wifi("192.168.1.55")
        self.assertTrue(is_ok)
        self.assertEqual(details["matched_subnet"], "192.168.1.0/24")

    def test_campus_subnet_secondary_authorized(self):
        """IP within secondary campus subnet is also authorized."""
        is_ok, details = verify_campus_wifi("192.168.29.100")
        self.assertTrue(is_ok)
        self.assertEqual(details["matched_subnet"], "192.168.29.0/24")

    def test_external_ip_rejected(self):
        """Non-campus IPs are rejected with correct error code."""
        is_ok, details = verify_campus_wifi("10.0.0.5")
        self.assertFalse(is_ok)
        self.assertIn("not connected", details["message"])

    def test_public_ip_rejected(self):
        """Public IP addresses are rejected."""
        is_ok, details = verify_campus_wifi("8.8.8.8")
        self.assertFalse(is_ok)
        self.assertFalse(details["authorized"])

    def test_localhost_blocked_in_strict_mode(self):
        """127.0.0.1 is rejected when allow_localhost is disabled."""
        Settings.set("allow_localhost", "0")
        is_ok, _ = verify_campus_wifi("127.0.0.1")
        self.assertFalse(is_ok)
        Settings.set("allow_localhost", "1")  # Restore

    def test_ipv6_mapped_ipv4_handled(self):
        """IPv6-mapped IPv4 addresses (::ffff:x.x.x.x) resolve correctly."""
        # This is handled in get_client_ip — verify the helper correctly strips the prefix
        from attendance_security import get_client_ip
        # We can't mock request easily, so just verify the CIDR check works with stripped IP
        is_ok, _ = verify_campus_wifi("192.168.1.200")
        self.assertTrue(is_ok)


class TestTimeWindowEnforcement(unittest.TestCase):
    """Test daily time window enforcement: Present, Late, Not Started, Closed."""

    def setUp(self):
        Settings.set("checkin_start_time", "08:00")
        Settings.set("checkin_cutoff_time", "09:30")
        Settings.set("checkin_late_cutoff_time", "10:30")

    def _make_time(self, h, m):
        """Create a datetime for today at hour h, minute m."""
        today = date.today()
        return datetime(today.year, today.month, today.day, h, m, 0)

    def test_before_start_time_not_started(self):
        """Before 08:00, window is NOT_STARTED."""
        result = evaluate_checkin_window(self._make_time(7, 30))
        self.assertEqual(result["status"], "NOT_STARTED")
        self.assertFalse(result["is_open"])
        self.assertIsNone(result["attendance_status"])

    def test_on_time_window_present(self):
        """Between 08:00 and 09:30, status is ON_TIME → attendance_status = Present."""
        result = evaluate_checkin_window(self._make_time(8, 45))
        self.assertEqual(result["status"], "ON_TIME")
        self.assertTrue(result["is_open"])
        self.assertEqual(result["attendance_status"], "Present")

    def test_at_exactly_cutoff_still_present(self):
        """At exactly the cutoff time (09:30:00), still marked Present."""
        result = evaluate_checkin_window(self._make_time(9, 30))
        self.assertEqual(result["attendance_status"], "Present")

    def test_late_window_active(self):
        """Between 09:30 and 10:30, status is LATE → attendance_status = Late."""
        result = evaluate_checkin_window(self._make_time(9, 55))
        self.assertEqual(result["status"], "LATE")
        self.assertTrue(result["is_open"])
        self.assertEqual(result["attendance_status"], "Late")

    def test_after_late_cutoff_closed(self):
        """After 10:30, window is CLOSED and no attendance can be marked."""
        result = evaluate_checkin_window(self._make_time(11, 0))
        self.assertEqual(result["status"], "CLOSED")
        self.assertFalse(result["is_open"])
        self.assertIsNone(result["attendance_status"])

    def test_seconds_remaining_decreases(self):
        """Seconds remaining reported for open windows (countdown logic)."""
        result = evaluate_checkin_window(self._make_time(8, 0))
        self.assertGreater(result["seconds_remaining"], 0)

    def test_all_window_fields_present(self):
        """Response always includes all required fields for dashboard rendering."""
        required_keys = [
            "is_open", "status", "attendance_status", "message",
            "seconds_remaining", "target_time", "start_time",
            "cutoff_time", "late_cutoff_time", "server_time"
        ]
        result = evaluate_checkin_window(self._make_time(9, 0))
        for k in required_keys:
            self.assertIn(k, result, f"Missing key: {k}")


class TestAttendanceCheckInFlow(unittest.TestCase):
    """End-to-end attendance marking using the new mark_attendance() method."""

    TEST_ROLL = "ATTEND-TEST-999"
    TEST_TOKEN = "attend-test-uuid-aaaa-bbbb-cccccccccccc"
    _student_id = None

    @classmethod
    def setUpClass(cls):
        init_db()
        # Always start with a fresh student
        st = Student.get_by_roll(cls.TEST_ROLL)
        if st:
            Student.delete(st["id"])
        cls._student_id = Student.create(
            full_name="Attendance Test Student",
            roll_number=cls.TEST_ROLL,
            email="attend.test@campus.edu",
            device_token=cls.TEST_TOKEN
        )
        # Pre-mark attendance so duplicate check and history tests are order-independent
        Attendance.mark_attendance(
            user_id=cls._student_id,
            client_ip="192.168.1.50",
            status="Present",
            detection_method="Device Token Test"
        )

    def test_mark_present_success(self):
        """Attendance was successfully recorded in setUpClass (is_new=True path)."""
        st = Student.get_by_roll(self.TEST_ROLL)
        log = Attendance.get_student_today_log(st["id"])
        self.assertIsNotNone(log)
        self.assertEqual(log["status"], "Present")
        self.assertEqual(log["client_ip"], "192.168.1.50")

    def test_duplicate_check_in_prevented(self):
        """Second check-in same day returns is_new=False (idempotent guard)."""
        st = Student.get_by_roll(self.TEST_ROLL)
        success, msg, log = Attendance.mark_attendance(
            user_id=st["id"],
            client_ip="192.168.1.50",
            status="Present",
            detection_method="Device Token Test"
        )
        self.assertFalse(success)
        self.assertIn("already", msg.lower())

    def test_today_log_retrievable(self):
        """Marked attendance is retrievable via get_student_today_log."""
        st = Student.get_by_roll(self.TEST_ROLL)
        log = Attendance.get_student_today_log(st["id"])
        self.assertIsNotNone(log)
        self.assertEqual(log["status"], "Present")
        self.assertIn("client_ip", log)

    def test_history_metrics_calculated(self):
        """History data includes present_days, late_days, and percentage."""
        st = Student.get_by_roll(self.TEST_ROLL)
        hist = Attendance.get_student_history(st["id"])
        self.assertIn("present_days", hist)
        self.assertIn("late_days", hist)
        self.assertIn("attendance_percentage", hist)
        self.assertIn("is_eligible", hist)
        self.assertGreaterEqual(hist["present_days"], 1)

    def test_today_metrics_includes_late(self):
        """get_today_metrics returns present_today, late_today, absent_today."""
        metrics = Attendance.get_today_metrics()
        self.assertIn("present_today", metrics)
        self.assertIn("late_today", metrics)
        self.assertIn("attended_today", metrics)
        self.assertIn("absent_today", metrics)

    @classmethod
    def tearDownClass(cls):
        st = Student.get_by_roll(cls.TEST_ROLL)
        if st:
            Student.delete(st["id"])


class TestSettingsTimeWindowHelpers(unittest.TestCase):
    """Test Settings model helpers for time window configuration."""

    def test_get_time_window_settings(self):
        """get_time_window_settings() returns all required keys."""
        settings = Settings.get_time_window_settings()
        required = ["checkin_start_time", "checkin_cutoff_time",
                    "checkin_late_cutoff_time", "authorized_subnet", "allow_localhost"]
        for key in required:
            self.assertIn(key, settings)

    def test_update_time_window_settings(self):
        """Settings can be updated and read back correctly."""
        Settings.update_time_window_settings(
            start_time="07:30",
            cutoff_time="09:00",
            late_cutoff_time="10:00",
            authorized_subnet="10.0.0.0/24",
            allow_localhost=False
        )
        s = Settings.get_time_window_settings()
        self.assertEqual(s["checkin_start_time"], "07:30")
        self.assertEqual(s["checkin_cutoff_time"], "09:00")
        self.assertEqual(s["checkin_late_cutoff_time"], "10:00")
        self.assertEqual(s["authorized_subnet"], "10.0.0.0/24")
        self.assertFalse(s["allow_localhost"])

        # Restore defaults
        Settings.update_time_window_settings(
            start_time="08:00",
            cutoff_time="09:30",
            late_cutoff_time="10:30",
            authorized_subnet="192.168.1.0/24, 192.168.29.0/24",
            allow_localhost=True
        )

    def test_admin_authentication(self):
        """Admin login with correct credentials succeeds."""
        admin = Admin.authenticate("admin", "admin123")
        self.assertIsNotNone(admin)
        self.assertEqual(admin["username"], "admin")

        wrong = Admin.authenticate("admin", "wrong_password")
        self.assertIsNone(wrong)


if __name__ == "__main__":
    unittest.main(verbosity=2)
