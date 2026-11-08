# 📡 AttendIQ — Touchless Wi-Fi & Device-Token Campus Attendance System

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.14-blue?logo=python)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/Framework-Flask%203.1-black?logo=flask)](https://flask.palletsprojects.com/)
[![Database](https://img.shields.io/badge/Database-SQLite3-003B57?logo=sqlite)](https://www.sqlite.org/)
[![Frontend](https://img.shields.io/badge/UI-Google%20Workspace%20%7C%20Material%20Design-4285F4?logo=google)](https://tailwindcss.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An enterprise-grade, touchless automated attendance management system engineered for educational institutions. Designed to be **100% passwordless, OTP-free, and biometric-free**, AttendIQ leverages **cryptographic browser device tokens (UUID v4)**, **campus Wi-Fi CIDR subnet verification**, and **strict daily time window enforcement** wrapped in a modern **Google Workspace & Google Admin Console** design.

---

## 🌟 Core Architectural Pillars

### 1. Passwordless, OTP-Free & Biometric-Free Identity
- **No SMS/Email OTPs, Passwords, or Facial Recognition**: Completely bypasses fragile SMS gateway fees, password fatigue, and biometric privacy concerns.
- **Persistent Cryptographic Device Token**: During one-time registration, the browser invokes the Web Cryptography API (`crypto.randomUUID()`) to generate a unique UUID v4 saved permanently to `localStorage`.
- **Hardware-to-Identity Binding**: The token uniquely authenticates the student's personal phone or laptop against the database with zero user credentials entered daily.

### 2. Network Geofencing (Campus Wi-Fi Subnet Verification)
- **Layer-3 CIDR Subnet Enforcement**: Incoming client IP addresses are extracted (with `X-Forwarded-For` proxy awareness) and validated against institutional CIDR subnets (e.g., `192.168.1.0/24`, `192.168.29.0/24`) using Python's `ipaddress` module.
- **Proxy/Off-Campus Rejection**: Check-ins from cellular networks or off-campus internet connections are immediately rejected with `403 Forbidden`.
- **Configurable Dev Mode**: Includes a switchable localhost (`127.0.0.1`) testing flag for offline evaluation without requiring a live campus router.

### 3. Server-Enforced Daily Time Windows
- **State Machine Architecture**: Attendance status is computed in real time on the server according to dynamic deadlines:
  - `Before Start Time` (e.g., `< 08:00`): **Window Closed** (`NOT_STARTED`)
  - `On-Time Window` (e.g., `08:00 - 09:30`): Marked as **Present** (`ON_TIME`)
  - `Late Grace Window` (e.g., `09:30 - 10:30`): Marked as **Late** (`LATE`)
  - `After Late Cutoff` (e.g., `> 10:30`): **Window Closed** (`CLOSED`, rejected)
- **Idempotency Guard**: SQLite composite unique constraints prevent multiple check-ins on the same day.

### 4. Google Workspace / Google Admin Console UI
- **Design System**: Built with Google Sans, Roboto, and Material 3 design principles with authentic Google color hierarchy (`#1a73e8` Blue, `#34a853` Green, `#fbbc04` Amber, `#ea4335` Red).
- **Role-Separated Portals**:
  - **Student Portal (`/`)**: One-click check-in, live countdown timer to the deadline, network telemetry badge, and personal historical percentage with semester exam eligibility warning ($\ge 75\%$).
  - **Admin Command Dashboard (`/admin/dashboard`)**: KPI overview (Enrolled, Present Today, Late Today, Absent Today), live time window settings form, student directory with device token reset capability, audit logs, and RFC 4180 CSV export.

---

## 🏗 Architecture & Request Flow

```
                      STUDENT BROWSER
                            |
           [ Visits / on Campus Wi-Fi ]
                            |
       +--------------------+--------------------+
       |                                         |
[No Device Token]                       [Device Token Found]
       |                                         |
Redirects to /register                  Clicks "Mark Attendance"
Generates crypto.randomUUID()                    |
Pairs Roll + Name + Token                        v
       |                               POST /api/attendance/check-in
       +-----------------------------------------+
                                                 |
                                                 v
                                        FLASK SECURITY ENGINE
                                                 |
                    +----------------------------+----------------------------+
                    |                            |                            |
            1. Token Verification        2. Subnet Check             3. Time Window Check
            Matches active student?      Client IP in CIDR?          Server time in window?
            [No -> 401 Unauthorized]    [No -> 403 Forbidden]       [Before/After -> 400]
                    |                            |                            |
                    +----------------------------+----------------------------+
                                                 | (All Pass)
                                                 v
                                       SQLITE DATABASE LAYER
                                 INSERT INTO attendance_logs
                            (status = 'Present' or 'Late', client_ip)
                                                 |
                                                 v
                                   200 OK — Attendance Logged!
```

---

## 🛠 Tech Stack

| Domain | Technology | Details |
|:---|:---|:---|
| **Backend** | Python 3.10+ / Flask 3.1 | Modular route handlers, context processors, session auth |
| **Database** | SQLite 3 | Zero-config SQL engine, composite unique index deduplication |
| **Security & Network** | Python `ipaddress` / Web Crypto API | Subnet CIDR match, UUID v4 token binding, X-Forwarded-For stripping |
| **Frontend** | Tailwind CSS + Google Material 3 | Responsive design, Google Sans/Roboto, async Fetch API |
| **Testing** | Python `unittest` | 41 unit & integration tests covering 100% of workflows |
| **Legacy Telemetry** | Scapy / ARP Cache Sweeper | Optional Layer-2 passive scanning module |

---

## 🚀 Quick Start Guide

### 1. Clone & Set Up Virtual Environment
```bash
git clone https://github.com/YOUR_USERNAME/wifi-attendance-system.git
cd wifi-attendance-system

python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Initialize & Seed Sample Data
```bash
python seed_data.py
```
*Creates courses, timetable schedules, and 7 sample students with pre-configured attendance histories.*

### 4. Run the Application
```bash
python app.py
```
Open your browser:
- **Student Check-In Portal**: `http://localhost:5000/`
- **Admin Command Console**: `http://localhost:5000/admin/dashboard`
  - *Default Admin Credentials*: `admin` / `admin123`

---

## 🧪 Automated Test Suite

Run all 41 test cases:
```bash
python -m unittest discover -p "test_*.py" -v
```

| Suite | Tests | Scope |
|:---|:---:|:---|
| `test_device_token.py` | 25 | Subnet ranges, time windows, UUID token pairing, reset, check-in flow |
| `test_app.py` | 11 | Flask routes, APIs (`/api/attendance/check-in`, `/api/time-window/status`), admin auth |
| `test_system.py` | 5 | MAC normalization, network utils, simulation backward compatibility |
| **Total** | **41** | **100% Pass** |

---

## 📄 License
This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
