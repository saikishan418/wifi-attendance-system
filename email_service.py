"""
Automated Email Notification Service for Absentee Alerts.
Supports both live SMTP delivery and Mock/Simulation mode for immediate testing.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, date
from typing import Dict, List, Optional

from models import Settings, Attendance, EmailAlert

def generate_absentee_html(student_name: str, roll_number: str, course_name: str, course_code: str, date_str: str) -> str:
    """Generates a professional, responsive HTML email body for absentee alerts."""
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; color: #334155; }}
    .container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); }}
    .header {{ background: linear-gradient(135deg, #1e1b4b 0%, #4338ca 100%); padding: 30px; text-align: center; color: #ffffff; }}
    .header h1 {{ margin: 0; font-size: 22px; font-weight: 700; }}
    .badge {{ display: inline-block; background: rgba(239, 68, 68, 0.2); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.4); padding: 4px 12px; border-radius: 9999px; font-size: 11px; font-weight: 700; text-transform: uppercase; margin-top: 10px; }}
    .content {{ padding: 30px; line-height: 1.6; font-size: 14px; }}
    .details-box {{ background-color: #f1f5f9; border-radius: 12px; padding: 16px; margin: 20px 0; border: 1px solid #cbd5e1; }}
    .details-row {{ display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 13px; }}
    .details-row:last-child {{ margin-bottom: 0; }}
    .details-label {{ color: #64748b; font-weight: 600; }}
    .details-val {{ color: #0f172a; font-weight: 700; }}
    .warning {{ background-color: #fff1f2; border-left: 4px solid #f43f5e; padding: 12px 16px; border-radius: 6px; font-size: 13px; color: #9f1239; margin: 20px 0; }}
    .footer {{ background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 20px; text-align: center; font-size: 12px; color: #94a3b8; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Campus Attendance Alert</h1>
      <div class="badge">Unverified Absence Recorded</div>
    </div>
    <div class="content">
      <p>Dear <strong>{student_name}</strong>,</p>
      <p>This automated notification confirms that your registered device was <strong>not detected</strong> on campus Wi-Fi during today's scheduled lecture session.</p>
      
      <div class="details-box">
        <div class="details-row">
          <span class="details-label">Student ID / Roll:</span>
          <span class="details-val">{roll_number}</span>
        </div>
        <div class="details-row">
          <span class="details-label">Course / Session:</span>
          <span class="details-val">{course_code} - {course_name}</span>
        </div>
        <div class="details-row">
          <span class="details-label">Session Date:</span>
          <span class="details-val">{date_str}</span>
        </div>
        <div class="details-row">
          <span class="details-label">Recorded Status:</span>
          <span class="details-val" style="color: #e11d48;">ABSENT</span>
        </div>
      </div>

      <div class="warning">
        <strong>Important Exam Regulation:</strong> Institutional policy requires a minimum of <strong>75% attendance</strong> to maintain examination eligibility. Continued unexcused absences may lead to course de-registration.
      </div>

      <p style="font-size: 12px; color: #64748b;">
        <strong>Were you present in class?</strong> If you attended in person, please ensure your phone or laptop was connected to campus Wi-Fi with <em>"Randomized MAC"</em> turned off, or consult your instructor for manual verification.
      </p>
    </div>
    <div class="footer">
      Automated Wi-Fi Attendance Telemetry System &bull; Campus Academic Administration
    </div>
  </div>
</body>
</html>"""


class EmailNotificationService:
    @staticmethod
    def is_mock_mode() -> bool:
        """Returns True if mock simulation mode is enabled."""
        return Settings.get("smtp_mock_mode", "1") == "1"

    @staticmethod
    def send_single_alert(student: Dict, course_code: str, course_name: str, date_str: str) -> Dict:
        """Sends or simulates an absence alert to a student."""
        recipient = student["email"]
        subject = f"[Absence Notice] You were marked Absent for {course_code} on {date_str}"
        is_mock = EmailNotificationService.is_mock_mode()

        html_body = generate_absentee_html(
            student_name=student.get("full_name") or student.get("name", "Student"),
            roll_number=student["roll_number"],
            course_name=course_name,
            course_code=course_code,
            date_str=date_str
        )

        if is_mock:
            # Mock mode: safely simulate and record without requiring live SMTP credentials
            details = f"MOCK DISPATCH: Simulated email delivered to {recipient} for {course_code}"
            EmailAlert.log(
                student_id=student["id"],
                course_id=student.get("course_id", 1),
                date_str=date_str,
                recipient_email=recipient,
                subject=subject,
                status="Mock Sent",
                details=details
            )
            print(f"[EmailService - MOCK] {details}")
            return {"success": True, "mode": "mock", "recipient": recipient}

        # Real SMTP Delivery
        smtp_host = Settings.get("smtp_host", "smtp.gmail.com")
        smtp_port = int(Settings.get("smtp_port", "587"))
        smtp_user = Settings.get("smtp_user", "")
        smtp_pass = Settings.get("smtp_password", "")
        smtp_from = Settings.get("smtp_from", "attendance@campus.edu")

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = smtp_from
            msg["To"] = recipient
            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(smtp_host, smtp_port, timeout=10.0) as server:
                server.starttls()
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_from, [recipient], msg.as_string())

            EmailAlert.log(
                student_id=student["id"],
                course_id=student.get("course_id", 1),
                date_str=date_str,
                recipient_email=recipient,
                subject=subject,
                status="Sent",
                details=f"SMTP transmission to {recipient} succeeded."
            )
            return {"success": True, "mode": "smtp", "recipient": recipient}

        except Exception as e:
            err_msg = str(e)
            EmailAlert.log(
                student_id=student["id"],
                course_id=student.get("course_id", 1),
                date_str=date_str,
                recipient_email=recipient,
                subject=subject,
                status="Failed",
                details=f"SMTP error: {err_msg}"
            )
            print(f"[EmailService - ERROR] Failed to send email to {recipient}: {err_msg}")
            return {"success": False, "mode": "smtp", "error": err_msg, "recipient": recipient}

    @staticmethod
    def dispatch_today_absentee_alerts(course_id: Optional[int] = None, date_str: Optional[str] = None) -> Dict:
        """
        Dispatches email alerts to all students who have not been marked present today.
        Returns a summary report.
        """
        target_date = date_str or date.today().isoformat()
        absentees = Attendance.get_absentees_for_date(date_str=target_date, course_id=course_id)

        sent_count = 0
        failed_count = 0
        is_mock = EmailNotificationService.is_mock_mode()

        for st in absentees:
            course_code = st.get("course_code", "GEN-100")
            course_name = st.get("course_name", "General Campus Session")
            res = EmailNotificationService.send_single_alert(
                student=st,
                course_code=course_code,
                course_name=course_name,
                date_str=target_date
            )
            if res["success"]:
                sent_count += 1
            else:
                failed_count += 1

        return {
            "target_date": target_date,
            "total_absentees": len(absentees),
            "sent_count": sent_count,
            "failed_count": failed_count,
            "is_mock_mode": is_mock
        }
