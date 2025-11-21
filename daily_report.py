import os
import json
from datetime import datetime
from collections import defaultdict

# === Obsidian Pfad ===
VAULT_PATH = r"D:\40-Personal\003-ObsidianVault\My awesome vault"
REPORT_DIR = os.path.join(VAULT_PATH, "SelfObserverDaily")

# === Log-Dateien von SelfObserver ===
LOG_DIR = "logs"
LEGACY_LOG = os.path.join(LOG_DIR, "screen_log.jsonl")

os.makedirs(REPORT_DIR, exist_ok=True)


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
                entries.append({"ts": ts, "mode": mode})
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
# 3. Optimierungsaufgaben generieren (regelbasiert)
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
# 4. Report-Text erzeugen
# ------------------------------------------------------
def format_report(date_str, durations, longest_segment, switches, entries_count, log_path):
    total_min = sum(durations.values())
    work = durations.get("work", 0.0)
    video = durations.get("video", 0.0)
    social = durations.get("social", 0.0)
    idle = durations.get("idle", 0.0)

    if total_min > 0:
        work_share = work / total_min * 100
        video_share = video / total_min * 100
        social_share = social / total_min * 100
        idle_share = idle / total_min * 100
    else:
        work_share = video_share = social_share = idle_share = 0.0

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
        lines.append(f"| work   | {work:7.1f} | {work_share:6.1f} % |")
        lines.append(f"| video  | {video:7.1f} | {video_share:6.1f} % |")
        lines.append(f"| social | {social:7.1f} | {social_share:6.1f} % |")
        lines.append(f"| idle   | {idle:7.1f} | {idle_share:6.1f} % |")
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

    # 3. Optimierungsaufgaben
    lines.append("## 3. Konkrete Optimierungsaufgaben für morgen")
    lines.append(build_optimization_section(durations, longest_segment, switches))
    lines.append("")

    # 4. Referenz
    lines.append("## 4. Datenreferenz")
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
        report_path = os.path.join(REPORT_DIR, f"report_{date_str}.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(empty_report)
        return report_path

    durations, longest_segment, switches = compute_durations_and_segments(today_entries)
    report_md = format_report(date_str, durations, longest_segment, switches, len(today_entries), log_path)

    report_path = os.path.join(REPORT_DIR, f"report_{date_str}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    return report_path


if __name__ == "__main__":
    path = generate_daily_report()
    print("Tagesbericht gespeichert:", path)
