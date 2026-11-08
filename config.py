import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).resolve().parent

# Application Configuration
SECRET_KEY = os.environ.get("SECRET_KEY", "wifi-attendance-secret-key-super-secure-2026")
DATABASE_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "attendance.db"))

# Scanner Engine Defaults (legacy ARP scanner, still usable alongside Device Token mode)
DEFAULT_SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL", 60))  # seconds
DEFAULT_SUBNET = os.environ.get("SUBNET_RANGE", "192.168.1.0/24")

# Authorized campus Wi-Fi subnets for device token check-in (comma-separated CIDR)
AUTHORIZED_SUBNETS = os.environ.get("AUTHORIZED_SUBNETS", "192.168.1.0/24, 192.168.29.0/24")

# Daily Attendance Time Windows (24-hour HH:MM format)
CHECKIN_START_TIME = os.environ.get("CHECKIN_START_TIME", "08:00")      # Window opens
CHECKIN_CUTOFF_TIME = os.environ.get("CHECKIN_CUTOFF_TIME", "09:30")    # On-time deadline (-> Present)
CHECKIN_LATE_CUTOFF = os.environ.get("CHECKIN_LATE_CUTOFF", "10:30")    # Late grace deadline (-> Late)

# Dev mode: allow localhost/127.0.0.1 for testing
ALLOW_LOCALHOST = os.environ.get("ALLOW_LOCALHOST", "1") == "1"

# Initial Admin Credentials (used during seed)
DEFAULT_ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
