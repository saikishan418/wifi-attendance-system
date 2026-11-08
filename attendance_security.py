"""
Security & Verification Module for Wi-Fi Attendance System.
Enforces:
1. Client IP campus Wi-Fi subnet verification (CIDR check).
2. Time window daily deadline enforcement (Start, On-Time Cutoff, Late Cutoff, Closed).
3. Secure Device Token (UUID v4) identity pairing without passwords, OTPs, or MAC addresses.
"""

import ipaddress
from datetime import datetime, date
from functools import wraps
from flask import request, jsonify, abort

def get_client_ip(req=None) -> str:
    """
    Extracts the true client IP from the request, taking reverse proxies
    (X-Forwarded-For) into account.
    """
    active_req = req or request
    x_forwarded_for = active_req.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        # First IP in comma-separated list is the original client IP
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = active_req.remote_addr or "127.0.0.1"
    
    # Handle IPv6-mapped IPv4 addresses like ::ffff:192.168.1.5
    if ip.startswith("::ffff:"):
        ip = ip[7:]
    elif ip == "::1":
        ip = "127.0.0.1"
        
    return ip

def verify_campus_wifi(client_ip: str = None) -> tuple[bool, dict]:
    """
    Verifies if incoming client IP matches authorized campus Wi-Fi subnet range(s).
    Returns (is_authorized: bool, details: dict).
    """
    from models import Settings
    
    ip_str = client_ip or get_client_ip()
    authorized_subnets_str = Settings.get("authorized_subnet", "192.168.1.0/24")
    allow_localhost = Settings.get("allow_localhost", "1") == "1"

    # Local development & testing exception
    if allow_localhost and ip_str in ("127.0.0.1", "localhost"):
        return True, {
            "authorized": True,
            "client_ip": ip_str,
            "matched_subnet": "127.0.0.1/32 (Localhost Dev Mode)",
            "message": f"Connected via verified local interface ({ip_str})."
        }

    try:
        client_obj = ipaddress.ip_address(ip_str)
        # Support comma or space separated CIDR strings (e.g., '192.168.1.0/24, 192.168.29.0/24')
        raw_subnets = [s.strip() for s in authorized_subnets_str.replace(";", ",").split(",") if s.strip()]
        
        for sub_str in raw_subnets:
            try:
                network = ipaddress.ip_network(sub_str, strict=False)
                if client_obj in network:
                    return True, {
                        "authorized": True,
                        "client_ip": ip_str,
                        "matched_subnet": sub_str,
                        "message": f"Verified on authorized campus Wi-Fi ({sub_str})."
                    }
            except ValueError:
                continue

        return False, {
            "authorized": False,
            "client_ip": ip_str,
            "configured_subnets": authorized_subnets_str,
            "message": f"Access denied: Your IP ({ip_str}) is not connected to the authorized campus Wi-Fi ({authorized_subnets_str})."
        }
    except Exception as e:
        return False, {
            "authorized": False,
            "client_ip": ip_str,
            "error": str(e),
            "message": f"Could not verify client network location: {str(e)}"
        }

def evaluate_checkin_window(now_dt: datetime = None) -> dict:
    """
    Evaluates current server time against the configured attendance windows:
    - [start_time, cutoff_time]: ON_TIME -> Marked as 'Present'
    - (cutoff_time, late_cutoff_time]: LATE -> Marked as 'Late'
    - Otherwise: NOT_STARTED or CLOSED
    """
    from models import Settings
    
    now = now_dt or datetime.now()
    now_time_str = now.strftime("%H:%M")
    today = now.date()

    start_str = Settings.get("checkin_start_time", "08:00").strip()
    cutoff_str = Settings.get("checkin_cutoff_time", "09:30").strip()
    late_cutoff_str = Settings.get("checkin_late_cutoff_time", "10:30").strip()

    try:
        start_dt = datetime.strptime(f"{today} {start_str}", "%Y-%m-%d %H:%M")
        cutoff_dt = datetime.strptime(f"{today} {cutoff_str}", "%Y-%m-%d %H:%M")
        late_cutoff_dt = datetime.strptime(f"{today} {late_cutoff_str}", "%Y-%m-%d %H:%M")
    except Exception:
        # Fallback if invalid time string
        start_dt = datetime.strptime(f"{today} 08:00", "%Y-%m-%d %H:%M")
        cutoff_dt = datetime.strptime(f"{today} 09:30", "%Y-%m-%d %H:%M")
        late_cutoff_dt = datetime.strptime(f"{today} 10:30", "%Y-%m-%d %H:%M")
        start_str, cutoff_str, late_cutoff_str = "08:00", "09:30", "10:30"

    # 1. Before opening time
    if now < start_dt:
        seconds_remaining = int((start_dt - now).total_seconds())
        return {
            "is_open": False,
            "status": "NOT_STARTED",
            "attendance_status": None,
            "message": f"Attendance check-in has not opened yet. Window opens today at {start_str}.",
            "seconds_remaining": seconds_remaining,
            "target_time": start_str,
            "start_time": start_str,
            "cutoff_time": cutoff_str,
            "late_cutoff_time": late_cutoff_str,
            "server_time": now_time_str
        }

    # 2. Within on-time window (Present)
    elif now <= cutoff_dt:
        seconds_remaining = int((cutoff_dt - now).total_seconds())
        return {
            "is_open": True,
            "status": "ON_TIME",
            "attendance_status": "Present",
            "message": f"Check-in window is OPEN. Deadline for on-time attendance is {cutoff_str}.",
            "seconds_remaining": seconds_remaining,
            "target_time": cutoff_str,
            "start_time": start_str,
            "cutoff_time": cutoff_str,
            "late_cutoff_time": late_cutoff_str,
            "server_time": now_time_str
        }

    # 3. Within late cutoff window (Late)
    elif now <= late_cutoff_dt and late_cutoff_dt > cutoff_dt:
        seconds_remaining = int((late_cutoff_dt - now).total_seconds())
        return {
            "is_open": True,
            "status": "LATE",
            "attendance_status": "Late",
            "message": f"On-time deadline ({cutoff_str}) has passed. Late check-in window open until {late_cutoff_str}.",
            "seconds_remaining": seconds_remaining,
            "target_time": late_cutoff_str,
            "start_time": start_str,
            "cutoff_time": cutoff_str,
            "late_cutoff_time": late_cutoff_str,
            "server_time": now_time_str
        }

    # 4. Window is closed
    else:
        return {
            "is_open": False,
            "status": "CLOSED",
            "attendance_status": None,
            "message": f"Attendance check-in is CLOSED for today. Final deadline was {late_cutoff_str if late_cutoff_dt > cutoff_dt else cutoff_str}.",
            "seconds_remaining": 0,
            "target_time": cutoff_str,
            "start_time": start_str,
            "cutoff_time": cutoff_str,
            "late_cutoff_time": late_cutoff_str,
            "server_time": now_time_str
        }

def require_campus_wifi(f):
    """
    Middleware decorator that restricts access exclusively to verified campus Wi-Fi IPs.
    Returns 403 Forbidden with detailed JSON explanation if outside subnet.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        is_auth, details = verify_campus_wifi()
        if not is_auth:
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({
                    "success": False,
                    "error_code": "NETWORK_UNAUTHORIZED",
                    "message": details.get("message", "Must be connected to campus Wi-Fi."),
                    "client_ip": details.get("client_ip")
                }), 403
            else:
                return abort(403, description=details.get("message"))
        return f(*args, **kwargs)
    return decorated_function
