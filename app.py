import os
import csv
import io
import uuid
from functools import wraps
from datetime import datetime, date
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, jsonify, Response, abort
)

import config
from database import init_db, is_valid_mac, normalize_mac
from models import Student, Attendance, Admin, Settings, ScanEvent, Course, Timetable, EmailAlert
from scanner import scanner_service, NetworkUtils
from email_service import EmailNotificationService
from attendance_security import (
    get_client_ip,
    verify_campus_wifi,
    evaluate_checkin_window,
    require_campus_wifi
)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# Ensure database is initialized
init_db()

# Auto-start scanner background service if enabled in system settings
if Settings.get("scanner_active", "0") == "1":
    scanner_service.start()


# =============================================================================
# AUTHENTICATION DECORATOR & CONTEXT PROCESSORS
# =============================================================================
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "admin_id" not in session:
            flash("Please sign in to access the administrator panel.", "warning")
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_global_data():
    """Injects live system context into all templates."""
    client_ip = get_client_ip()
    is_wifi, wifi_info = verify_campus_wifi(client_ip)
    time_window = evaluate_checkin_window()
    time_settings = Settings.get_time_window_settings()

    return {
        "current_admin": session.get("admin_username"),
        "scanner_is_running": scanner_service.is_running(),
        "today_date": date.today().isoformat(),
        "active_period": Timetable.get_current_active_period(),
        "client_ip": client_ip,
        "is_campus_wifi": is_wifi,
        "wifi_info": wifi_info,
        "time_window": time_window,
        "time_settings": time_settings
    }


# =============================================================================
# STUDENT PORTAL & DAILY CHECK-IN
# =============================================================================
@app.route("/")
def index():
    """
    Daily Check-In Dashboard.
    On client load, JavaScript inspects localStorage for 'device_token'.
    If missing, client redirects to /register.
    If present, displays live deadline countdown, 'Mark Attendance' button,
    network status, and personal attendance history.
    """
    # Administrators visiting root are sent directly to the Admin Command Dashboard
    if "admin_id" in session and request.args.get("view") != "student":
        return redirect(url_for("admin_dashboard"))

    metrics = Attendance.get_today_metrics()
    time_window = evaluate_checkin_window()
    time_settings = Settings.get_time_window_settings()
    client_ip = get_client_ip()
    is_wifi, wifi_info = verify_campus_wifi(client_ip)

    return render_template(
        "index.html",
        metrics=metrics,
        time_window=time_window,
        time_settings=time_settings,
        client_ip=client_ip,
        is_campus_wifi=is_wifi,
        wifi_info=wifi_info
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    """
    One-Time Student Device Pairing Portal.
    No passwords, SMS/Email OTPs, or MAC addresses needed.
    JavaScript generates a secure UUID (v4) stored permanently in localStorage
    as 'device_token' and submits it along with student details.
    """
    if request.method == "POST":
        full_name = request.form.get("name", "").strip() or request.form.get("full_name", "").strip()
        roll_number = request.form.get("roll_number", "").strip().upper()
        email = request.form.get("email", "").strip().lower()
        device_token = request.form.get("device_token", "").strip()

        # Generate a fallback server-side token if browser failed to pass one
        if not device_token:
            device_token = str(uuid.uuid4())

        errors = []
        if not full_name or len(full_name) < 2:
            errors.append("Student full name is required (at least 2 characters).")
        if not roll_number:
            errors.append("Roll number / Student ID is required.")
        if not email or "@" not in email:
            errors.append("A valid campus email is required.")

        # Check if this device token is already used by another student
        existing_token_owner = Student.get_by_device_token(device_token)
        if existing_token_owner and existing_token_owner["roll_number"] != roll_number:
            errors.append(
                f"This device is already linked to student {existing_token_owner['full_name']} "
                f"({existing_token_owner['roll_number']}). Each device can only be paired to one student."
            )

        # Check roll number uniqueness or device reset re-pairing
        existing_roll = Student.get_by_roll(roll_number)
        if existing_roll:
            # If the student's token was cleared by an administrator (or matches current)
            if not existing_roll.get("device_token") or existing_roll["device_token"] == device_token:
                # Re-bind token to this student
                try:
                    Student.bind_device_token(existing_roll["id"], device_token, full_name, email)
                    flash(f"Device successfully linked for {full_name} ({roll_number})! Your attendance records have been connected.", "success")
                    return redirect(url_for("index"))
                except Exception as e:
                    errors.append(f"Could not link device: {str(e)}")
            else:
                errors.append(
                    f"Roll Number '{roll_number}' is already registered to another device. "
                    "If you switched phones or laptops, please ask an administrator to reset your device token."
                )

        if errors:
            for err in errors:
                flash(err, "error")
            return render_template(
                "register.html",
                name=full_name,
                full_name=full_name,
                roll_number=roll_number,
                email=email,
                device_token=device_token
            )

        # Create new student record
        try:
            Student.create(
                full_name=full_name,
                roll_number=roll_number,
                email=email,
                device_token=device_token
            )
            flash(f"Registration successful! Welcome {full_name}. Your device has been securely paired.", "success")
            return redirect(url_for("index"))
        except Exception as e:
            flash(f"Registration failed due to a system error: {str(e)}", "error")
            return render_template(
                "register.html",
                name=full_name,
                full_name=full_name,
                roll_number=roll_number,
                email=email,
                device_token=device_token
            )

    return render_template("register.html")


@app.route("/student/lookup", methods=["GET", "POST"])
def student_lookup():
    """Portal for students to search and view their attendance history."""
    if request.method == "POST":
        roll_number = request.form.get("roll_number", "").strip().upper()
        if not roll_number:
            flash("Please enter a student roll number.", "warning")
            return redirect(url_for("student_lookup"))
        return redirect(url_for("student_profile", roll_number=roll_number))
    return render_template("student_lookup.html")


@app.route("/student/<roll_number>")
def student_profile(roll_number):
    """Personal attendance report view for a registered student."""
    student = Student.get_by_roll(roll_number)
    if not student:
        flash(f"No student found with Roll Number '{roll_number}'.", "error")
        return redirect(url_for("student_lookup"))

    history_data = Attendance.get_student_history(student["id"])
    today_str = date.today().isoformat()
    is_present_today = any(l["date"] == today_str for l in history_data["logs"])

    return render_template(
        "student_profile.html",
        student=student,
        history=history_data,
        is_present_today=is_present_today
    )


# =============================================================================
# ASYNCHRONOUS REST API: STUDENT STATUS & ATTENDANCE CHECK-IN
# =============================================================================
@app.route("/api/student/me")
def api_student_me():
    """
    Returns profile, live network status, time window status, and attendance history
    for the student matching the provided browser device_token.
    """
    device_token = request.args.get("device_token", "").strip() or request.headers.get("X-Device-Token", "").strip()
    if not device_token:
        return jsonify({"success": False, "error_code": "MISSING_TOKEN", "message": "No device token provided."}), 400

    student = Student.get_by_device_token(device_token)
    if not student:
        return jsonify({
            "success": False,
            "error_code": "TOKEN_NOT_FOUND",
            "message": "Device token not found in the campus registry. Please register your device."
        }), 404

    client_ip = get_client_ip()
    is_wifi, wifi_info = verify_campus_wifi(client_ip)
    time_window = evaluate_checkin_window()
    history = Attendance.get_student_history(student["id"])
    today_log = Attendance.get_student_today_log(student["id"])

    return jsonify({
        "success": True,
        "student": {
            "id": student["id"],
            "full_name": student["full_name"],
            "name": student["full_name"],
            "roll_number": student["roll_number"],
            "email": student["email"],
            "registered_at": student.get("registered_at") or student.get("registered_date")
        },
        "network": {
            "client_ip": client_ip,
            "is_campus_wifi": is_wifi,
            "message": wifi_info.get("message")
        },
        "time_window": time_window,
        "today_attendance": today_log,
        "history": history
    })


@app.route("/api/attendance/check-in", methods=["POST"])
def api_attendance_check_in():
    """
    Mark Daily Attendance Endpoint.
    Enforces the 3 Core Architectural Rules:
    1. Validates Device Token against student database.
    2. Validates Client IP matches authorized campus Wi-Fi subnet range.
    3. Validates current server time against daily cutoff windows (Present vs Late vs Closed).
    """
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    device_token = data.get("device_token", "").strip() or request.headers.get("X-Device-Token", "").strip()

    # Step 1: Validate Device Token
    if not device_token:
        return jsonify({
            "success": False,
            "error_code": "MISSING_DEVICE_TOKEN",
            "message": "Missing device token. Please ensure your device is registered."
        }), 400

    student = Student.get_by_device_token(device_token)
    if not student:
        return jsonify({
            "success": False,
            "error_code": "INVALID_DEVICE_TOKEN",
            "message": "This device is not registered. Please register your device on the portal."
        }), 401

    # Step 2: Validate Campus Wi-Fi Network Subnet
    client_ip = get_client_ip()
    is_wifi_ok, wifi_details = verify_campus_wifi(client_ip)
    if not is_wifi_ok:
        return jsonify({
            "success": False,
            "error_code": "NETWORK_UNAUTHORIZED",
            "client_ip": client_ip,
            "message": wifi_details.get("message", "You must be connected to authorized campus Wi-Fi to check in.")
        }), 403

    # Step 3: Validate Daily Time Window Enforcement
    time_window = evaluate_checkin_window()
    if not time_window["is_open"]:
        return jsonify({
            "success": False,
            "error_code": "TIME_WINDOW_CLOSED",
            "server_time": time_window["server_time"],
            "message": time_window["message"]
        }), 400

    # Step 4: Check For Duplicate Attendance Today
    existing_log = Attendance.get_student_today_log(student["id"])
    if existing_log:
        return jsonify({
            "success": False,
            "error_code": "ALREADY_CHECKED_IN",
            "message": f"Attendance already recorded today as {existing_log['status']} at {existing_log['timestamp']}.",
            "log": existing_log
        }), 409

    # Step 5: Log Attendance Record
    status = time_window["attendance_status"]  # "Present" or "Late"
    success, msg, log_entry = Attendance.mark_attendance(
        user_id=student["id"],
        client_ip=client_ip,
        status=status,
        detection_method="Device Token Wi-Fi"
    )

    if not success:
        return jsonify({
            "success": False,
            "error_code": "RECORDING_FAILED",
            "message": msg
        }), 500

    # Retrieve updated history metrics
    updated_history = Attendance.get_student_history(student["id"])

    return jsonify({
        "success": True,
        "status": status,
        "message": f"Attendance successfully marked as {status}!",
        "log": log_entry,
        "client_ip": client_ip,
        "history": updated_history
    }), 200


@app.route("/api/time-window/status")
def api_time_window_status():
    """Returns real-time server time and attendance deadline information."""
    return jsonify({
        "time_window": evaluate_checkin_window(),
        "settings": Settings.get_time_window_settings()
    })


# =============================================================================
# ADMIN AUTHENTICATION
# =============================================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    """Admin login page."""
    if "admin_id" in session:
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        admin = Admin.authenticate(username, password)
        if admin:
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            flash(f"Welcome back, Administrator {admin['username']}!", "success")
            next_url = request.args.get("next")
            return redirect(next_url or url_for("admin_dashboard"))
        else:
            flash("Invalid administrator username or password.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    """Logs out admin user."""
    session.clear()
    flash("You have been signed out successfully.", "info")
    return redirect(url_for("login"))


# =============================================================================
# ADMIN DASHBOARD & ATTENDANCE MANAGEMENT
# =============================================================================
@app.route("/admin")
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    """
    Primary operational command center for administrators.
    Displays:
    - Overview metrics: Total Enrolled, Present Today, Late, Absent.
    - System Settings: Edit daily attendance time windows and cutoff deadlines.
    - Today's verified check-ins and quick actions.
    """
    metrics = Attendance.get_today_metrics()
    today_logs = Attendance.get_today_logs()
    scanner_status = scanner_service.get_status()
    time_window = evaluate_checkin_window()
    time_settings = Settings.get_time_window_settings()

    return render_template(
        "admin/dashboard.html",
        metrics=metrics,
        today_logs=today_logs,
        scanner_status=scanner_status,
        time_window=time_window,
        time_settings=time_settings
    )


@app.route("/admin/settings/time-window", methods=["POST"])
@admin_required
def admin_update_time_window():
    """Updates daily check-in opening, on-time cutoff, late cutoff, and Wi-Fi subnets."""
    start_time = request.form.get("checkin_start_time", "").strip()
    cutoff_time = request.form.get("checkin_cutoff_time", "").strip()
    late_cutoff_time = request.form.get("checkin_late_cutoff_time", "").strip()
    authorized_subnet = request.form.get("authorized_subnet", "").strip()
    allow_localhost = request.form.get("allow_localhost") == "1"

    if not (start_time and cutoff_time and late_cutoff_time):
        flash("Start time, cutoff deadline, and late cutoff deadline are required.", "error")
    else:
        Settings.update_time_window_settings(
            start_time=start_time,
            cutoff_time=cutoff_time,
            late_cutoff_time=late_cutoff_time,
            authorized_subnet=authorized_subnet if authorized_subnet else None,
            allow_localhost=allow_localhost
        )
        flash("Daily attendance time windows and Wi-Fi settings saved successfully.", "success")

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/logs")
@admin_required
def admin_logs():
    """Comprehensive, filterable attendance records."""
    date_filter = request.args.get("date", "").strip()
    roll_filter = request.args.get("roll_number", "").strip()
    status_filter = request.args.get("status", "").strip()

    logs = Attendance.get_logs(
        date_filter=date_filter if date_filter else None,
        roll_number=roll_filter if roll_filter else None,
        status_filter=status_filter if status_filter else None,
        limit=500
    )

    return render_template(
        "admin/logs.html",
        logs=logs,
        date_filter=date_filter,
        roll_filter=roll_filter,
        status_filter=status_filter
    )


@app.route("/admin/export-csv")
@admin_required
def export_csv():
    """Exports attendance logs as a downloadable CSV file."""
    date_filter = request.args.get("date", "").strip()
    roll_filter = request.args.get("roll_number", "").strip()
    status_filter = request.args.get("status", "").strip()

    logs = Attendance.get_logs(
        date_filter=date_filter if date_filter else None,
        roll_number=roll_filter if roll_filter else None,
        status_filter=status_filter if status_filter else None,
        limit=5000
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Date", "Timestamp", "Roll Number", "Student Name",
        "Email", "Status", "Client IP", "Detection Method"
    ])

    for log in logs:
        writer.writerow([
            log["id"],
            log["date"],
            log["timestamp"],
            log["roll_number"],
            log.get("full_name") or log.get("name"),
            log["email"],
            log["status"],
            log.get("client_ip", "127.0.0.1"),
            log.get("detection_method", "Device Token Wi-Fi")
        ])

    filename = f"attendance_report_{date.today().isoformat()}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.route("/admin/students", methods=["GET", "POST"])
@admin_required
def admin_students():
    """Student management: directory list, search, add, edit, or reset tokens."""
    if request.method == "POST":
        action = request.form.get("action", "add")

        if action == "add":
            name = request.form.get("name", "").strip() or request.form.get("full_name", "").strip()
            roll_number = request.form.get("roll_number", "").strip().upper()
            email = request.form.get("email", "").strip().lower()
            mac_address = request.form.get("mac_address", "").strip()

            if not (name and roll_number and email):
                flash("Name, Roll Number, and Email are required.", "error")
            elif Student.get_by_roll(roll_number):
                flash(f"Roll number {roll_number} already exists.", "error")
            else:
                Student.create(full_name=name, roll_number=roll_number, email=email, mac_address=mac_address)
                flash(f"Student {name} added successfully. Device token will be paired upon first check-in or registration.", "success")
            return redirect(url_for("admin_students"))

    search_query = request.args.get("q", "").strip()
    students = Student.get_all(search_query=search_query if search_query else None)
    return render_template("admin/students.html", students=students, search_query=search_query)


@app.route("/admin/students/<int:student_id>/reset-token", methods=["POST"])
@admin_required
def reset_student_token(student_id):
    """
    Resets a student's browser device token.
    Allows the student to register their new device at /register without losing attendance history.
    """
    student = Student.get_by_id(student_id)
    if not student:
        flash("Student not found.", "error")
        return redirect(url_for("admin_students"))

    Student.reset_device_token(student_id)
    flash(
        f"Device token for student '{student['full_name']}' ({student['roll_number']}) "
        "has been reset. The student can now register their new device.",
        "success"
    )
    return redirect(url_for("admin_students"))


@app.route("/admin/students/<int:student_id>/edit", methods=["POST"])
@admin_required
def edit_student(student_id):
    """Edits student profile details."""
    student = Student.get_by_id(student_id)
    if not student:
        flash("Student not found.", "error")
        return redirect(url_for("admin_students"))

    name = request.form.get("name", "").strip() or request.form.get("full_name", "").strip()
    roll_number = request.form.get("roll_number", "").strip().upper()
    email = request.form.get("email", "").strip().lower()
    mac_address = request.form.get("mac_address", "").strip()
    reset_token = "reset_token" in request.form

    existing_roll = Student.get_by_roll(roll_number)
    if existing_roll and existing_roll["id"] != student_id:
        flash(f"Roll number {roll_number} is already in use by another student.", "error")
        return redirect(url_for("admin_students"))

    Student.update(student_id, name, roll_number, email, mac_address)

    if reset_token:
        Student.reset_device_token(student_id)
        flash(f"Student {name} updated and device token reset successfully.", "success")
    else:
        flash(f"Student {name} updated successfully.", "success")

    return redirect(url_for("admin_students"))


@app.route("/admin/students/<int:student_id>/delete", methods=["POST"])
@admin_required
def delete_student(student_id):
    """Deletes a student and cascades to their attendance records."""
    student = Student.get_by_id(student_id)
    if student:
        Student.delete(student_id)
        flash(f"Student '{student['full_name']}' ({student['roll_number']}) deleted.", "info")
    return redirect(url_for("admin_students"))


# =============================================================================
# TIMETABLE & CLASS PERIOD SCHEDULES
# =============================================================================
@app.route("/admin/timetable")
@admin_required
def admin_timetable():
    """Timetable & period scheduling command center."""
    courses = Course.get_all()
    slots = Timetable.get_all_slots()
    active_period = Timetable.get_current_active_period()
    return render_template(
        "admin/timetable.html",
        courses=courses,
        slots=slots,
        active_period=active_period
    )


@app.route("/admin/timetable/slots/add", methods=["POST"])
@admin_required
def add_timetable_slot():
    """Adds a new lecture slot to the timetable."""
    course_id = request.form.get("course_id", type=int)
    day = request.form.get("day_of_week", "").strip()
    start_time = request.form.get("start_time", "").strip()
    end_time = request.form.get("end_time", "").strip()
    room_number = request.form.get("room_number", "").strip()

    if not (course_id and day and start_time and end_time and room_number):
        flash("All fields are required to schedule a class period.", "error")
    else:
        Timetable.create_slot(course_id, day, start_time, end_time, room_number)
        flash(f"Timetable slot created ({day} {start_time}-{end_time} in {room_number}).", "success")

    return redirect(url_for("admin_timetable"))


@app.route("/admin/timetable/slots/<int:slot_id>/delete", methods=["POST"])
@admin_required
def delete_timetable_slot(slot_id):
    """Deletes a lecture slot."""
    Timetable.delete_slot(slot_id)
    flash("Timetable slot deleted.", "info")
    return redirect(url_for("admin_timetable"))


@app.route("/admin/timetable/courses/add", methods=["POST"])
@admin_required
def add_course():
    """Adds a new academic course."""
    code = request.form.get("course_code", "").strip().upper()
    name = request.form.get("course_name", "").strip()
    instructor = request.form.get("instructor", "").strip()

    if not (code and name and instructor):
        flash("Course code, name, and instructor are required.", "error")
    else:
        Course.create(code, name, instructor)
        flash(f"Course {code} ({name}) created successfully.", "success")

    return redirect(url_for("admin_timetable"))


# =============================================================================
# SCANNER ENGINE & SIMULATION (LEGACY SUPPORT)
# =============================================================================
@app.route("/admin/scanner", methods=["GET", "POST"])
@admin_required
def admin_scanner():
    """Scanner configuration, live log viewer, and manual controls."""
    if request.method == "POST":
        subnet = request.form.get("subnet_range", "").strip()
        interval = request.form.get("scan_interval", "60").strip()
        engine = request.form.get("preferred_engine", "auto").strip()

        if subnet:
            Settings.set("subnet_range", subnet)
            Settings.set("authorized_subnet", subnet)
        if interval.isdigit() and int(interval) >= 10:
            Settings.set("scan_interval", interval)
        if engine in ("auto", "scapy", "arp_table"):
            Settings.set("preferred_engine", engine)

        flash("Scanner configuration updated successfully.", "success")
        return redirect(url_for("admin_scanner"))

    status = scanner_service.get_status()
    recent_events = ScanEvent.get_recent(limit=25)
    recent_logs = scanner_service.get_recent_logs()
    auto_detected_subnet = NetworkUtils.auto_detect_subnet()
    all_students = Student.get_all()

    return render_template(
        "admin/scanner.html",
        status=status,
        recent_events=recent_events,
        recent_logs=recent_logs,
        auto_detected_subnet=auto_detected_subnet,
        all_students=all_students
    )


# =============================================================================
# ABSENTEE EMAIL NOTIFICATIONS
# =============================================================================
@app.route("/admin/alerts", methods=["GET", "POST"])
@admin_required
def admin_alerts():
    """Absentee email notification control center and dispatch history."""
    if request.method == "POST":
        Settings.set("smtp_host", request.form.get("smtp_host", "smtp.gmail.com").strip())
        Settings.set("smtp_port", request.form.get("smtp_port", "587").strip())
        Settings.set("smtp_user", request.form.get("smtp_user", "").strip())
        if request.form.get("smtp_password"):
            Settings.set("smtp_password", request.form.get("smtp_password", "").strip())
        Settings.set("smtp_from", request.form.get("smtp_from", "attendance@campus.edu").strip())
        Settings.set("smtp_mock_mode", "1" if request.form.get("smtp_mock_mode") else "0")

        flash("SMTP notification settings saved successfully.", "success")
        return redirect(url_for("admin_alerts"))

    today_absentees = Attendance.get_absentees_for_date()
    recent_alerts = EmailAlert.get_recent(limit=35)
    smtp_settings = {
        "host": Settings.get("smtp_host", "smtp.gmail.com"),
        "port": Settings.get("smtp_port", "587"),
        "user": Settings.get("smtp_user", ""),
        "from": Settings.get("smtp_from", "attendance@campus.edu"),
        "mock_mode": Settings.get("smtp_mock_mode", "1") == "1"
    }

    return render_template(
        "admin/alerts.html",
        today_absentees=today_absentees,
        recent_alerts=recent_alerts,
        smtp_settings=smtp_settings
    )


@app.route("/admin/alerts/send", methods=["POST"])
@admin_required
def send_absentee_alerts():
    """Triggers absentee email dispatches for today."""
    course_id = request.form.get("course_id", type=int)
    result = EmailNotificationService.dispatch_today_absentee_alerts(course_id=course_id)
    mode_text = "Simulated (Mock Mode)" if result["is_mock_mode"] else "Sent via SMTP"
    flash(
        f"Absentee Alerts Dispatched: {result['sent_count']} notices {mode_text}. "
        f"({result['failed_count']} failed).",
        "success" if result["sent_count"] > 0 else "info"
    )
    return redirect(url_for("admin_alerts"))


@app.route("/api/alerts/send", methods=["POST"])
@admin_required
def api_send_alerts():
    data = request.get_json() or {}
    course_id = data.get("course_id")
    result = EmailNotificationService.dispatch_today_absentee_alerts(course_id=course_id)
    return jsonify({
        "success": True,
        "result": result,
        "message": f"Successfully processed {result['sent_count']} absentee notification(s)."
    })


@app.route("/api/timetable/current")
def api_current_period():
    active = Timetable.get_current_active_period()
    return jsonify({
        "has_active_period": active is not None,
        "period": active
    })


@app.route("/api/scanner/status")
def api_scanner_status():
    status = scanner_service.get_status()
    metrics = Attendance.get_today_metrics()
    return jsonify({"status": status, "metrics": metrics})


@app.route("/api/scanner/logs")
@admin_required
def api_scanner_logs():
    return jsonify({"logs": scanner_service.get_recent_logs()})


@app.route("/api/scanner/trigger", methods=["POST"])
@admin_required
def api_scanner_trigger():
    try:
        result = scanner_service.execute_single_scan(quick=False)
        return jsonify({
            "success": True,
            "message": f"Scan complete. Found {result['total_detected_devices']} active devices.",
            "data": result
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/scanner/toggle", methods=["POST"])
@admin_required
def api_scanner_toggle():
    data = request.get_json() or {}
    action = data.get("action")
    if action == "start":
        Settings.set("scanner_active", "1")
        scanner_service.start()
        return jsonify({"success": True, "is_running": True, "message": "Scanner service started."})
    else:
        Settings.set("scanner_active", "0")
        scanner_service.stop()
        return jsonify({"success": True, "is_running": False, "message": "Scanner service stopped."})


@app.route("/api/scanner/simulate", methods=["POST"])
@admin_required
def api_scanner_simulate():
    data = request.get_json() or {}
    mac = data.get("mac_address", "").strip()
    if not is_valid_mac(mac):
        return jsonify({"success": False, "message": "Invalid MAC address format."}), 400

    result = scanner_service.simulate_device(mac)
    return jsonify({
        "success": True,
        "message": f"Simulation executed for {normalize_mac(mac)}.",
        "matched": len(result["matched_students"]),
        "newly_marked": len(result["newly_marked"]),
        "students": [s["name"] for s in result["matched_students"]]
    })


if __name__ == "__main__":
    print("=" * 60)
    print(" Automatic Wi-Fi Based Attendance System")
    print(f" Subnet: {Settings.get('authorized_subnet', '192.168.1.0/24')}")
    print(f" Daily Check-in Window: {Settings.get('checkin_start_time', '08:00')} - {Settings.get('checkin_cutoff_time', '09:30')} (Late until {Settings.get('checkin_late_cutoff_time', '10:30')})")
    print(" Default Admin: admin / admin123")
    print(" Access Web Dashboard at: http://127.0.0.1:5000")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True)
