/* ============================================================
   GLOBAL VARIABLES
============================================================ */
let pieChart = null;
let lineChart = null;

/* ============================================================
   THEME SYSTEM
============================================================ */

let CURRENT_THEME = localStorage.getItem("line_theme") || "glow";

function setTheme(t) {
    CURRENT_THEME = t;
    localStorage.setItem("line_theme", t);
    applyThemeToLineChart();
}

function dynamicColor(mode) {
    const map = {
        coding: "#4FA3FF",
        browsing: "#B67BFF",
        gaming: "#FF6161",
        chatting: "#5CFF92",
        video: "#FFCA66",
        system: "#AAB2C8",
        idle: "#76839B",
    };
    return map[mode?.toLowerCase?.()] || "#94a3b8";
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
                pointRadius: 0,
            };

        case "apple":
            return {
                borderWidth: 3,
                tension: 0.4,
                fill: true,
                backgroundColor: appleGradient(ctx, color),
                borderColor: color,
                pointRadius: 2,
            };

        case "dsm":
            return {
                borderWidth: 2,
                tension: 0.25,
                fill: false,
                backgroundColor: "transparent",
                borderColor: color + "cc",
                pointRadius: 0,
            };

        case "cyber":
            return {
                borderWidth: 3,
                tension: 0.35,
                fill: true,
                backgroundColor: neonGlow(ctx, color),
                borderColor: color,
                pointRadius: 2,
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
            <td>${d.ts}</td>
            <td>${d.exe}</td>
            <td class="font-semibold">${d.mode}</td>
            <td>${(d.confidence * 100).toFixed(1)}%</td>
            <td>${d.title}</td>
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
                scales: { y: { beginAtZero: true } },
                plugins: { legend: { labels: { color: "#fff" } } }
            }
        });
    }

    const ctx = document.getElementById("lineChart").getContext("2d");

    lineChart.data.labels = labels;
    lineChart.data.datasets = labels.map((label, index) => {
        const ds = {
            label,
            data: labels.map(l => (l === label ? values[index] : null))
        };
        return Object.assign(ds, themeStyle(label, ctx));
    });

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
