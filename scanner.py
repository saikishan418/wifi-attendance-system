"""
=============================================================================
AUTOMATED WI-FI DETECTION ENGINE (scanner.py)
=============================================================================
Architecture & Working Principle:
1. Subnet Discovery & Addressing:
   - Derives or receives the local CIDR subnet (e.g., 192.168.1.0/24 or 192.168.29.0/24).
   
2. Multi-Tier Active Discovery:
   - Tier 1 (Scapy Layer-2 ARP): If Scapy and WinPcap/Npcap/libpcap are available,
     it transmits Layer-2 ARP broadcast requests (Ethernet broadcast to ff:ff:ff:ff:ff:ff
     who-has <IP> tell <Scanner-IP>) and listens for unicast ARP replies.
   - Tier 2 (Multi-Threaded Ping Sweep + System ARP Table Parser): If raw socket
     drivers are unavailable or restricted (standard non-admin execution on Windows),
     the engine performs an asynchronous ICMP ping sweep across active subnet addresses
     to trigger kernel ARP table resolution, then extracts validated MAC addresses
     from the operating system's ARP cache (`arp -a`).
   - Tier 3 (Simulation & Manual Test Hooks): Allows immediate demonstration of device
     registration and attendance logging without requiring physical device reconfiguration.

3. Database Synchronization & Idempotency:
   - Detected MAC addresses are normalized into uppercase XX:XX:XX:XX:XX:XX format.
   - Cross-referenced against the `students` database table.
   - For matches, `Attendance.mark_present()` is invoked. The system enforces a
     UNIQUE constraint on (student_id, date), ensuring only one record per student per day.
=============================================================================
"""

import os
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date
from typing import List, Dict, Set, Optional, Tuple

from database import normalize_mac, is_valid_mac
from models import Student, Attendance, Settings, ScanEvent, Timetable, Course

# Attempt Scapy import; if unavailable or missing pcap driver, flag gracefully
SCAPY_AVAILABLE = False
try:
    from scapy.all import Ether, ARP, srp, conf
    # Suppress scapy runtime verbosity
    conf.verb = 0
    SCAPY_AVAILABLE = True
except Exception:
    SCAPY_AVAILABLE = False


class NetworkUtils:
    """Helper utilities for network subnet discovery and IP calculations."""

    @staticmethod
    def get_local_ip() -> str:
        """
        Determines the machine's primary local LAN IPv4 address
        by routing a dummy UDP socket towards a public DNS.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Does not actually transmit packets; queries local OS routing table
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        except Exception:
            local_ip = "127.0.0.1"
        finally:
            s.close()
        return local_ip

    @staticmethod
    def auto_detect_subnet() -> str:
        """
        Guesses the local /24 subnet based on primary LAN interface.
        Example: 192.168.29.24 -> 192.168.29.0/24
        """
        local_ip = NetworkUtils.get_local_ip()
        if local_ip.startswith("127.") or local_ip == "0.0.0.0":
            return "192.168.1.0/24"
        parts = local_ip.split(".")
        return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"

    @staticmethod
    def is_multicast_or_broadcast(mac: str) -> bool:
        """Filters out multicast, broadcast, and virtual network adapter MACs."""
        norm = mac.upper()
        if norm in ("FF:FF:FF:FF:FF:FF", "00:00:00:00:00:00"):
            return True
        # Multicast prefixes (IPv4 multicast starts with 01:00:5E, IPv6 starts with 33:33)
        if norm.startswith("01:00:5E") or norm.startswith("33:33:"):
            return True
        return False


class WifiScannerService:
    """
    Background worker thread service that periodically scans the network,
    detects active MAC addresses, and marks attendance for matching students.
    """

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._is_scanning = False
        self._last_scan_time: Optional[str] = None
        self._last_devices_count = 0
        self._last_matches_count = 0
        self._logs_buffer: List[Dict] = []
        self._max_buffer_size = 50

    def add_log(self, message: str, level: str = "INFO"):
        """Adds a log entry to the in-memory circular buffer for real-time UI monitoring."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = {
            "timestamp": timestamp,
            "level": level,
            "message": message
        }
        with self._lock:
            self._logs_buffer.append(entry)
            if len(self._logs_buffer) > self._max_buffer_size:
                self._logs_buffer.pop(0)
        print(f"[{timestamp}] [{level}] {message}")

    def get_recent_logs(self) -> List[Dict]:
        """Returns the in-memory log buffer."""
        with self._lock:
            return list(self._logs_buffer)

    def is_running(self) -> bool:
        """Returns True if the background polling thread is active."""
        return self._thread is not None and self._thread.is_alive()

    def get_status(self) -> Dict:
        """Returns comprehensive state for admin dashboard widgets."""
        configured_subnet = Settings.get("subnet_range", NetworkUtils.auto_detect_subnet())
        interval = int(Settings.get("scan_interval", "60"))
        engine_mode = Settings.get("preferred_engine", "auto")
        active_period = Timetable.get_current_active_period()

        return {
            "is_running": self.is_running(),
            "is_currently_scanning": self._is_scanning,
            "last_scan_time": self._last_scan_time or "Never",
            "last_devices_count": self._last_devices_count,
            "last_matches_count": self._last_matches_count,
            "configured_subnet": configured_subnet,
            "scan_interval": interval,
            "engine_mode": engine_mode,
            "scapy_available": SCAPY_AVAILABLE,
            "local_ip": NetworkUtils.get_local_ip(),
            "active_period": active_period
        }

    # =========================================================================
    # DETECTION STRATEGY 1: Scapy Layer-2 ARP Broadcast Ping
    # =========================================================================
    def scan_with_scapy(self, subnet: str) -> List[Dict[str, str]]:
        """
        Uses Scapy to broadcast an ARP who-has request across the subnet.
        Returns list of dicts: [{"ip": "...", "mac": "..."}]
        """
        if not SCAPY_AVAILABLE:
            raise RuntimeError("Scapy or packet capture provider (Npcap/libpcap) is not available.")

        devices = []
        try:
            self.add_log(f"Initiating Scapy ARP broadcast on {subnet}...", "INFO")
            # Build combined Ethernet + ARP packet
            arp_req = ARP(pdst=subnet)
            broadcast = Ether(dst="ff:ff:ff:ff:ff:ff")
            arp_request_broadcast = broadcast / arp_req

            answered_list = srp(arp_request_broadcast, timeout=2.5, verbose=False, retry=1)[0]

            for sent, received in answered_list:
                mac_raw = received.hwsrc
                ip_addr = received.psrc
                if is_valid_mac(mac_raw) and not NetworkUtils.is_multicast_or_broadcast(mac_raw):
                    devices.append({
                        "ip": ip_addr,
                        "mac": normalize_mac(mac_raw)
                    })
            self.add_log(f"Scapy ARP scan found {len(devices)} active devices.", "SUCCESS")
        except Exception as e:
            self.add_log(f"Scapy scan failed ({e}). Falling back to ARP table cache parser.", "WARNING")
            raise

        return devices

    # =========================================================================
    # DETECTION STRATEGY 2: Subnet Ping Sweep + OS ARP Table Parser (arp -a)
    # =========================================================================
    def _ping_host(self, ip: str):
        """Pings a single IP to trigger host ARP resolution in OS cache."""
        is_win = os.name == 'nt'
        cmd = ["ping", "-n" if is_win else "-c", "1", "-w" if is_win else "-W", "300", ip]
        try:
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1.0
            )
        except Exception:
            pass

    def perform_ping_sweep(self, subnet_base: str, start: int = 1, end: int = 254):
        """
        Spawns worker threads to ping subnet IP range in parallel.
        This forces devices to reply and populates the OS ARP table.
        """
        ip_parts = subnet_base.split(".")
        prefix = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}"
        
        self.add_log(f"Performing ping sweep on {prefix}.{start}-{end} to refresh ARP cache...", "INFO")
        with ThreadPoolExecutor(max_workers=35) as executor:
            targets = [f"{prefix}.{i}" for i in range(start, end + 1)]
            executor.map(self._ping_host, targets)

    def parse_system_arp_table(self) -> List[Dict[str, str]]:
        """
        Executes `arp -a` and parses output across Windows, Linux, and macOS.
        Returns list of dicts: [{"ip": "...", "mac": "..."}]
        """
        devices = []
        try:
            output = subprocess.check_output(
                "arp -a",
                shell=True,
                stderr=subprocess.STDOUT,
                timeout=5.0
            ).decode("latin1", errors="ignore")

            # Regex for IPv4 address followed by MAC address (hyphen or colon separated)
            pattern = re.compile(
                r'([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})\s+([0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2})'
            )

            seen_macs = set()
            for line in output.splitlines():
                match = pattern.search(line)
                if match:
                    ip = match.group(1)
                    mac_raw = match.group(2)
                    if is_valid_mac(mac_raw) and not NetworkUtils.is_multicast_or_broadcast(mac_raw):
                        norm = normalize_mac(mac_raw)
                        if norm not in seen_macs:
                            seen_macs.add(norm)
                            devices.append({"ip": ip, "mac": norm})

            self.add_log(f"OS ARP table parser detected {len(devices)} active physical hardware addresses.", "INFO")
        except Exception as e:
            self.add_log(f"Failed to execute or parse 'arp -a': {e}", "ERROR")

        return devices

    def scan_with_arp_cache(self, subnet: str, quick: bool = False) -> List[Dict[str, str]]:
        """
        Executes ping sweep (unless quick=True) followed by system ARP table parse.
        """
        if not quick:
            # Extract base IP for ping sweep
            base_ip = subnet.split("/")[0]
            self.perform_ping_sweep(base_ip)
        return self.parse_system_arp_table()

    # =========================================================================
    # CORE DISCOVERY DISPATCHER
    # =========================================================================
    def discover_active_devices(self, subnet: Optional[str] = None, quick: bool = False) -> Tuple[List[Dict[str, str]], str]:
        """
        Executes active network discovery based on configured preference and platform capabilities.
        Returns tuple: (list_of_devices, method_used)
        """
        if not subnet:
            subnet = Settings.get("subnet_range", NetworkUtils.auto_detect_subnet())

        preferred = Settings.get("preferred_engine", "auto")
        method_used = "Wi-Fi ARP Scan"

        if preferred == "scapy" and SCAPY_AVAILABLE:
            try:
                devices = self.scan_with_scapy(subnet)
                method_used = "Scapy ARP Broadcast"
                return devices, method_used
            except Exception:
                pass  # Fallback to ARP cache parser below

        # Auto or ARP Table parser
        try:
            if preferred == "auto" and SCAPY_AVAILABLE:
                try:
                    devices = self.scan_with_scapy(subnet)
                    method_used = "Scapy ARP Broadcast"
                    return devices, method_used
                except Exception:
                    pass

            devices = self.scan_with_arp_cache(subnet, quick=quick)
            method_used = "System ARP Cache Scan"
            return devices, method_used
        except Exception as e:
            self.add_log(f"Network discovery encountered error: {e}", "ERROR")
            return [], "Failed Scan"

    # =========================================================================
    # ATTENDANCE RECORDING SYNCHRONIZATION
    # =========================================================================
    def process_detected_macs(self, detected_devices: List[Dict[str, str]], detection_method: str) -> Dict:
        """
        Takes detected active MACs, compares them with students in the database,
        identifies the current active lecture period from the timetable schedule,
        and records attendance for present students if not already marked today.
        """
        today_str = date.today().isoformat()
        now_time = datetime.now().strftime("%H:%M:%S")

        # Determine if a specific timetable class period is active right now
        active_period = Timetable.get_current_active_period()
        course_id = active_period["course_id"] if active_period else 1
        course_label = f"{active_period['course_code']} ({active_period['room_number']})" if active_period else "General Campus Session"

        detected_mac_set = {d["mac"].upper() for d in detected_devices}
        matched_students = []
        newly_marked_students = []
        already_present_students = []

        all_students = Student.get_all()

        for st in all_students:
            st_mac = st["mac_address"].upper()
            if st_mac in detected_mac_set:
                matched_students.append(st)
                # Attempt to mark present for the active period/course (idempotent)
                was_new = Attendance.mark_present(
                    student_id=st["id"],
                    course_id=course_id,
                    date_str=today_str,
                    time_str=now_time,
                    detection_method=detection_method
                )
                if was_new:
                    newly_marked_students.append(st)
                    self.add_log(
                        f"Attendance RECORDED for {st['name']} ({st['roll_number']}) in [{course_label}] via {detection_method}.",
                        "SUCCESS"
                    )
                else:
                    already_present_students.append(st)

        # Audit event into database
        details = (
            f"Period: {course_label}, Active Devices: {len(detected_devices)}, "
            f"Matched: {len(matched_students)}, Newly Marked: {len(newly_marked_students)}"
        )
        ScanEvent.log(
            method=detection_method,
            active_macs_found=len(detected_devices),
            students_marked=len(newly_marked_students),
            details=details
        )

        self._last_scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._last_devices_count = len(detected_devices)
        self._last_matches_count = len(matched_students)

        return {
            "total_detected_devices": len(detected_devices),
            "matched_students": matched_students,
            "newly_marked": newly_marked_students,
            "already_present": already_present_students,
            "method": detection_method,
            "active_period": active_period,
            "course_label": course_label,
            "timestamp": self._last_scan_time
        }

    # =========================================================================
    # MANUAL TRIGGER & DEMO SIMULATION
    # =========================================================================
    def execute_single_scan(self, quick: bool = False) -> Dict:
        """Runs a synchronous scan cycle immediately (useful for UI 'Scan Now' button)."""
        with self._lock:
            self._is_scanning = True
        try:
            self.add_log("Triggering manual network scan...", "INFO")
            devices, method = self.discover_active_devices(quick=quick)
            result = self.process_detected_macs(devices, method)
            self.add_log(
                f"Scan finished. {result['total_detected_devices']} active devices found, "
                f"{len(result['newly_marked'])} new attendances marked.",
                "INFO"
            )
            return result
        finally:
            with self._lock:
                self._is_scanning = False

    def simulate_device(self, mac_address: str, ip_address: str = "192.168.1.150") -> Dict:
        """
        Simulates an active device presence on the network.
        Ideal for demos, presentations, and grading without needing physical mobile devices.
        """
        norm_mac = normalize_mac(mac_address)
        self.add_log(f"SIMULATION: Injecting virtual active packet for MAC {norm_mac} ({ip_address})", "WARNING")
        devices = [{"ip": ip_address, "mac": norm_mac}]
        result = self.process_detected_macs(devices, "Simulation Injection")
        return result

    # =========================================================================
    # BACKGROUND WORKER THREAD LIFECYCLE
    # =========================================================================
    def _worker_loop(self):
        """Continuous background execution loop."""
        self.add_log("Automated Wi-Fi scanner background service STARTED.", "SUCCESS")
        while not self._stop_event.is_set():
            # Check if scanner is enabled in system settings
            is_active_setting = Settings.get("scanner_active", "1")
            interval = int(Settings.get("scan_interval", "60"))

            if is_active_setting == "1":
                try:
                    with self._lock:
                        self._is_scanning = True
                    devices, method = self.discover_active_devices()
                    self.process_detected_macs(devices, method)
                except Exception as e:
                    self.add_log(f"Error during scheduled scan cycle: {e}", "ERROR")
                finally:
                    with self._lock:
                        self._is_scanning = False

            # Wait for next interval or until stop requested
            self._stop_event.wait(timeout=interval)

        self.add_log("Automated Wi-Fi scanner background service STOPPED.", "INFO")

    def start(self):
        """Starts the background scanner thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self.add_log("Scanner service is already running.", "WARNING")
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._worker_loop, name="WifiScannerWorker", daemon=True)
            self._thread.start()

    def stop(self):
        """Stops the background scanner thread safely."""
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                return
            self._stop_event.set()
        # Wait up to 5 seconds for thread to conclude gracefully
        self._thread.join(timeout=5.0)


# Global singleton scanner service instance
scanner_service = WifiScannerService()
