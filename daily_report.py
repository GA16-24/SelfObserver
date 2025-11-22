import json
import os
import subprocess
from collections import defaultdict
from datetime import datetime, date
from typing import Any, Dict, List

import behavior_model
import behavior_digital_twin
import time_series_forecasting
from self_observer import ALLOWED_MODES

# === Obsidian Pfad ===
VAULT_PATH = r"D:\40-Personal\003-ObsidianVault\My awesome vault"
REPORT_DIR = os.path.join(VAULT_PATH, "SelfObserverDaily")

# === Log-Dateien von SelfObserver ===
LOG_DIR = "logs"
LEGACY_LOG = os.path.join(LOG_DIR, "screen_log.jsonl")

OLLAMA = os.environ.get("OLLAMA_EXE", r"C:\\Users\\x1sci\\AppData\\Local\\Programs\\Ollama\\ollama.exe")
REPORT_MODEL = os.environ.get("REPORT_MODEL", "qwen2.5:7b")

os.makedirs(REPORT_DIR, exist_ok=True)


def report_path_for_date(day: date) -> str:
    """Return the on-disk path for a report corresponding to a given date."""
    return os.path.join(REPORT_DIR, f"report_{day.isoformat()}.md")

ANALYSIS_PROMPT = (
    "Du bist eine analytische Beobachtungs-KI. Deine Aufgabe ist es, das digitale "
    "Nutzungsverhalten eines 15-jährigen Schülers anhand der gegebenen Rohdaten objektiv zu analysieren. "
    "Die Daten können App-Nutzung, Tabs, Titel, Programme, Spiele, Chat-Inhalte, Zeitangaben, Tageszeiten "
    "oder Nutzungsdauern enthalten. Du ordnest jede Aktivität sinnvoll in Kategorien wie Lernen, Recherche, "
    "kreatives Arbeiten, Kommunikation, Gaming, Entertainment, Sport, Musik, Social Media oder Leerlauf ein "
    "und leitest daraus klare Muster ab. Identifiziere die Interessen, Hobbys und häufig wiederkehrenden "
    "Themen des Nutzers, erkenne seinen Tagesrhythmus, produktive Phasen, Konzentrationsabfälle und mögliche "
    "Übernutzung. Erstelle ein Stärkenprofil des Nutzers, zeige potenzielle Risiken wie Überlastung, zu hohe "
    "Social-Media- oder Gaming-Zeiten, fehlende Pausen oder Schlafverschiebungen auf und bleibe dabei "
    "vollständig evidenzbasiert. Schließe deine Analyse mit konkreten, realistischen und umsetzbaren "
    "Vorschlägen ab, die das Nutzungsverhalten verbessern können, zum Beispiel zur Zeitverteilung, zum Lernen, "
    "zu Pausen, zum Schlafrhythmus oder zur Fokussierung. Die Ausgabe folgt immer dieser Struktur: kurze "
    "Zusammenfassung, Nutzungsprofil, Interessen, Verhaltenstrends, Stärken, Risiken und Empfehlungen."
)


# ------------------------------------------------------
# 1. Logs laden
# ------------------------------------------------------
def latest_log_path():
    """Finde die aktuellste Tages-Logdatei (Fallback: legacy screen_log.jsonl)."""
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
    """Lädt alle Log-Einträge aus der neuesten Log-Datei."""
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
                ts = datetime.fromisoformat(ts_str)
                entries.append({
                    "ts": ts,
                    "mode": mode,
                    "exe": obj.get("exe", ""),
                    "title": obj.get("title", ""),
                    "url": obj.get("url", ""),
                    "uia_labels": obj.get("uia_labels", []),
                    "confidence": obj.get("confidence", 0.0),
                    "embedding": obj.get("embedding"),
                })
            except Exception:
                # Fehlerhafte Zeilen werden einfach übersprungen
                continue

    # nach Zeit sortieren
    entries.sort(key=lambda x: x["ts"])
    return entries


def filter_today(entries):
    """Filtert nur Einträge des heutigen Tages."""
    today = datetime.now().date()
    today_entries = [e for e in entries if e["ts"].date() == today]
    today_entries.sort(key=lambda x: x["ts"])
    return today_entries


# ------------------------------------------------------
# 2. Dauer pro Modus + Segmente
# ------------------------------------------------------
def compute_durations_and_segments(entries):
    """
    Berechnet:
      - Dauer pro Modus (in Minuten)
      - längste zusammenhängende Phase pro Modus (in Minuten)
      - Anzahl der Moduswechsel
    """
    durations = defaultdict(float)
    longest_segment = defaultdict(float)
    switches = 0

    if len(entries) < 2:
        return durations, longest_segment, switches

    # Dauer pro Modus
    for i in range(len(entries) - 1):
        cur = entries[i]
        nxt = entries[i + 1]
        dt = (nxt["ts"] - cur["ts"]).total_seconds() / 60.0  # Minuten
        if dt < 0:
            continue
        mode = cur["mode"]
        durations[mode] += dt

    # Segmente + Wechsel
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

    # letztes Segment
    last_ts = entries[-1]["ts"]
    dt = (last_ts - seg_start).total_seconds() / 60.0
    if dt > 0 and dt > longest_segment[current_mode]:
        longest_segment[current_mode] = dt

    return durations, longest_segment, switches


# ------------------------------------------------------
# 3. KI-Kontext aufbereiten
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


def build_behavior_section(entries, analysis: Dict[str, Any] | None = None):
    if not entries:
        return "Keine Aktivitäten für Verhaltensanalyse vorhanden."

    analysis = analysis or behavior_model.analyze_behaviors(entries)
    labels = analysis.get("labels", [])
    if not labels:
        return "Keine Cluster konnten berechnet werden."

    clusters = analysis.get("clusters", {})
    transitions = analysis.get("transitions", {})
    flow = analysis.get("flow_state_likelihood", 0.0)
    anomalies = analysis.get("anomaly_indices", [])
    algo = analysis.get("algorithm", "unbekannt")

    lines = [f"Verhaltens-Embedding genutzt (Algorithmus: {algo})."]

    if clusters:
        lines.append("Top-Cluster:")
        for lbl, info in sorted(clusters.items(), key=lambda kv: kv[1]["size"], reverse=True):
            lines.append(
                f"- Cluster {lbl} → {info['label']} (n={info['size']}, "
                f"kogn. Last={info['avg_cognitive_load']}, Dopamin={info['avg_dopamine_drive']}, Ziel={info['avg_goal_focus']})"
            )
            if info["top_modes"]:
                mode_str = ", ".join([f"{m} ({c})" for m, c in info["top_modes"]])
                lines.append(f"  • Häufigste Modi: {mode_str}")
            if info["top_apps"]:
                app_str = ", ".join([f"{m} ({c})" for m, c in info["top_apps"]])
                lines.append(f"  • Häufigste Apps: {app_str}")

    if transitions:
        lines.append("Modus-/Cluster-Wechsel:")
        for (a, b), count in transitions.most_common(6):
            lines.append(f"- {a} → {b}: {count}×")

    lines.append(f"Flow-State-Wahrscheinlichkeit (Dominate Cluster-Anteil): {flow:.2f}")
    if anomalies:
        lines.append(f"Ausreißer/rausfallende Punkte: {len(anomalies)}")

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
    lines.append(f"Modellwahl: {forecast.get('algorithm', 'unbekannt')}")

    if forecast.get("predicted_cluster") is not None:
        cid = forecast["predicted_cluster"]
        prob = dist.get(cid, 0.0) * 100
        lines.append(
            f"Wahrscheinlichster Cluster in der nächsten Stunde: {cluster_name(cid)} ({prob:.1f}% Wahrscheinlichkeit)."
        )

    lines.append("Cluster-Wahrscheinlichkeitsverteilung für die nächste Stunde:")
    for cid, prob in sorted(dist.items(), key=lambda kv: kv[1], reverse=True):
        lines.append(f"- {cluster_name(cid)}: {prob*100:.1f}%")

    lines.append(
        f"Erwartete Produktivität: {forecast.get('productivity', 0.0):.2f} | Ablenkungswahrscheinlichkeit: {forecast.get('distraction', 0.0):.2f}"
    )

    insights = forecast.get("insights", [])
    if insights:
        lines.append("Interpretierbare Hinweise:")
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
    lines.append("Behavior Digital Twin (Embedding + Markov + Kontext) aktiv.")

    if matrix:
        lines.append("Übergangswahrscheinlichkeiten (Top 5):")
        flat = []
        for src, dsts in matrix.items():
            for dst, prob in dsts.items():
                flat.append((prob, src, dst))
        for prob, src, dst in sorted(flat, reverse=True)[:5]:
            lines.append(f"- {_fmt_cluster(src)} → {_fmt_cluster(dst)}: {prob*100:.1f}%")

    if short_term.get("predicted_cluster") is not None:
        cid = short_term["predicted_cluster"]
        prob = short_term.get("distribution", {}).get(cid, 0.0) * 100
        lines.append(f"Kurzfrist (≈30 Min) erwartet: {_fmt_cluster(cid)} ({prob:.1f}%).")

    if best:
        peak_str = ", ".join([f"{h:02d}:00 ({score:.2f})" for h, score in best])
        lines.append(f"Produktivitätsfenster: {peak_str}.")
    if worst:
        low_str = ", ".join([f"{h:02d}:00 ({score:.2f})" for h, score in worst])
        lines.append(f"Produktivität fällt oft ab: {low_str}.")

    if triggers[0]:
        trigger_lines = [f"{app} ({cnt}×)" for app, cnt in triggers[0]]
        lines.append("Prokrastinationstrigger (Apps): " + ", ".join(trigger_lines))
    if triggers[1]:
        context_lines = [f"{ctx} ({cnt}×)" for ctx, cnt in triggers[1]]
        lines.append("Prokrastinationstrigger (Kontext): " + ", ".join(context_lines))

    if stress:
        lines.append(
            f"Stress-/Fragmentierungsindikator: {stress.get('estimate', 'unbekannt')} (Wechselrate {stress.get('switch_rate', 0.0)} pro Minute)."
        )

    if alignment:
        lines.append(
            f"Langfristorientierung: {alignment.get('trend', 'neutral')} (Alignment-Score {alignment.get('alignment', 0.0):.2f}, Ziel={alignment.get('goal', 0.0):.2f}, Dopamin={alignment.get('dopamine', 0.0):.2f})."
        )

    if insights:
        lines.append("Zusätzliche Twin-Insights:")
        for ins in insights[:5]:
            lines.append(f"- {ins}")

    return "\n".join(lines)


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
# 4. Optimierungsaufgaben generieren (regelbasiert)
# ------------------------------------------------------
def build_optimization_section(durations, longest_segment, switches):
    """
    Erzeugt konkrete Optimierungsaufgaben auf Basis der Daten.
    Keine LLM-Nutzung, nur einfache Regeln.
    """
    lines = []
    total_min = sum(durations.values())

    if total_min <= 0:
        lines.append("Für heute liegen kaum verwertbare Daten vor. Morgen erneut messen und beobachten.")
        return "\n".join(lines)

    share = {m: durations[m] / total_min for m in durations.keys()}

    video_min = durations.get("video", 0.0)
    work_min = durations.get("work", 0.0)
    social_min = durations.get("social", 0.0)
    idle_min = durations.get("idle", 0.0)

    # 1) Video-Anteil
    if share.get("video", 0.0) > 0.4:
        max_block = longest_segment.get("video", 0.0)
        target_block = min(45, max(25, int(max_block * 0.8) if max_block > 0 else 35))
        lines.append(
            f"- Video-Nutzung reduzieren: Heute ca. {video_min:.1f} Minuten, "
            f"größter Block ≈ {max_block:.1f} Minuten. "
            f"Ziel für morgen: Einzelne Video-Blöcke auf maximal {target_block} Minuten begrenzen."
        )

    # 2) Work-Anteil
    if share.get("work", 0.0) < 0.3:
        lines.append(
            "- Arbeits-/Lernzeit erhöhen: Der Anteil produktiver Zeit ist heute relativ gering. "
            "Für morgen mindestens zwei klar definierte Arbeitsblöcke von je 30–45 Minuten einplanen."
        )
    else:
        max_work_block = longest_segment.get("work", 0.0)
        if max_work_block < 30:
            lines.append(
                "- Fokussierte Arbeitsphasen stabilisieren: Die längste zusammenhängende Arbeitsphase war kurz. "
                "Für morgen ein Arbeitsintervall von mindestens 45 Minuten ohne App-Wechsel anstreben."
            )

    # 3) Social / Moduswechsel
    if social_min > 15 and switches > 15:
        lines.append(
            "- Fragmentierung durch soziale Apps reduzieren: Heute gab es viele Moduswechsel "
            "und relevante Social-Zeit. Für morgen feste Check-Zeiten (z. B. alle 60–90 Minuten) definieren "
            "statt permanente Benachrichtigungsreaktion."
        )

    # 4) Idle-Zeit
    if idle_min > 60:
        lines.append(
            f"- Idle-Phasen nutzen: Es wurden etwa {idle_min:.1f} Minuten ohne klar zuordenbare Aktivität erfasst. "
            "Für morgen mindestens eine dieser Phasen konkret mit einer Aufgabe belegen "
            "(z. B. Kurzwiederholung eines Themas, Ordnung des Systems, Planungsblock)."
        )

    if not lines:
        lines.append(
            "Die heutigen Daten zeigen kein extremes Ungleichgewicht. Für morgen kann das Muster "
            "beibehalten werden, mit Fokus auf klar definierten Lernblöcken und bewusster Pausenplanung."
        )

    return "\n".join(lines)


# ------------------------------------------------------
# 5. Report-Text erzeugen
# ------------------------------------------------------
def format_report(date_str, durations, longest_segment, switches, entries_count, log_path, today_entries, analysis):
    total_min = sum(durations.values())
    forecast = time_series_forecasting.forecast_next_hour(today_entries, analysis)

    mode_rows = []
    if total_min > 0:
        for mode in ALLOWED_MODES:
            mins = durations.get(mode, 0.0)
            share = mins / total_min * 100 if total_min > 0 else 0.0
            mode_rows.append((mode, mins, share))

        # Falls zusätzliche Modi existieren, die nicht in ALLOWED_MODES stehen, trotzdem anzeigen
        extra_modes = sorted(set(durations.keys()) - set(ALLOWED_MODES))
        for mode in extra_modes:
            mins = durations.get(mode, 0.0)
            share = mins / total_min * 100 if total_min > 0 else 0.0
            mode_rows.append((mode, mins, share))

    lines = []
    lines.append(f"# Tagesbericht – {date_str}\n")
    lines.append("Dieser Bericht wurde automatisch von SelfObserver erzeugt.")
    lines.append("Er basiert auf den aufgezeichneten Vordergrundaktivitäten des heutigen Tages.\n")

    # 1. Zeitverteilung
    lines.append("## 1. Zeitverteilung nach Modus (in Minuten)")
    if total_min <= 0:
        lines.append("Es liegen für heute keine ausreichenden Daten vor.\n")
    else:
        lines.append("| Modus   | Minuten | Anteil |")
        lines.append("|---------|---------|--------|")
        for mode, mins, share in mode_rows:
            lines.append(f"| {mode:<7}| {mins:7.1f} | {share:6.1f} % |")
        lines.append("")

    # 2. Muster
    lines.append("## 2. Verhaltensanalyse (technische Sicht)")
    lines.append(f"- Gesamterfasste Zeit: {total_min:.1f} Minuten.")
    lines.append(f"- Anzahl der aufgezeichneten Ereignisse: {entries_count}.")
    lines.append(f"- Anzahl der Moduswechsel (Indikator für Fragmentierung): {switches}.")

    if longest_segment:
        lines.append("- Längste zusammenhängende Phasen je Modus:")
        for mode, seg_min in longest_segment.items():
            if seg_min <= 0:
                continue
            lines.append(f"  - {mode}: ca. {seg_min:.1f} Minuten")
    lines.append("")

    # 3. Embedding-basierte Verhaltensmuster
    lines.append("## 3. Verhaltens-Embedding & Cluster")
    lines.append(build_behavior_section(today_entries, analysis))
    lines.append("")

    # 4. Behavior Digital Twin (probabilistisches Modell)
    lines.append("## 4. Behavior Digital Twin (probabilistisches Modell)")
    lines.append(build_digital_twin_section(today_entries, analysis, forecast))
    lines.append("")

    # 5. Zeitreihenbasierte Verhaltensvorhersage (nächste Stunde)
    lines.append("## 5. Zeitreihenbasierte Verhaltensvorhersage (nächste Stunde)")
    lines.append(build_forecast_section(today_entries, analysis, forecast))
    lines.append("")

    # 6. Optimierungsaufgaben
    lines.append("## 6. Konkrete Optimierungsaufgaben für morgen")
    lines.append(build_optimization_section(durations, longest_segment, switches))
    lines.append("")

    # 7. LLM-basierte Interpretation
    lines.append("## 7. KI-Analyse des Nutzungstages")
    lines.append(generate_llm_section(durations, longest_segment, switches, today_entries))
    lines.append("")

    # 8. Referenz
    lines.append("## 8. Datenreferenz")
    if log_path:
        lines.append(f"Die Rohdaten liegen in der Datei `{log_path}`.\n")
    else:
        lines.append("Es wurde keine Log-Datei gefunden.\n")

    return "\n".join(lines)


# ------------------------------------------------------
# 5. Hauptfunktion für SelfObserver
# ------------------------------------------------------
def generate_daily_report():
    """Wird von self_observer.py einmal täglich (z. B. 22:00) aufgerufen."""
    log_path = latest_log_path()
    all_entries = load_all_logs(log_path)
    today_entries = filter_today(all_entries)

    date_str = datetime.now().strftime("%Y-%m-%d")

    if not today_entries:
        # trotzdem leere Struktur schreiben，方便你看见“今天没数据”
        empty_report = (
            f"# Tagesbericht – {date_str}\n\n"
            "Es wurden für heute keine geeigneten Ereignisdaten gefunden.\n"
            "Mögliche Ursachen: SelfObserver war nicht aktiv oder der Tag ist noch nicht ausreichend fortgeschritten.\n"
        )
        report_path = report_path_for_date(datetime.now().date())
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(empty_report)
        return report_path

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
