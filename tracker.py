#!/usr/bin/env python3
"""
Adelaide Airport (ADL) Plane Spotter – free serverless tracker.
Uses AirLabs API + Discord webhook + GitHub history.json auto-commit.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import requests

# ──────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────
AIRPORT_IATA = "ADL"
AIRPORT_ICAO = "YPAD"

# Tail numbers (registrations) – exact match (case-insensitive)
TARGET_REGS: Set[str] = {
    "VH-X4A", "VH-ZND", "VH-OGG", "VH-XZP", "VH-8VI",
}

# Aircraft ICAO type codes
# A380 → A388
# B747 → B744, B748, B74*
# B777 → B772, B77W, B773, B778, B779
# 4-engine airliners (common ICAO codes)
TARGET_TYPES: Set[str] = {
    # A380
    "A388",
    # B747 family
    "B744", "B748", "B74R", "B74S",
    # B777 family
    "B772", "B77W", "B773", "B778", "B779",
    # Other classic 4-engine airliners
    "A340", "A342", "A343", "A345", "A346",
    "IL96", "IL86",
}

# How long (hours) to keep a flight in history after last seen
HISTORY_TTL_HOURS = 18

HISTORY_FILE = "history.json"
API_BASE = "https://airlabs.co/api/v9"

# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)

def get_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        log(f"ERROR: missing required env var {name}")
        sys.exit(1)
    return val

def load_history() -> Dict[str, Any]:
    if not os.path.exists(HISTORY_FILE):
        return {"flights": {}, "last_cleanup": None}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "flights" not in data:
            data = {"flights": data, "last_cleanup": None}
        return data
    except Exception as e:
        log(f"WARN: could not load history.json – starting fresh ({e})")
        return {"flights": {}, "last_cleanup": None}

def save_history(data: Dict[str, Any]) -> None:
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

def cleanup_history(history: Dict[str, Any]) -> None:
    now = time.time()
    cutoff = now - (HISTORY_TTL_HOURS * 3600)
    flights = history.get("flights", {})
    before = len(flights)
    history["flights"] = {
        k: v for k, v in flights.items()
        if v.get("last_seen", 0) > cutoff
    }
    history["last_cleanup"] = datetime.now(timezone.utc).isoformat()
    removed = before - len(history["flights"])
    if removed:
        log(f"Cleaned {removed} expired entries from history")

def make_key(flight: Dict[str, Any]) -> str:
    """Unique key that survives status changes for the same physical flight."""
    f_iata = flight.get("flight_iata") or flight.get("flight_icao") or "UNK"
    reg = (flight.get("reg_number") or "").upper().replace("-", "")
    # Prefer flight_iata + approximate day so the same flight number on different days is distinct
    ts = flight.get("dep_time_ts") or flight.get("arr_time_ts") or int(time.time())
    day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y%m%d")
    return f"{f_iata}|{reg}|{day}"

def is_interesting(flight: Dict[str, Any]) -> bool:
    reg = (flight.get("reg_number") or "").upper().strip()
    ac_type = (flight.get("aircraft_icao") or "").upper().strip()

    if reg in TARGET_REGS or reg.replace("-", "") in {r.replace("-", "") for r in TARGET_REGS}:
        return True
    if ac_type in TARGET_TYPES:
        return True
    # Extra safety for partial matches / variants
    if ac_type.startswith(("A388", "B74", "B77", "A34")):
        return True
    return False

def status_label(status: str, dep_iata: str, arr_iata: str) -> str:
    s = (status or "").lower()
    if s in ("scheduled", "active"):
        if dep_iata == AIRPORT_IATA:
            return "🛫 Taking off / Active departure"
        if arr_iata == AIRPORT_IATA:
            return "🛬 Approaching / Active arrival"
        return "✈️ Active"
    if s == "landed":
        return "🛬 Landed"
    return f"ℹ️ {status or 'Unknown'}"

def build_embed(flight: Dict[str, Any], event: str) -> Dict[str, Any]:
    reg = flight.get("reg_number") or "N/A"
    ac = flight.get("aircraft_icao") or "N/A"
    f_iata = flight.get("flight_iata") or flight.get("flight_icao") or "N/A"
    airline = flight.get("airline_iata") or flight.get("airline_icao") or ""
    dep = flight.get("dep_iata") or "?"
    arr = flight.get("arr_iata") or "?"
    status = flight.get("status") or "unknown"
    alt = flight.get("alt")
    speed = flight.get("speed")
    lat = flight.get("lat")
    lng = flight.get("lng")

    title = f"{event} – {f_iata} ({reg})"
    description = (
        f"**Aircraft:** `{ac}`  |  **Airline:** `{airline}`\n"
        f"**Route:** `{dep}` → `{arr}`\n"
        f"**Status:** `{status}`"
    )

    fields = []
    if alt is not None:
        fields.append({"name": "Altitude", "value": f"{alt} m", "inline": True})
    if speed is not None:
        fields.append({"name": "Speed", "value": f"{speed} km/h", "inline": True})
    if lat is not None and lng is not None:
        fields.append({
            "name": "Position",
            "value": f"[{lat:.4f}, {lng:.4f}](https://www.google.com/maps?q={lat},{lng})",
            "inline": False
        })

    color = 0x00FF88 if "Landed" in event or "Approaching" in event else 0x3498DB

    return {
        "title": title,
        "description": description,
        "color": color,
        "fields": fields,
        "footer": {"text": f"Adelaide (ADL) Spotter • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

def send_discord(webhook: str, embeds: List[Dict[str, Any]]) -> None:
    if not embeds:
        return
    # Discord allows max 10 embeds per message
    for i in range(0, len(embeds), 10):
        chunk = embeds[i:i+10]
        payload = {"embeds": chunk}
        r = requests.post(webhook, json=payload, timeout=15)
        if r.status_code >= 400:
            log(f"Discord webhook error {r.status_code}: {r.text[:300]}")
        else:
            log(f"Sent {len(chunk)} Discord alert(s)")
        time.sleep(0.4)  # mild rate-limit politeness

def fetch_schedules(api_key: str, direction: str) -> List[Dict[str, Any]]:
    """direction = 'dep' or 'arr'"""
    params = {
        "api_key": api_key,
        f"{direction}_iata": AIRPORT_IATA,
        "limit": 200,          # free tier is limited; 200 is safe
    }
    url = f"{API_BASE}/schedules"
    try:
        r = requests.get(url, params=params, timeout=25)
        r.raise_for_status()
        data = r.json()
        # AirLabs sometimes returns {"response": [...], "request": ...}
        if isinstance(data, dict) and "response" in data:
            return data["response"] or []
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        log(f"Schedules ({direction}) error: {e}")
        return []

def fetch_live_flights(api_key: str, direction: str) -> List[Dict[str, Any]]:
    """Live ADS-B positions for flights that have dep/arr = ADL."""
    params = {
        "api_key": api_key,
        f"{direction}_iata": AIRPORT_IATA,
    }
    url = f"{API_BASE}/flights"
    try:
        r = requests.get(url, params=params, timeout=25)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and "response" in data:
            return data["response"] or []
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        log(f"Live flights ({direction}) error: {e}")
        return []

def enrich_with_live(schedules: List[Dict], live: List[Dict]) -> List[Dict]:
    """Merge live position / aircraft data into schedule records when possible."""
    live_by_iata = {}
    for f in live:
        key = f.get("flight_iata") or f.get("flight_icao")
        if key:
            live_by_iata[key] = f

    enriched = []
    for s in schedules:
        key = s.get("flight_iata") or s.get("flight_icao")
        merged = dict(s)
        if key and key in live_by_iata:
            live_f = live_by_iata[key]
            # Prefer live data for reg / type / position / status
            for k in ("reg_number", "aircraft_icao", "lat", "lng", "alt", "speed", "status", "hex"):
                if live_f.get(k) is not None:
                    merged[k] = live_f[k]
        enriched.append(merged)
    return enriched

def git_commit_history() -> None:
    """Commit & push history.json if it changed. Safe for GitHub Actions."""
    try:
        # Configure identity (required in Actions)
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)

        # Stage
        subprocess.run(["git", "add", HISTORY_FILE], check=True)

        # Check if anything staged
        status = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True
        )
        if status.returncode == 0:
            log("history.json unchanged – nothing to commit")
            return

        msg = f"chore: update plane-spotter history {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "push"], check=True)
        log("Successfully committed & pushed history.json")
    except subprocess.CalledProcessError as e:
        log(f"Git commit/push failed (non-fatal): {e}")
    except Exception as e:
        log(f"Unexpected git error: {e}")

# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────
def main() -> None:
    api_key = get_env("AIRLABS_API_KEY")
    webhook = get_env("DISCORD_WEBHOOK_URL")

    log("Starting Adelaide plane spotter run")

    history = load_history()
    cleanup_history(history)
    known = history["flights"]

    # 1. Pull schedules (best for status: scheduled / active / landed)
    dep_sched = fetch_schedules(api_key, "dep")
    arr_sched = fetch_schedules(api_key, "arr")
    all_sched = dep_sched + arr_sched
    log(f"Fetched {len(dep_sched)} departures + {len(arr_sched)} arrivals from schedules")

    # 2. Pull live positions (best for reg_number + aircraft_icao + lat/lng)
    dep_live = fetch_live_flights(api_key, "dep")
    arr_live = fetch_live_flights(api_key, "arr")
    all_live = dep_live + arr_live
    log(f"Fetched {len(dep_live)} live departures + {len(arr_live)} live arrivals")

    # 3. Enrich schedules with live data
    candidates = enrich_with_live(all_sched, all_live)

    # Also add pure live flights that might not be in schedules yet
    seen_keys = {make_key(c) for c in candidates}
    for lf in all_live:
        k = make_key(lf)
        if k not in seen_keys:
            candidates.append(lf)

    # 4. Filter interesting + detect new events
    alerts: List[Dict[str, Any]] = []
    now_ts = int(time.time())

    for flight in candidates:
        if not is_interesting(flight):
            continue

        key = make_key(flight)
        status = (flight.get("status") or "").lower()
        prev = known.get(key, {})

        # Decide if we should alert
        # We alert on first sighting of a new status that is interesting
        interesting_statuses = {"scheduled", "active", "landed", "en-route"}
        if status not in interesting_statuses:
            continue

        prev_status = (prev.get("status") or "").lower()
        already_alerted = prev.get("alerted_statuses", [])

        # New status we haven't pinged yet
        if status not in already_alerted:
            event = status_label(status, flight.get("dep_iata", ""), flight.get("arr_iata", ""))
            embed = build_embed(flight, event)
            alerts.append(embed)

            # Update history entry
            known[key] = {
                "status": status,
                "alerted_statuses": already_alerted + [status],
                "last_seen": now_ts,
                "reg": flight.get("reg_number"),
                "type": flight.get("aircraft_icao"),
                "flight": flight.get("flight_iata") or flight.get("flight_icao"),
                "route": f"{flight.get('dep_iata')}→{flight.get('arr_iata')}",
            }
            log(f"NEW ALERT: {key} → {status}")
        else:
            # Just refresh last_seen
            known[key]["last_seen"] = now_ts
            known[key]["status"] = status

    # 5. Persist
    history["flights"] = known
    save_history(history)

    # 6. Send Discord
    if alerts:
        send_discord(webhook, alerts)
    else:
        log("No new alerts this run")

    # 7. Commit history back to the repo
    git_commit_history()

    log("Run finished")

if __name__ == "__main__":
    main()
