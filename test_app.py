"""
Full Integration Test for Flask Web App and REST API Endpoints.
"""

import unittest
from app import app
from database import init_db
from models import Student, Attendance, Admin


class TestWebApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

    def setUp(self):
        self.client = app.test_client()

    def test_home_page(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        # Home is now the student check-in dashboard
        self.assertIn(b"Student Dashboard", res.data)
        self.assertIn(b"device_token", res.data)

    def test_registration_flow(self):
        # 1. GET registration form
        res = self.client.get("/register")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"One-Time Device Enrollment", res.data)

        # 2. POST registration with duplicate roll (device_token flow)
        res = self.client.post("/register", data={
            "full_name": "Duplicate Test",
            "roll_number": "CS-2026-001",
            "email": "dup@campus.edu",
            "device_token": "aa112233-4455-6677-8899-aabbccddeeff"
        }, follow_redirects=True)
        self.assertIn(b"already registered", res.data)

    def test_student_lookup_and_profile(self):
        # Lookup existing student from seed data
        res = self.client.get("/student/CS-2026-001")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Aarav Sharma", res.data)
        self.assertIn(b"CS-2026-001", res.data)
        self.assertIn(b"Attendance Rate", res.data)

    def test_admin_auth_and_dashboard(self):
        # Unauthenticated access to dashboard should redirect to /login
        res = self.client.get("/admin/dashboard")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login", res.headers["Location"])

        # Login with correct credentials
        res = self.client.post("/login", data={
            "username": "admin",
            "password": "admin123"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Attendance Command Dashboard", res.data)

        # Authenticated access to admin logs
        res_logs = self.client.get("/admin/logs")
        self.assertEqual(res_logs.status_code, 200)
        self.assertIn(b"Attendance Audit Logs", res_logs.data)

        # Authenticated export CSV
        res_csv = self.client.get("/admin/export-csv")
        self.assertEqual(res_csv.status_code, 200)
        self.assertEqual(res_csv.mimetype, "text/csv")
        self.assertIn(b"Roll Number", res_csv.data)

        # Authenticated scanner engine view
        res_scan = self.client.get("/admin/scanner")
        self.assertEqual(res_scan.status_code, 200)
        self.assertIn(b"Automated Wi-Fi Scanner Engine", res_scan.data)

        # Authenticated timetable view
        res_tt = self.client.get("/admin/timetable")
        self.assertEqual(res_tt.status_code, 200)
        self.assertIn(b"Timetable & Lecture Periods", res_tt.data)

        # Authenticated alerts view
        res_alerts = self.client.get("/admin/alerts")
        self.assertEqual(res_alerts.status_code, 200)
        self.assertIn(b"Absentee Email Notification Center", res_alerts.data)

    def test_timetable_and_periods(self):
        self.client.post("/login", data={"username": "admin", "password": "admin123"})
        
        # Test creating a new slot
        res = self.client.post("/admin/timetable/slots/add", data={
            "course_id": 1,
            "day_of_week": "Friday",
            "start_time": "14:00",
            "end_time": "15:30",
            "room_number": "Lab 101"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Timetable slot created", res.data)

    def test_absentee_email_alerts(self):
        self.client.post("/login", data={"username": "admin", "password": "admin123"})
        
        # API absentee dispatch
        res = self.client.post("/api/alerts/send", json={})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("Successfully processed", data["message"])

    def test_api_endpoints(self):
        # Public status API
        res = self.client.get("/api/scanner/status")
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()
        self.assertIn("status", json_data)
        self.assertIn("metrics", json_data)

        # Login as admin for protected APIs
        self.client.post("/login", data={"username": "admin", "password": "admin123"})

        # API simulation (MAC-based scanner still preserved)
        res_sim = self.client.post("/api/scanner/simulate", json={
            "mac_address": "A8:DA:0C:D5:E2:24"
        })
        self.assertEqual(res_sim.status_code, 200)
        sim_data = res_sim.get_json()
        self.assertTrue(sim_data["success"])
        self.assertGreaterEqual(sim_data["matched"], 1)

    def test_time_window_status_api(self):
        """New API: live check-in window status."""
        res = self.client.get("/api/time-window/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("time_window", data)
        self.assertIn("is_open", data["time_window"])
        self.assertIn("status", data["time_window"])

    def test_student_me_api_missing_token(self):
        """Missing device_token should return 400."""
        res = self.client.get("/api/student/me")
        self.assertEqual(res.status_code, 400)

    def test_checkin_missing_token(self):
        """Check-in without device_token should return 400."""
        res = self.client.post("/api/attendance/check-in", json={})
        self.assertEqual(res.status_code, 400)

    def test_checkin_invalid_token(self):
        """Check-in with unknown device_token should return 401."""
        res = self.client.post("/api/attendance/check-in", json={
            "device_token": "00000000-0000-0000-0000-000000000000"
        })
        self.assertEqual(res.status_code, 401)


if __name__ == "__main__":
    unittest.main()
