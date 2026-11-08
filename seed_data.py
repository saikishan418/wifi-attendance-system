"""
Seed script to populate realistic demo courses, timetable slots,
students, past attendance records, and verify admin credentials.
"""

from datetime import date, timedelta
from database import init_db
from models import Student, Attendance, Admin, Settings, Course, Timetable

DEMO_COURSES = [
    {"code": "CS101", "name": "Introduction to Computer Science", "instructor": "Dr. Alan Turing"},
    {"code": "CS204", "name": "Data Structures & Algorithms", "instructor": "Prof. Ada Lovelace"},
    {"code": "NET301", "name": "Computer Networks & Wireless Systems", "instructor": "Dr. Vint Cerf"},
    {"code": "MATH102", "name": "Discrete Mathematics", "instructor": "Dr. Claude Shannon"}
]

DEMO_TIMETABLE_SLOTS = [
    # Mon-Fri standard periods + Daily slots
    {"course_code": "CS101", "day": "Monday", "start": "09:00", "end": "10:30", "room": "Lecture Hall 101"},
    {"course_code": "CS204", "day": "Tuesday", "start": "10:45", "end": "12:15", "room": "Computing Lab 3"},
    {"course_code": "NET301", "day": "Wednesday", "start": "13:00", "end": "14:30", "room": "Networks Lab 2"},
    {"course_code": "MATH102", "day": "Thursday", "start": "09:00", "end": "10:30", "room": "Auditorium B"},
    {"course_code": "NET301", "day": "Friday", "start": "11:00", "end": "12:30", "room": "Networks Lab 2"},
    # Daily active demonstration slot (ensures active period detection is visible during testing)
    {"course_code": "CS204", "day": "Daily", "start": "00:00", "end": "23:59", "room": "Smart Hall 4A"}
]

DEMO_STUDENTS = [
    {
        "name": "Aarav Sharma",
        "roll_number": "CS-2026-001",
        "email": "aarav.sharma@campus.edu",
        "mac_address": "A8:DA:0C:D5:E2:24",  # Matches local LAN gateway / active sample
        "attendance_pattern": [True, True, True, True, True, True, True]  # 100%
    },
    {
        "name": "Sophia Rodriguez",
        "roll_number": "CS-2026-002",
        "email": "sophia.r@campus.edu",
        "mac_address": "3C:22:FB:41:89:12",
        "attendance_pattern": [True, True, False, True, True, True, False]  # ~71%
    },
    {
        "name": "Marcus Chen",
        "roll_number": "CS-2026-003",
        "email": "marcus.chen@campus.edu",
        "mac_address": "88:66:5A:11:34:B7",
        "attendance_pattern": [True, True, True, True, True, False, True]  # 85%
    },
    {
        "name": "Zara Patel",
        "roll_number": "CS-2026-004",
        "email": "zara.patel@campus.edu",
        "mac_address": "DC:A6:32:9F:7A:1C",
        "attendance_pattern": [True, False, False, True, False, False, False]  # 28%
    },
    {
        "name": "Liam O'Connor",
        "roll_number": "CS-2026-005",
        "email": "liam.oc@campus.edu",
        "mac_address": "50:EB:71:3C:99:4D",
        "attendance_pattern": [True, True, True, True, True, True, False]  # 85%
    },
    {
        "name": "Priya Nair",
        "roll_number": "CS-2026-006",
        "email": "priya.nair@campus.edu",
        "mac_address": "E4:5F:01:28:C0:D3",
        "attendance_pattern": [True, True, True, True, True, True, True]  # 100%
    }
]

def seed():
    print("[Seed] Initializing database...")
    init_db()

    print("[Seed] Seeding academic courses...")
    courses_map = {}
    for c in DEMO_COURSES:
        all_c = Course.get_all()
        existing = next((x for x in all_c if x["course_code"] == c["code"]), None)
        if not existing:
            c_id = Course.create(c["code"], c["name"], c["instructor"])
            courses_map[c["code"]] = c_id
            print(f"  + Course created: {c['code']} - {c['name']}")
        else:
            courses_map[c["code"]] = existing["id"]

    print("[Seed] Seeding timetable lecture slots...")
    current_slots = Timetable.get_all_slots()
    if not current_slots:
        for slot in DEMO_TIMETABLE_SLOTS:
            c_id = courses_map.get(slot["course_code"], 1)
            Timetable.create_slot(
                course_id=c_id,
                day_of_week=slot["day"],
                start_time=slot["start"],
                end_time=slot["end"],
                room_number=slot["room"]
            )
            print(f"  + Timetable slot: {slot['course_code']} ({slot['day']} {slot['start']}-{slot['end']} at {slot['room']})")

    today = date.today()
    # Past 6 school days + today = 7 days
    dates_list = [(today - timedelta(days=6 - i)).isoformat() for i in range(7)]

    print(f"\n[Seed] Seeding demo students and attendance logs ({dates_list[0]} to {dates_list[-1]})...")
    
    for st_data in DEMO_STUDENTS:
        existing = Student.get_by_roll(st_data["roll_number"])
        if existing:
            student_id = existing["id"]
            print(f"  [Exists] {st_data['name']} (ID: {student_id})")
        else:
            student_id = Student.create(
                full_name=st_data["name"],
                roll_number=st_data["roll_number"],
                email=st_data["email"],
                mac_address=st_data["mac_address"]
            )
            print(f"  + Student created: {st_data['name']} (ID: {student_id}) with MAC {st_data['mac_address']}")

        # Populate attendance for each day across courses
        for day_idx, day_str in enumerate(dates_list):
            if day_idx < len(st_data["attendance_pattern"]) and st_data["attendance_pattern"][day_idx]:
                time_str = f"09:{10 + day_idx * 5:02d}:15"
                method = "Wi-Fi ARP Scan" if day_idx % 2 == 0 else "System ARP Cache Scan"
                # Seed attendance for primary active course
                c_id = courses_map.get("CS204", 1)
                Attendance.mark_present(student_id, course_id=c_id, date_str=day_str, time_str=time_str, detection_method=method)

    print("\n[Seed] Demo data loaded successfully!")
    print("-------------------------------------------------------------")
    print("Academic Courses:")
    for c in Course.get_all():
        print(f"  - [{c['course_code']}] {c['course_name']} ({c['instructor']})")
    print("-------------------------------------------------------------")
    print("Admin Login: admin / admin123")
    print("-------------------------------------------------------------\n")

if __name__ == "__main__":
    seed()
