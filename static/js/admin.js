// Admin Dashboard JavaScript: Real-time Polling, Manual Scans, Simulations, and Live Terminal

function showToast(message, type = "info") {
    const container = document.getElementById("toast-container") || createToastContainer();
    const toast = document.createElement("div");
    
    const colors = {
        success: "bg-emerald-600 text-white border-emerald-700",
        error: "bg-rose-600 text-white border-rose-700",
        warning: "bg-amber-600 text-white border-amber-700",
        info: "bg-indigo-600 text-white border-indigo-700"
    };

    toast.className = `flex items-center gap-3 px-4 py-3 rounded-xl shadow-xl border text-sm font-medium transition-all duration-300 transform translate-y-2 opacity-0 ${colors[type] || colors.info}`;
    toast.innerHTML = `
        <svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
        </svg>
        <span class="flex-1">${message}</span>
        <button onclick="this.parentElement.remove()" class="text-white/80 hover:text-white">&times;</button>
    `;

    container.appendChild(toast);
    setTimeout(() => {
        toast.classList.remove("translate-y-2", "opacity-0");
    }, 20);

    setTimeout(() => {
        toast.classList.add("opacity-0", "translate-y-2");
        setTimeout(() => toast.remove(), 300);
    }, 4500);
}

function createToastContainer() {
    const cont = document.createElement("div");
    cont.id = "toast-container";
    cont.className = "fixed bottom-5 right-5 z-50 flex flex-col gap-2 max-w-sm";
    document.body.appendChild(cont);
    return cont;
}

// 1. Trigger Manual Network Scan
async function triggerScanNow(btnElement) {
    if (!btnElement) btnElement = document.getElementById("btn-scan-now");
    const originalContent = btnElement ? btnElement.innerHTML : "";
    if (btnElement) {
        btnElement.disabled = true;
        btnElement.innerHTML = `
            <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white inline" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
            </svg>
            Scanning Subnet...
        `;
    }

    try {
        const response = await fetch("/api/scanner/trigger", {
            method: "POST",
            headers: { "Content-Type": "application/json" }
        });
        const data = await response.json();
        if (data.success) {
            showToast(data.message, "success");
            // Refresh stats if on dashboard
            fetchScannerStatus();
            setTimeout(() => window.location.reload(), 1500);
        } else {
            showToast(data.message || "Scan failed.", "error");
        }
    } catch (err) {
        showToast("Network error executing scan.", "error");
    } finally {
        if (btnElement) {
            btnElement.disabled = false;
            btnElement.innerHTML = originalContent;
        }
    }
}

// 2. Toggle Background Scanner Service
async function toggleScannerService(action) {
    try {
        const response = await fetch("/api/scanner/toggle", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: action })
        });
        const data = await response.json();
        if (data.success) {
            showToast(data.message, "info");
            setTimeout(() => window.location.reload(), 1000);
        }
    } catch (err) {
        showToast("Error updating scanner service state.", "error");
    }
}

// 3. Inject Virtual Device Simulation
async function simulateDeviceFromUI() {
    const input = document.getElementById("simulate-mac-input");
    const mac = input ? input.value.trim() : "";
    if (!mac) {
        showToast("Please enter or select a MAC address to simulate.", "warning");
        return;
    }

    try {
        const response = await fetch("/api/scanner/simulate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mac_address: mac })
        });
        const data = await response.json();
        if (data.success) {
            showToast(
                `Simulation success! Detected ${data.matched} matching student(s). ${data.newly_marked} new attendance marked.`,
                data.newly_marked > 0 ? "success" : "info"
            );
            setTimeout(() => window.location.reload(), 1200);
        } else {
            showToast(data.message || "Simulation failed.", "error");
        }
    } catch (err) {
        showToast("Simulation API request failed.", "error");
    }
}

// 4. Polling Scanner Status and Live KPI Metrics
async function fetchScannerStatus() {
    try {
        const response = await fetch("/api/scanner/status");
        if (!response.ok) return;
        const data = await response.json();

        // Update Dashboard KPI elements if they exist
        const presentEl = document.getElementById("kpi-present-today");
        if (presentEl && data.metrics) presentEl.innerText = data.metrics.present_today;

        const absentEl = document.getElementById("kpi-absent-today");
        if (absentEl && data.metrics) absentEl.innerText = data.metrics.absent_today;

        const rateEl = document.getElementById("kpi-rate-today");
        if (rateEl && data.metrics) rateEl.innerText = `${data.metrics.attendance_rate}%`;

        const lastScanEl = document.getElementById("scanner-last-time");
        if (lastScanEl && data.status) lastScanEl.innerText = data.status.last_scan_time || "Never";

    } catch (err) {
        // Silently ignore background poll hiccup
    }
}

// 5. Live Terminal Logs Poller (for /admin/scanner)
async function pollTerminalLogs() {
    const terminalEl = document.getElementById("terminal-content");
    if (!terminalEl) return;

    try {
        const response = await fetch("/api/scanner/logs");
        if (!response.ok) return;
        const data = await response.json();
        if (data.logs) {
            terminalEl.innerHTML = data.logs.map(log => {
                let colorClass = "text-slate-300";
                if (log.level === "SUCCESS") colorClass = "text-emerald-400 font-medium";
                if (log.level === "WARNING") colorClass = "text-amber-400 font-medium";
                if (log.level === "ERROR") colorClass = "text-rose-400 font-semibold";
                if (log.level === "INFO") colorClass = "text-sky-300";
                return `<div><span class="text-slate-500">[${log.timestamp}]</span> <span class="${colorClass}">[${log.level}] ${log.message}</span></div>`;
            }).join("");
            
            terminalEl.scrollTop = terminalEl.scrollHeight;
        }
    } catch (err) {
        // Ignore terminal poll error
    }
}

// Auto-start polling on page load
document.addEventListener("DOMContentLoaded", function () {
    // Poll status every 8 seconds
    setInterval(fetchScannerStatus, 8000);

    // If terminal exists on this page, poll logs every 3 seconds
    if (document.getElementById("terminal-content")) {
        pollTerminalLogs();
        setInterval(pollTerminalLogs, 3000);
    }
});
