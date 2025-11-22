/* ============================================================
   GLOBAL VARIABLES
============================================================ */
let pieChart = null;
let lineChart = null;

function formatMinutesFriendly(minutes) {
    const m = minutes || 0;
    if (m >= 60) {
        const hours = m / 60;
        if (Math.abs(hours - Math.round(hours)) < 0.05) {
            return `${Math.round(hours)}h`;
        }
        return `${hours.toFixed(1)}h`;
    }
    if (m >= 10) {
        return `${Math.round(m)}m`;
    }
    return `${m.toFixed(1)}m`;
}

function formatMinutesFriendly(minutes) {
    const m = minutes || 0;
    if (m >= 60) {
        const hours = m / 60;
        if (Math.abs(hours - Math.round(hours)) < 0.05) {
            return `${Math.round(hours)}h`;
        }
        return `${hours.toFixed(1)}h`;
    }
    if (m >= 10) {
        return `${Math.round(m)}m`;
    }
    return `${m.toFixed(1)}m`;
}

function formatMinutesFriendly(minutes) {
    const m = minutes || 0;
    if (m >= 60) {
        const hours = m / 60;
        if (Math.abs(hours - Math.round(hours)) < 0.05) {
            return `${Math.round(hours)}h`;
        }
        return `${hours.toFixed(1)}h`;
    }
    if (m >= 10) {
        return `${Math.round(m)}m`;
    }
    return `${m.toFixed(1)}m`;
}

/* ============================================================
   THEME SYSTEM
============================================================ */

let CURRENT_THEME = localStorage.getItem("line_theme") || "glow";

function setTheme(t) {
    CURRENT_THEME = t;
    localStorage.setItem("line_theme", t);
    applyThemeToLineChart();
}

const DYNAMIC_COLOR_MAP = {
    coding: "#4FA3FF",
    browsing: "#B67BFF",
    gaming: "#FF6161",
    chatting: "#5CFF92",
    video: "#FFCA66",
    reading: "#56E0E0",
    writing: "#F97316",
    ai_chat: "#10B981",
    music: "#A78BFA",
    file_management: "#FACC15",
    exploring: "#22D3EE",
    settings: "#CBD5E1",
    studying: "#34D399",
    system: "#AAB2C8",
    idle: "#76839B",
    unknown: "#94a3b8",
    maybe_gaming: "#FB7185",
    gaming_hint: "#F472B6",
};

const FALLBACK_PALETTE = [
    "#ef4444", "#22c55e", "#3b82f6", "#f59e0b", "#14b8a6", "#a855f7",
    "#f97316", "#10b981", "#eab308", "#8b5cf6", "#06b6d4", "#ef476f",
    "#118ab2", "#ffd166", "#06d6a0", "#8338ec", "#3a86ff", "#ff006e"
];

function dynamicColor(mode) {
    const key = mode?.toLowerCase?.();
    if (key && DYNAMIC_COLOR_MAP[key]) return DYNAMIC_COLOR_MAP[key];
    if (!key) return "#94a3b8";

    const hash = [...key].reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
    return FALLBACK_PALETTE[hash % FALLBACK_PALETTE.length];
}

function themeStyle(mode, ctx) {
    const color = dynamicColor(mode);

    switch (CURRENT_THEME) {
        case "glow":
            return {
                borderWidth: 2.5,
                tension: 0.3,
                fill: true,
                backgroundColor: glowGradient(ctx, color),
                borderColor: color,
                borderDash: [5, 5],
                pointRadius: 4,
            };

        case "apple":
            return {
                borderWidth: 3,
                tension: 0.4,
                fill: true,
                backgroundColor: appleGradient(ctx, color),
                borderColor: color,
                pointRadius: 4,
            };

        case "dsm":
            return {
                borderWidth: 2,
                tension: 0.25,
                fill: false,
                backgroundColor: "transparent",
                borderColor: color + "cc",
                pointRadius: 3,
            };

        case "cyber":
            return {
                borderWidth: 3,
                tension: 0.35,
                fill: true,
                backgroundColor: neonGlow(ctx, color),
                borderColor: color,
                pointRadius: 4,
            };

        default:
            return {};
    }
}

function glowGradient(ctx, color) {
    const g = ctx.createLinearGradient(0, 0, 0, 300);
    g.addColorStop(0, color + "88");
    g.addColorStop(1, color + "00");
    return g;
}

function appleGradient(ctx, color) {
    const g = ctx.createLinearGradient(0, 0, 0, 350);
    g.addColorStop(0, color + "ff");
    g.addColorStop(0.4, color + "33");
    g.addColorStop(1, color + "00");
    return g;
}

function neonGlow(ctx, color) {
    const g = ctx.createRadialGradient(150, 150, 20, 150, 150, 250);
    g.addColorStop(0, color + "ff");
    g.addColorStop(1, color + "00");
    return g;
}

/* Apply theme to existing chart */
function applyThemeToLineChart() {
    if (!lineChart) return;

    const ctx = document.getElementById("lineChart").getContext("2d");
    lineChart.data.datasets.forEach(ds => {
        Object.assign(ds, themeStyle(ds.label, ctx));
    });
    lineChart.update();
}

/* ============================================================
   Animated Number
============================================================ */

function animateNumber(id, value) {
    const el = document.getElementById(id);
    let current = 0;
    const step = value / 30;

    const interval = setInterval(() => {
        current += step;
        if (current >= value) {
            current = value;
            clearInterval(interval);
        }
        el.innerText = current.toFixed(1);
    }, 20);
}

/* ============================================================
   Logs & Cards
============================================================ */

async function updateLogs() {
    const res = await fetch("/api/latest");
    const data = await res.json();
    if (!data.length) return;

    const latest = data[data.length - 1];

    let tbody = document.getElementById("log-body");
    tbody.innerHTML = "";

    [...data].reverse().forEach(d => {
        tbody.innerHTML += `
        <tr class="border-b border-slate-700/30">
            <td class="py-2 pr-4 align-top text-slate-300">${d.ts}</td>
            <td class="py-2 pr-4 align-top text-slate-200">${d.exe}</td>
            <td class="py-2 pr-4 align-top font-semibold">${d.mode}</td>
            <td class="py-2 pr-6 align-top text-slate-200">${(d.confidence * 100).toFixed(1)}%</td>
            <td class="py-2 pl-2 align-top text-slate-100">${d.title}</td>
        </tr>`;
    });

    updateCards(latest);
}

function updateCards(latest) {
    let stats = document.getElementById("stats");

    stats.innerHTML = `
        <div class="glass p-6 rounded-2xl shadow-xl">
            <div class="text-sm text-slate-400">Current Mode</div>
            <div class="text-3xl font-bold">${latest.mode}</div>
        </div>

        <div class="glass p-6 rounded-2xl shadow-xl">
            <div class="text-sm text-slate-400">App</div>
            <div class="text-xl font-semibold">${latest.exe}</div>
        </div>

        <div class="glass p-6 rounded-2xl shadow-xl">
            <div class="text-sm text-slate-400">Confidence</div>
            <div id="c_conf" class="text-xl font-semibold">0%</div>
        </div>
    `;

    animateNumber("c_conf", latest.confidence * 100);
}

/* ============================================================
   Pie Chart
============================================================ */

async function updatePie() {
    const res = await fetch("/api/stats/day");
    const data = await res.json();

    let labels = Object.keys(data);
    let values = Object.values(data).map(v => v / 60);

    // Keep the UI stable even when there is no data yet.
    if (!labels.length) {
        labels = ["No data yet"];
        values = [1];
    }

    const colors = labels.map(l => dynamicColor(l.toLowerCase()) || "#94a3b8");

    if (!pieChart) {
        pieChart = new Chart(document.getElementById("pieChart"), {
            type: "pie",
            data: {
                labels: labels,
                datasets: [{
                    data: values,
                    backgroundColor: colors,
                    borderWidth: 2,
                    hoverOffset: 25
                }]
            },
            options: {
                animation: { duration: 1200, easing: "easeInOutQuart" },
                layout: { padding: 20 },
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            color: "#fff",
                            font: { size: 16, weight: "600" },
                            usePointStyle: true,
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                const label = context.label || "";
                                const minutes = context.parsed;
                                return `${label}: ${formatMinutesFriendly(minutes)}`;
                            }
                        }
                    }
                }
            }
        });
        return;
    }

    pieChart.data.labels = labels;
    pieChart.data.datasets[0].data = values;
    pieChart.data.datasets[0].backgroundColor = colors;
    pieChart.update({ duration: 1200, easing: "easeInOutQuart" });
}

/* ============================================================
   Line Chart (Persistent + Smooth)
============================================================ */

async function updateLine() {
    const res = await fetch("/api/stats/day");
    const data = await res.json();

    let labels = Object.keys(data);
    let values = Object.values(data).map(v => v / 60);

    if (!labels.length) {
        labels = ["No data yet"];
        values = [0];
    }

    if (!lineChart) {
        const ctx = document.getElementById("lineChart").getContext("2d");
        lineChart = new Chart(document.getElementById("lineChart"), {
            type: "line",
            data: { labels: [], datasets: [] },
            options: {
                animation: false,
                scales: {
                    x: { ticks: { color: "#cbd5e1" }, grid: { color: "#1e293b" } },
                    y: { beginAtZero: true, ticks: { color: "#cbd5e1" }, grid: { color: "#1e293b" } }
                },
                plugins: { legend: { labels: { color: "#fff" } } }
            }
        });
    }

    const ctx = document.getElementById("lineChart").getContext("2d");

    const colors = labels.map(l => dynamicColor(l.toLowerCase()) || "#94a3b8");

    lineChart.data.labels = labels;
    lineChart.data.datasets = [Object.assign({
        label: "Usage",
        data: values,
        pointBackgroundColor: colors,
        pointBorderColor: colors,
        pointRadius: 5,
        spanGaps: true,
    }, themeStyle("usage", ctx))];

    lineChart.options.scales.y.ticks = Object.assign({}, lineChart.options.scales.y.ticks, {
        callback: (val) => formatMinutesFriendly(val)
    });

    lineChart.options.plugins.tooltip = {
        callbacks: {
            label: function (context) {
                const label = context.dataset.label || "Usage";
                const minutes = context.parsed.y;
                return `${label}: ${formatMinutesFriendly(minutes)}`;
            }
        }
    };

    lineChart.update();
}

/* ============================================================
   INTERVALS
============================================================ */

setInterval(updateLogs, 1000);
setInterval(updatePie, 5000);
setInterval(updateLine, 2000);

updateLogs();
updatePie();
updateLine();
