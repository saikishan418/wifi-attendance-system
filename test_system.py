"""
Comprehensive Unit & Integration Test Suite for Wi-Fi Attendance System.
"""

import unittest
from datetime import date
from database import init_db, normalize_mac, is_valid_mac
from models import Student, Attendance, Admin, Settings
from scanner import WifiScannerService, NetworkUtils

class TestWifiAttendanceSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_mac_normalization(self):
        """Test MAC address normalization across varying input styles."""
        self.assertEqual(normalize_mac("aa:bb:cc:dd:ee:ff"), "AA:BB:CC:DD:EE:FF")
        self.assertEqual(normalize_mac("AA-BB-CC-DD-EE-FF"), "AA:BB:CC:DD:EE:FF")
        self.assertEqual(normalize_mac("aabb.ccdd.eeff"), "AA:BB:CC:DD:EE:FF")
        self.assertEqual(normalize_mac("112233445566"), "11:22:33:44:55:66")
        
        # Invalid MAC formats
        self.assertFalse(is_valid_mac("invalid_mac"))
        self.assertFalse(is_valid_mac("11:22:33:44:55")) # too short
        self.assertFalse(is_valid_mac("11:22:33:44:55:66:77")) # too long

    def test_student_and_attendance_flow(self):
        """Test student creation and idempotent attendance marking."""
        roll = "TEST-ROLL-999"
        mac = "fa:b1:c2:d3:e4:f5"
        
        # Clean up if leftover from previous test
        existing = Student.get_by_roll(roll)
        if existing:
            Student.delete(existing["id"])

        student_id = Student.create(full_name="Test Student", roll_number=roll, email="test@test.com", mac_address=mac)
        self.assertIsNotNone(student_id)

        # Verify fetched student
        st = Student.get_by_id(student_id)
        self.assertEqual(st["roll_number"], roll)
        self.assertEqual(st["mac_address"], "FA:B1:C2:D3:E4:F5")

        # Mark attendance first time today -> should return True
        today = date.today().isoformat()
        marked = Attendance.mark_present(student_id, date_str=today, detection_method="Unit Test Scan")
        self.assertTrue(marked)

        # Mark attendance second time today -> must return False (idempotent, prevents duplicates)
        marked_duplicate = Attendance.mark_present(student_id, date_str=today, detection_method="Unit Test Scan")
        self.assertFalse(marked_duplicate)

        # Check history
        history = Attendance.get_student_history(student_id)
        self.assertGreaterEqual(history["present_days"], 1)

        # Cleanup
        Student.delete(student_id)

    def test_admin_authentication(self):
        """Test admin authentication with valid and invalid passwords."""
        admin = Admin.authenticate("admin", "admin123")
        self.assertIsNotNone(admin)
        self.assertEqual(admin["username"], "admin")

        wrong = Admin.authenticate("admin", "wrong_pass")
        self.assertIsNone(wrong)

    def test_scanner_simulation(self):
        """Test virtual device packet injection in WifiScannerService."""
        scanner = WifiScannerService()
        
        # Use an existing student from seed data (Aarav Sharma)
        aarav = Student.get_by_roll("CS-2026-001")
        self.assertIsNotNone(aarav)

        res = scanner.simulate_device(aarav["mac_address"])
        self.assertIn("matched_students", res)
        matched_rolls = [s["roll_number"] for s in res["matched_students"]]
        self.assertIn("CS-2026-001", matched_rolls)

    def test_network_utils(self):
        """Verify network utilities do not crash and return valid formats."""
        local_ip = NetworkUtils.get_local_ip()
        self.assertTrue(len(local_ip.split(".")) == 4)
        subnet = NetworkUtils.auto_detect_subnet()
        self.assertTrue(subnet.endswith("/24"))

if __name__ == "__main__":
    unittest.main()
