// Main JavaScript helper functions for student portal & common components

document.addEventListener("DOMContentLoaded", function () {
    // 1. MAC Address Auto-formatting (adds colons automatically & forces uppercase)
    const macInputs = document.querySelectorAll(".mac-input");
    macInputs.forEach(input => {
        input.addEventListener("input", function (e) {
            let val = e.target.value.replace(/[^0-9A-Fa-f]/g, "").toUpperCase();
            if (val.length > 12) val = val.substring(0, 12);
            let formatted = "";
            for (let i = 0; i < val.length; i += 2) {
                if (i > 0 && i < val.length) formatted += ":";
                formatted += val.substring(i, Math.min(i + 2, val.length));
            }
            e.target.value = formatted;
        });
    });

    // 2. Guide Tabs Switcher for MAC Address Discovery
    window.switchGuideTab = function (tabName) {
        const tabs = ["android", "ios", "windows", "macos", "linux"];
        tabs.forEach(t => {
            const btn = document.getElementById(`tab-btn-${t}`);
            const content = document.getElementById(`tab-content-${t}`);
            if (btn && content) {
                if (t === tabName) {
                    btn.classList.add("border-indigo-600", "text-indigo-600", "font-semibold");
                    btn.classList.remove("border-transparent", "text-slate-500");
                    content.classList.remove("hidden");
                } else {
                    btn.classList.remove("border-indigo-600", "text-indigo-600", "font-semibold");
                    btn.classList.add("border-transparent", "text-slate-500");
                    content.classList.add("hidden");
                }
            }
        });
    };

    // 3. Quick Roll Number Fill (Student Lookup)
    window.fillRollNumber = function (roll) {
        const input = document.getElementById("lookup-roll-input");
        if (input) {
            input.value = roll;
            input.focus();
        }
    };
});
