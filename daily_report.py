import json
import os
import subprocess
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

import behavior_digital_twin
import behavior_model
import time_series_forecasting
from selfobserver.capture import is_ignored_window
from selfobserver.config import ALLOWED_MODES

# === Obsidian Pfad ===
VAULT_PATH = r"D:\\40-Personal\\003-ObsidianVault\\My awesome vault"
REPORT_DIR = os.path.join(VAULT_PATH, "SelfObserverDaily")

# === Log-Dateien von SelfObserver ===
LOG_DIR = "logs"
LEGACY_LOG = os.path.join(LOG_DIR, "screen_log.jsonl")

OLLAMA = os.environ.get("OLLAMA_EXE", r"C:\\Users\\x1sci\\AppData\\Local\\Programs\\Ollama\\ollama.exe")
REPORT_MODEL = os.environ.get("REPORT_MODEL", "qwen2.5:7b")

os.makedirs(REPORT_DIR, exist_ok=True)


# ------------------------------------------------------
# Pfade und Logging
# ------------------------------------------------------
def report_path_for_date(day: date) -> str:
    """Return the on-disk path for a report corresponding to a given date."""
    return os.path.join(REPORT_DIR, f"report_{day.isoformat()}.md")


def _parse_timestamp(ts_str: str) -> datetime:
    """Parse timestamps, tolerating midnight as hour 24 by rolling to next day."""
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError as exc:
        if "hour must be in 0..23" in str(exc) and "24:" in ts_str:
            try:
                fixed = ts_str.replace(" 24:", " 00:").replace("T24:", "T00:")
                return datetime.fromisoformat(fixed) + timedelta(days=1)
            except Exception:
                pass
        raise


def latest_log_path():
    """Find the newest daily log file (fallback: legacy screen_log.jsonl)."""
    if not os.path.exists(LOG_DIR):
        return LEGACY_LOG if os.path.exists(LEGACY_LOG) else None

    newest = None
    newest_date = None

    for name in os.listdir(LOG_DIR):
        if not (name.startswith("screen_log_") and name.endswith(".jsonl")):
            continue
        date_part = name[len("screen_log_"):-len(".jsonl")]
        try:
            parsed = datetime.fromisoformat(date_part).date()
        except Exception:
            continue
        if not newest_date or parsed > newest_date:
            newest_date = parsed
            newest = os.path.join(LOG_DIR, name)

    if newest:
        return newest

    return LEGACY_LOG if os.path.exists(LEGACY_LOG) else None


def load_all_logs(log_path=None):
    """Load every log entry from the chosen log file."""
    entries = []
    log_file = log_path or latest_log_path()
    if not log_file or not os.path.exists(log_file):
        return entries

    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                ts_str = obj.get("ts")
                mode = obj.get("mode", "idle")
                if not ts_str:
                    continue
                ts = _parse_timestamp(ts_str)
                window_info = {"exe": obj.get("exe", ""), "title": obj.get("title", "")}
                if is_ignored_window(window_info):
                    continue
                entries.append(
                    {
                        "ts": ts,
                        "mode": mode,
                        "exe": window_info["exe"],
                        "title": window_info["title"],
                        "url": obj.get("url", ""),
                        "uia_labels": obj.get("uia_labels", []),
                        "confidence": obj.get("confidence", 0.0),
                        "embedding": obj.get("embedding"),
                    }
                )
            except Exception:
                # Fehlerhafte Zeilen werden einfach übersprungen
                continue

    entries.sort(key=lambda x: x["ts"])
    return entries


def filter_today(entries):
    """Filter only entries of today's date."""
    today = datetime.now().date()
    today_entries = [e for e in entries if e["ts"].date() == today]
    today_entries.sort(key=lambda x: x["ts"])
    return today_entries


# ------------------------------------------------------
# 1. Dauer pro Modus + Segmente
# ------------------------------------------------------
def compute_durations_and_segments(entries):
    """
    Compute per-mode durations, longest uninterrupted segment per mode, and number of mode switches.
    """
    durations = defaultdict(float)
    longest_segment = defaultdict(float)
    switches = 0

    if len(entries) < 2:
        return durations, longest_segment, switches

    for i in range(len(entries) - 1):
        cur = entries[i]
        nxt = entries[i + 1]
        dt = (nxt["ts"] - cur["ts"]).total_seconds() / 60.0
        if dt < 0:
            continue
        mode = cur["mode"]
        durations[mode] += dt

    current_mode = entries[0]["mode"]
    seg_start = entries[0]["ts"]

    for i in range(1, len(entries)):
        e = entries[i]
        if e["mode"] != current_mode:
            dt = (e["ts"] - seg_start).total_seconds() / 60.0
            if dt > longest_segment[current_mode]:
                longest_segment[current_mode] = dt
            switches += 1
            current_mode = e["mode"]
            seg_start = e["ts"]

    last_ts = entries[-1]["ts"]
    dt = (last_ts - seg_start).total_seconds() / 60.0
    if dt > 0 and dt > longest_segment[current_mode]:
        longest_segment[current_mode] = dt

    return durations, longest_segment, switches


# ------------------------------------------------------
# 2. KI-Kontext aufbereiten
# ------------------------------------------------------
def summarize_timeline(entries, limit=30):
    lines = []
    for e in entries[-limit:]:
        ts = e["ts"].strftime("%H:%M:%S")
        exe = (e.get("exe") or "").split("\\")[-1]
        title = e.get("title") or ""
        if len(title) > 60:
            title = title[:57] + "..."
        lines.append(f"{ts} | {e.get('mode')} | {exe} | {title}")
    return "\n".join(lines) if lines else "Keine Daten verfügbar"


def build_llm_context(durations, longest_segment, switches, entries):
    total_min = sum(durations.values())

    duration_lines = []
    for mode, mins in sorted(durations.items(), key=lambda kv: kv[0]):
        duration_lines.append(f"- {mode}: {mins:.1f} Minuten")

    longest_lines = []
    for mode, mins in sorted(longest_segment.items(), key=lambda kv: kv[0]):
        if mins > 0:
            longest_lines.append(f"- {mode}: {mins:.1f} Minuten am Stück")

    context = [
        "Rohdaten des Tages:",
        f"- Gesamtzeit: {total_min:.1f} Minuten",
        f"- Moduswechsel: {switches}",
        "- Dauer pro Modus:",
        *duration_lines,
        "- Längste zusammenhängende Phasen:",
        *(longest_lines or ["(keine längeren Phasen)"]),
        "- Neueste Zeitstempel (max 30):",
        summarize_timeline(entries),
    ]

    return "\n".join(context)


# ------------------------------------------------------
# 3. Einfache Zusammenfassung ohne Fachjargon
# ------------------------------------------------------
def build_plain_language_summary(durations, longest_segment, switches):
    total_min = sum(durations.values())
    if total_min <= 0:
        return "Heute liegen keine verwertbaren Nutzungsdaten vor."

    lines: List[str] = []
    sorted_modes = sorted(durations.items(), key=lambda kv: kv[1], reverse=True)
    top_modes = sorted_modes[:3]

    if top_modes:
        parts = []
        for mode, mins in top_modes:
            share = mins / total_min * 100
            block = longest_segment.get(mode, 0.0)
            block_text = f" (längster Block ~{block:.0f} Min)" if block > 0 else ""
            parts.append(f"{mode}: {mins:.0f} Min ({share:.0f} %){block_text}")
        lines.append("Hauptaktivitäten: " + "; ".join(parts) + ".")

    if switches >= 25:
        lines.append(
            "Viele Wechsel zwischen Apps/Modi – das deutet auf einen eher fragmentierten Tag hin. Versuche längere Blöcke einzuplanen."
        )
    elif switches >= 10:
        lines.append("Mäßige Anzahl an App-Wechseln – du hast zwischen Aufgaben gewechselt, aber nicht ständig.")
    else:
        lines.append("Wenig App-Wechsel – der Tag war relativ fokussiert.")

    idle_min = durations.get("idle", 0.0)
    if idle_min >= 60:
        lines.append("Es gab über eine Stunde Leerlauf ohne klaren Modus. Vielleicht kannst du dort kleine Aufgaben oder Pausen einplanen.")

    video_min = durations.get("video", 0.0)
    if video_min >= 120:
        lines.append("Viel Video-Zeit – falls das nicht geplant war, helfen feste Zeitfenster (z. B. nach erledigten Aufgaben).")

    work_min = durations.get("work", 0.0)
    if work_min > 0:
        block = longest_segment.get("work", 0.0)
        lines.append(f"Produktive Zeit: {work_min:.0f} Minuten, längster Arbeitsblock ca. {block:.0f} Minuten.")

    return "\n".join(lines)


def _format_minutes(total_minutes: float) -> str:
    """Return a human friendly hours/minutes string for dashboard style output."""
    hours = int(total_minutes // 60)
    minutes = int(round(total_minutes % 60))
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def _top_apps(entries: List[Dict[str, Any]], limit: int = 3) -> List[str]:
    """Return the most common apps/sites for the day."""
    counts = Counter()
    for e in entries:
        exe = (e.get("exe") or "").split("\\")[-1]
        if exe:
            counts[exe.lower()] += 1
        elif e.get("url"):
            counts[e["url"].lower()] += 1
    return [name for name, _ in counts.most_common(limit)]


def _bucketed_mode(entries: List[Dict[str, Any]], start_hour: int, end_hour: int) -> Dict[str, float]:
    """Approximate mode durations inside a given hour window (wrapping allowed)."""
    durations = defaultdict(float)
    if len(entries) < 2:
        return durations

    def overlap_minutes(start, end, win_start, win_end):
        # window may wrap past midnight; build windows with timedeltas to allow hour=24
        day_start = datetime.combine(start.date(), datetime.min.time())
        window_start = day_start + timedelta(hours=win_start)
        window_end = day_start + timedelta(hours=win_end)
        if win_end <= win_start:
            window_end += timedelta(days=1)

        seg_start = max(start, window_start)
        seg_end = min(end, window_end)
        if seg_end <= seg_start:
            return 0.0
        return (seg_end - seg_start).total_seconds() / 60.0

    for cur, nxt in zip(entries, entries[1:]):
        seg_start = cur["ts"]
        seg_end = nxt["ts"]
        if seg_end <= seg_start:
            continue
        minutes = overlap_minutes(seg_start, seg_end, start_hour, end_hour)
        if minutes > 0:
            durations[cur.get("mode", "unknown")] += minutes
    return durations


def _cluster_durations(entries: List[Dict[str, Any]], labels: List[int]) -> Dict[int, float]:
    """Approximate minutes spent per cluster using consecutive timestamps."""
    durations = defaultdict(float)
    if len(entries) < 2 or not labels:
        return durations

    for idx, (cur, nxt) in enumerate(zip(entries, entries[1:])):
        lbl = labels[idx] if idx < len(labels) else -1
        if lbl == -1:
            continue
        seg_start = cur["ts"]
        seg_end = nxt["ts"]
        if seg_end <= seg_start:
            continue
        durations[lbl] += (seg_end - seg_start).total_seconds() / 60.0
    return durations


# ------------------------------------------------------
# 4. Modellbasierte Abschnitte
# ------------------------------------------------------
def build_behavior_section(entries, analysis: Dict[str, Any] | None = None):
    if not entries:
        return "Keine Aktivitäten für eine Verhaltensanalyse vorhanden."

    analysis = analysis or behavior_model.analyze_behaviors(entries)
    labels = analysis.get("labels", [])
    if not labels:
        return "Keine Cluster konnten berechnet werden."

    clusters = analysis.get("clusters", {})
    transitions = analysis.get("transitions", {})
    flow = analysis.get("flow_state_likelihood", 0.0)
    anomalies = analysis.get("anomaly_indices", [])
    algo = analysis.get("algorithm", "unbekannt")

    lines: List[str] = []
    lines.append(f"Automatisch erkannte Verhaltenscluster (Algorithmus: {algo}):")

    if clusters:
        for lbl, info in sorted(clusters.items(), key=lambda kv: kv[1]["size"], reverse=True):
            lines.append(
                f"- Cluster {lbl}: {info['label']} (n={info['size']}, kognitive Last={info['avg_cognitive_load']}, Dopamin={info['avg_dopamine_drive']}, Ziel={info['avg_goal_focus']})"
            )
            if info["top_modes"]:
                mode_str = ", ".join([f"{m} ({c})" for m, c in info["top_modes"]])
                lines.append(f"  • Häufigste Modi: {mode_str}")
            if info["top_apps"]:
                app_str = ", ".join([f"{m} ({c})" for m, c in info["top_apps"]])
                lines.append(f"  • Häufigste Apps: {app_str}")

    if transitions:
        lines.append("Häufigste Wechsel zwischen Clustern/Modi:")
        for (a, b), count in transitions.most_common(6):
            lines.append(f"- {a} → {b}: {count}×")

    lines.append(f"Flow-Score (hoher Wert = konsistenter Tag): {flow:.2f}")
    if anomalies:
        lines.append(f"Auffällige Ausreißer: {len(anomalies)}")

    return "\n".join(lines)


def build_forecast_section(entries, analysis: Dict[str, Any] | None = None, forecast: Dict[str, Any] | None = None):
    if not entries:
        return "Keine Daten für eine Vorhersage vorhanden."

    forecast = forecast or time_series_forecasting.forecast_next_hour(entries, analysis)
    dist = forecast.get("distribution", {})

    if not dist:
        return "Keine verwertbare Vorhersage generiert."

    clusters_meta = forecast.get("clusters_meta", {})

    def cluster_name(lbl):
        info = clusters_meta.get(lbl)
        if info:
            return info.get("label", f"cluster_{lbl}")
        return f"cluster_{lbl}"

    lines: List[str] = []
    lines.append(f"Modell: {forecast.get('algorithm', 'unbekannt')}")

    if forecast.get("predicted_cluster") is not None:
        cid = forecast["predicted_cluster"]
        prob = dist.get(cid, 0.0) * 100
        lines.append(
            f"Wahrscheinlichster Zustand in der nächsten Stunde: {cluster_name(cid)} ({prob:.1f}% Wahrscheinlichkeit)."
        )

    lines.append("Verteilung der nächsten Stunde:")
    for cid, prob in sorted(dist.items(), key=lambda kv: kv[1], reverse=True):
        lines.append(f"- {cluster_name(cid)}: {prob*100:.1f}%")

    lines.append(
        f"Erwartete Produktivität: {forecast.get('productivity', 0.0):.2f} | Ablenkungsrisiko: {forecast.get('distraction', 0.0):.2f}"
    )

    insights = forecast.get("insights", [])
    if insights:
        lines.append("Hinweise:")
        for insight in insights:
            lines.append(f"- {insight}")

    return "\n".join(lines)


def build_digital_twin_section(entries, analysis: Dict[str, Any] | None = None, forecast: Dict[str, Any] | None = None):
    if not entries:
        return "Keine Aktivitäten für den Behavior Digital Twin verfügbar."

    forecast = forecast or time_series_forecasting.forecast_next_hour(entries, analysis)
    twin = behavior_digital_twin.build_digital_twin(entries, analysis, forecast)

    if not twin.get("features"):
        return "Digital Twin konnte nicht konstruiert werden."

    matrix = twin.get("transition_matrix", {})
    triggers = twin.get("procrastination_triggers", ([], []))
    best, worst = twin.get("productivity_windows", ([], []))
    stress = twin.get("stress", {})
    alignment = twin.get("goal_alignment", {})
    short_term = twin.get("short_term", {})
    insights = twin.get("insights", [])

    def _fmt_cluster(lbl):
        clusters = twin.get("clusters", {})
        info = clusters.get(lbl)
        if info:
            return info.get("label", f"cluster_{lbl}")
        return f"cluster_{lbl}"

    lines: List[str] = []
    lines.append("Behavior Digital Twin (Embedding + Markov + Kontext):")

    if matrix:
        lines.append("Top-Übergangswahrscheinlichkeiten:")
        flat = []
        for src, dsts in matrix.items():
            for dst, prob in dsts.items():
                flat.append((prob, src, dst))
        for prob, src, dst in sorted(flat, reverse=True)[:5]:
            lines.append(f"- {_fmt_cluster(src)} → {_fmt_cluster(dst)}: {prob*100:.1f}%")

    if short_term.get("predicted_cluster") is not None:
        cid = short_term["predicted_cluster"]
        prob = short_term.get("distribution", {}).get(cid, 0.0) * 100
        lines.append(f"Kurzfrist-Prognose (≈30 Min): {_fmt_cluster(cid)} ({prob:.1f}%).")

    if best:
        peak_str = ", ".join([f"{h:02d}:00 ({score:.2f})" for h, score in best])
        lines.append(f"Günstige Fokusslots: {peak_str}.")
    if worst:
        low_str = ", ".join([f"{h:02d}:00 ({score:.2f})" for h, score in worst])
        lines.append(f"Abfallende Phasen: {low_str}.")

    if triggers[0]:
        trigger_lines = [f"{app} ({cnt}×)" for app, cnt in triggers[0]]
        lines.append("Typische Ablenker (Apps): " + ", ".join(trigger_lines))
    if triggers[1]:
        context_lines = [f"{ctx} ({cnt}×)" for ctx, cnt in triggers[1]]
        lines.append("Typische Ablenker (Kontext): " + ", ".join(context_lines))

    if stress:
        lines.append(
            f"Stress-/Fragmentierungsindikator: {stress.get('estimate', 'unbekannt')} (Wechselrate {stress.get('switch_rate', 0.0)} pro Minute)."
        )

    if alignment:
        lines.append(
            f"Langfristorientierung: {alignment.get('trend', 'neutral')} (Alignment-Score {alignment.get('alignment', 0.0):.2f}, Ziel={alignment.get('goal', 0.0):.2f}, Dopamin={alignment.get('dopamine', 0.0):.2f})."
        )

    if insights:
        lines.append("Weitere Twin-Insights:")
        for ins in insights[:5]:
            lines.append(f"- {ins}")

    return "\n".join(lines)


# ------------------------------------------------------
# 5. LLM-Analyse
# ------------------------------------------------------
ANALYSIS_PROMPT = (
    "Du bist eine analytische Beobachtungs-KI. Beschreibe das digitale Nutzungsverhalten eines 15-jährigen Schülers klar und in Alltagssprache. "
    "Ordne die Aktivitäten in verständliche Kategorien (z. B. Lernen, Recherche, kreatives Arbeiten, Kommunikation, Gaming, Entertainment, Social Media, Leerlauf) ein und leite daraus Muster ab. "
    "Erkenne Tagesrhythmus, produktive Phasen, Konzentrationsabfälle und mögliche Übernutzung. "
    "Erstelle ein Stärkenprofil, nenne potenzielle Risiken (z. B. zu viel Social Media/Gaming, fehlende Pausen, Schlafverschiebungen) und schließe mit konkreten, realistischen Verbesserungsvorschlägen. "
    "Vermeide Fachjargon, schreibe kurze Sätze und erkläre Zahlen oder Begriffe, falls nötig. "
    "Die Ausgabe folgt immer dieser Struktur: kurze Zusammenfassung, Nutzungsprofil, Interessen, Verhaltenstrends, Stärken, Risiken und Empfehlungen."
)


def run_llm_analysis(prompt):
    try:
        result = subprocess.run(
            [OLLAMA, "run", REPORT_MODEL],
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=90,
        )
        out = result.stdout.decode("utf-8", "ignore").strip()
        return out if out else None
    except Exception:
        return None


def generate_llm_section(durations, longest_segment, switches, entries):
    context = build_llm_context(durations, longest_segment, switches, entries)
    prompt = (
        f"{ANALYSIS_PROMPT}\n\n"
        "Arbeite ausschließlich mit den bereitgestellten Rohdaten von heute und bleibe evidenzbasiert.\n"
        "Nutze folgende Informationen:\n"
        f"{context}\n\n"
        "Antworte nur mit der geforderten Struktur und ohne zusätzliche Einleitungen."
    )

    analysis = run_llm_analysis(prompt)
    if not analysis:
        return "(Die KI-Analyse konnte nicht erzeugt werden – bitte Ollama/LLM-Setup prüfen.)"

    return analysis


# ------------------------------------------------------
# 6. Optimierungsaufgaben generieren (regelbasiert)
# ------------------------------------------------------
def build_optimization_section(durations, longest_segment, switches):
    """Create actionable optimization tasks based on the data."""
    lines: List[str] = []
    total_min = sum(durations.values())

    if total_min <= 0:
        lines.append("Für heute liegen kaum verwertbare Daten vor. Morgen erneut messen und beobachten.")
        return "\n".join(lines)

    share = {m: durations[m] / total_min for m in durations.keys()}

    video_min = durations.get("video", 0.0)
    work_min = durations.get("work", 0.0)
    social_min = durations.get("social", 0.0)
    idle_min = durations.get("idle", 0.0)

    if share.get("video", 0.0) > 0.4:
        max_block = longest_segment.get("video", 0.0)
        target_block = min(45, max(25, int(max_block * 0.8) if max_block > 0 else 35))
        lines.append(
            f"- Video-Nutzung reduzieren: Heute ca. {video_min:.1f} Minuten, größter Block ≈ {max_block:.1f} Minuten. Ziel: Einzelne Blöcke auf max. {target_block} Minuten begrenzen."
        )

    if share.get("work", 0.0) < 0.3:
        lines.append(
            "- Arbeits-/Lernzeit erhöhen: Der Anteil produktiver Zeit ist heute relativ gering. Für morgen zwei Arbeitsblöcke von je 30–45 Minuten einplanen."
        )
    else:
        max_work_block = longest_segment.get("work", 0.0)
        if max_work_block < 30:
            lines.append(
                "- Fokussierte Arbeitsphasen stabilisieren: Längster Arbeitsblock war kurz. Ziel: mindestens 45 Minuten ohne App-Wechsel."
            )

    if social_min > 15 and switches > 15:
        lines.append(
            "- Fragmentierung durch soziale Apps reduzieren: Viele Moduswechsel und Social-Zeit. Feste Check-Zeiten (z. B. alle 60–90 Minuten) statt sofortiger Reaktion."
        )

    if idle_min > 60:
        lines.append(
            f"- Idle-Phasen nutzen: Etwa {idle_min:.1f} Minuten ohne klar zuordenbare Aktivität. Eine Phase morgen mit einer Mini-Aufgabe füllen (z. B. kurzes Wiederholen, Planung, Aufräumen)."
        )

    if not lines:
        lines.append(
            "Keine starken Ungleichgewichte sichtbar. Morgen Fokus auf klar definierte Lernblöcke und bewusste Pausenplanung beibehalten."
        )

    return "\n".join(lines)


# ------------------------------------------------------
# 7. Report-Text erzeugen
# ------------------------------------------------------
def format_report(date_str, durations, longest_segment, switches, entries_count, log_path, today_entries, analysis):
    total_min = sum(durations.values())
    has_behavior = len(today_entries) >= 2
    analysis = analysis if has_behavior else {}
    forecast = time_series_forecasting.forecast_next_hour(today_entries, analysis) if has_behavior else {}
    twin = behavior_digital_twin.build_digital_twin(today_entries, analysis, forecast) if has_behavior else {}

    week_str = datetime.now().strftime("%G-[W]%V")
    month_str = datetime.now().strftime("%B %Y")
    quarter = (datetime.now().month - 1) // 3 + 1
    day_type = "Weekend" if datetime.now().weekday() >= 5 else "Weekday"

    top_modes = sorted(durations.items(), key=lambda kv: kv[1], reverse=True)
    top_outcomes = [
        f"{mode}: {_format_minutes(mins)} (längster Block {longest_segment.get(mode, 0):.0f}m)"
        for mode, mins in top_modes[:3]
        if mins > 0
    ]

    optimization_lines = build_optimization_section(durations, longest_segment, switches).split("\n")
    top_apps = _top_apps(today_entries)
    anomalies = analysis.get("anomaly_indices", []) if analysis else []

    cluster_durations = _cluster_durations(today_entries, analysis.get("labels", [])) if analysis else {}
    cluster_meta = analysis.get("clusters", {}) if analysis else {}

    transitions = analysis.get("transitions", Counter()) if analysis else Counter()
    total_transitions = sum(transitions.values()) or 1

    hourly_switches = Counter()
    for prev, nxt in zip(today_entries, today_entries[1:]):
        if prev.get("mode") != nxt.get("mode"):
            hourly_switches[prev["ts"].hour] += 1

    best_windows, worst_windows = twin.get("productivity_windows", ([], [])) if twin else ([], [])
    triggers = twin.get("procrastination_triggers", ([], [])) if twin else ([], [])
    stress = twin.get("stress", {"estimate": "niedrig", "switch_rate": 0.0}) if twin else {"estimate": "niedrig", "switch_rate": 0.0}
    alignment = twin.get("goal_alignment", {"alignment": 0.0, "trend": "neutral"}) if twin else {"alignment": 0.0, "trend": "neutral"}

    prod_score = int(min(100, max(0, (durations.get("work", 0.0) / (total_min or 1)) * 140))) if total_min else 0
    distract_score = int(min(100, max(0, ((durations.get("video", 0.0) + durations.get("social", 0.0)) / (total_min or 1)) * 140))) if total_min else 0
    dopamine_balance = int(alignment.get("alignment", 0.0) * 100)

    data_completeness = "hoch" if entries_count >= 30 else "mittel" if entries_count >= 10 else "gering"
    forecast_quality = "OK" if forecast else "Keine Vorhersage"

    def _timeline_block(label: str, start: int, end: int):
        bucket = _bucketed_mode(today_entries, start, end) if has_behavior else {}
        if not bucket:
            return label, "Keine Daten", "", ""
        primary_mode, primary_min = max(bucket.items(), key=lambda kv: kv[1])
        def _in_window(hour: int) -> bool:
            if end > start:
                return start <= hour < end
            return hour >= start or hour < end

        switches_block = sum(
            1
            for prev, nxt in zip(today_entries, today_entries[1:])
            if prev.get("mode") != nxt.get("mode") and _in_window(prev["ts"].hour)
        )
        notes = f"Top-Modus: {primary_mode} ({_format_minutes(primary_min)})"
        return label, primary_mode, f"Wechsel: {switches_block}", notes

    timeline_blocks = [
        _timeline_block("Morning (06–12)", 6, 12),
        _timeline_block("Afternoon (12–18)", 12, 18),
        _timeline_block("Evening (18–24)", 18, 24),
        _timeline_block("Late Night (24–06)", 0, 6),
    ]

    def _cluster_row(lbl, mins):
        meta = cluster_meta.get(lbl, {})
        return meta.get("label", f"Cluster {lbl}"), mins, meta.get("top_apps", []), meta.get("top_modes", [])

    lines: List[str] = []
    lines.extend(
        [
            "---",
            "tags:",
            "  - selfobserver",
            "  - 🧠",
            "Status:",
            "Category:",
            "  - \"[[🗺️ 05 Lifestyle MOC]]\"",
            "Topics:",
            "Summary:",
            "Source:",
            "---",
            ">[!info]- Meta Details",
            f">Date: {date_str}",
            f">Week: {week_str}",
            f">Month: {month_str}",
            f">Quarter: Q{quarter} - {datetime.now().strftime('%Y')}",
            f">Year: {datetime.now().strftime('%Y')}",
            "",
            f"# Human Screen Behavior Report — {date_str}",
            "",
            "## 1) Executive Summary",
            f"- **Day type:** {day_type}",
            "- **Top outcomes:**",
            *[f"  - {item}" for item in (top_outcomes or ["Keine klaren Aktivitäten erkannt."])],
            f"- **Biggest risk:** {triggers[0][0][0]} Ablenkung" if triggers and triggers[0] else "- **Biggest risk:** Hohe Wechselrate" if switches > 20 else "- **Biggest risk:** Keine deutliche Gefahr erkannt",
            f"- **One thing to do tomorrow:** {optimization_lines[0] if optimization_lines else 'Kein Vorschlag generiert.'}",
            "",
            "## 2) Key Metrics Dashboard",
            "### Time & Focus",
            f"- **Total active screen time:** {_format_minutes(total_min)}",
            f"- **Deep work time:** {_format_minutes(durations.get('work', 0.0))}",
            f"- **Context switches:** {switches}",
            f"- **Top apps/sites:** {', '.join(top_apps) if top_apps else 'keine Daten'}",
            "",
            "### Scores (0–100)",
            f"- **Productivity score:** {prod_score}",
            f"- **Distraction score:** {distract_score}",
            f"- **Dopamine ↔ Goal balance:** {dopamine_balance}",
            f"- **Stress/strain indicator:** {stress.get('estimate', 'niedrig').title()}",
            "",
            "### Quality & Confidence",
            f"- **Data completeness:** {data_completeness}",
            f"- **Anomalies detected:** {len(anomalies)}",
            f"- **Forecast accuracy (if available):** {forecast_quality}",
            "",
            "## 3) Daily Timeline",
        ]
    )

    for label, mode, transitions_info, notes in timeline_blocks:
        lines.extend(
            [
                f"### {label}",
                f"- **Primary mode:** {mode}",
                f"- **Key transitions:** {transitions_info or '–'}",
                f"- **Notes / triggers:** {notes or '–'}",
                "",
            ]
        )

    lines.append("## 4) Behavior Modes (Clusters)")
    if cluster_durations:
        for (lbl, mins) in sorted(cluster_durations.items(), key=lambda kv: kv[1], reverse=True)[:3]:
            name, dur, top_apps_meta, top_modes_meta = _cluster_row(lbl, mins)
            lines.extend(
                [
                    f"### Cluster {lbl} — {name}",
                    f"- **Time spent:** {_format_minutes(dur)}",
                    f"- **Typical apps:** {', '.join([a for a, _ in top_apps_meta]) if top_apps_meta else '–'}",
                    f"- **Intent / context:** {name}",
                    "- **Cognitive / emotion tone:** –",
                    "- **Dopamine vs goal:** –",
                    "- **Quality:** Productive / Neutral / Distracting",
                    "- **Notes:**",
                    "",
                ]
            )
    else:
        lines.append("Keine Clusterinformationen verfügbar.\n")

    lines.append("## 5) Transitions & Routines (State Machine View)")
    lines.append("### Most common transitions")
    if transitions:
        for (a, b), count in transitions.most_common(3):
            prob = count / total_transitions * 100
            lines.append(f"- **{a} → {b}:** ({prob:.1f} %, {count}) — meaning: Wechsel zwischen Modi")
    else:
        lines.append("- Keine Wechselmuster erkennbar")

    lines.extend(
        [
            "",
            "### Stability & churn",
            f"- **Stickiest modes:** {', '.join([m for m, _ in top_modes[:2]]) if top_modes else '–'}",
            f"- **Highest-switch hours:** {', '.join([f'{h:02d}h' for h, _ in hourly_switches.most_common(2)]) if hourly_switches else '–'}",
            "",
            "### Productivity windows",
            f"- **Best windows:** {', '.join([f'{h:02d}:00' for h, _ in best_windows]) if best_windows else '–'}",
            f"- **Worst windows:** {', '.join([f'{h:02d}:00' for h, _ in worst_windows]) if worst_windows else '–'}",
            f"- **What helped / hurt:** {'Ablenkende Apps' if triggers and triggers[0] else '–'}",
            "",
            "## 6) Triggers: Procrastination, Distraction, Stress",
            "### Trigger list (ranked)",
        ]
    )

    if triggers and (triggers[0] or triggers[1]):
        for idx, (app, count) in enumerate(triggers[0][:2], start=1):
            lines.extend(
                [
                    f"{idx}) **Trigger:** {app}",
                    "   - **When:** Häufig bei Dopamin-getriebenen Phasen",
                    f"   - **Pattern:** {count} Vorkommen",
                    "   - **Impact:** Zerstreut den Fokus",
                    "   - **Countermeasure:** Zeitfenster für Checks einplanen",
                    "",
                ]
            )
    else:
        lines.append("1) **Trigger:** keine klaren Ablenker gefunden")

    lines.extend(
        [
            "### Recovery signals",
            "- **What reliably resets focus:** Kurze Pause + klarer nächster Schritt",
            "",
            "## 7) Anomalies & Noteworthy Events",
        ]
    )

    if anomalies:
        idx = anomalies[0]
        ts = today_entries[idx]["ts"].strftime("%H:%M:%S") if idx < len(today_entries) else "–"
        lines.extend(
            [
                f"- **Anomaly:** ungewöhnliches Muster um {ts}",
                "  - **Evidence:** Cluster als Ausreißer markiert",
                "  - **Possible cause (inference):** Kontextwechsel oder neue App",
                "  - **Action:** Monitor",
                "",
            ]
        )
    else:
        lines.append("- **Anomaly:** keine Auffälligkeiten erkannt")

    lines.extend(
        [
            "## 8) Forecast & Tomorrow Outlook",
            "### Next-hour / next-day probabilities (from forecaster)",
        ]
    )

    if forecast and forecast.get("distribution"):
        dist_sorted = sorted(forecast["distribution"].items(), key=lambda kv: kv[1], reverse=True)[:3]
        lines.append("- **Most likely modes:** " + ", ".join([f"{cid} ({prob*100:.1f}%)" for cid, prob in dist_sorted]))
    else:
        lines.append("- **Most likely modes:** Keine Prognose")

    lines.extend(
        [
            f"- **Risk periods:** {', '.join([f'{h:02d}:00' for h, _ in worst_windows]) if worst_windows else '–'}",
            f"- **High-confidence prediction:** {forecast.get('predicted_cluster')}" if forecast else "- **High-confidence prediction:** –",
            "- **Low-confidence areas + why:** Geringe Datenbasis" if not forecast else "- **Low-confidence areas + why:** Modell=Baseline",
            "",
            "### If–Then plan",
            "- **If** (Ablenkungsrisiko steigt) **then** (Benachrichtigungen aus, 25-Minuten Fokusblock)",
            "",
            "## 9) Recommendations (max 3)",
        ]
    )

    for idx, rec in enumerate(optimization_lines[:3], start=1):
        lines.append(f"{idx}) {rec}")

    lines.extend(
        [
            "",
            "## 10) Appendix (Power User)",
            "### Cluster catalog",
        ]
    )

    if cluster_meta:
        for lbl, meta in cluster_meta.items():
            lines.append(
                f"- {lbl} → {meta.get('label', 'cluster')} → apps: {', '.join([a for a, _ in meta.get('top_apps', [])])}"
            )
    else:
        lines.append("- Keine Cluster berechnet")

    lines.extend(
        [
            "",
            "### Model / pipeline notes",
            f"- Clustering path used: {analysis.get('algorithm', 'none') if analysis else 'none'}",
            "- Guards tripped: –",
            "- Rolling baseline + priors: siehe Forecast-Baseline",
            "",
            "### Data integrity",
            f"- **Missing intervals:** {'keine erkennbar' if entries_count else 'vollständig offen'}",
            f"- **Device downtime:** {'nicht festgestellt' if entries_count else 'SelfObserver nicht aktiv?'}",
        ]
    )

    if log_path:
        lines.append(f"- **Log source:** {log_path}")

    return "\n".join([str(line) for line in lines])


# ------------------------------------------------------
# 8. Hauptfunktion für SelfObserver
# ------------------------------------------------------
def generate_daily_report():
    """Generates the daily report (called by self_observer.py)."""
    log_path = latest_log_path()
    all_entries = load_all_logs(log_path)
    today_entries = filter_today(all_entries)

    date_str = datetime.now().strftime("%Y-%m-%d")

    if not today_entries:
        durations, longest_segment, switches, analysis = defaultdict(float), defaultdict(float), 0, {}
    else:
        durations, longest_segment, switches = compute_durations_and_segments(today_entries)
        analysis = behavior_model.analyze_behaviors(today_entries)
    report_md = format_report(
        date_str,
        durations,
        longest_segment,
        switches,
        len(today_entries),
        log_path,
        today_entries,
        analysis,
    )

    report_path = report_path_for_date(datetime.now().date())
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    return report_path


if __name__ == "__main__":
    path = generate_daily_report()
    print("Tagesbericht gespeichert:", path)
