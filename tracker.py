import os
import sys
import requests
import json
from datetime import datetime

# --- DEBUG INITIALISATION ---
print("⚙️ [DEBUG] Starting YPAD Tracker Engine (Robust JSON Patch)...")

# 1. VERIFY CLOUD SECRETS ARE CONNECTED
API_KEY = os.getenv("AIRLABS_API_KEY")
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

secrets_intact = True
if not API_KEY:
    print("❌ [DEBUG ERROR] Missing required secret variable: AIRLABS_API_KEY")
    secrets_intact = False
if not WEBHOOK_URL:
    print("❌ [DEBUG ERROR] Missing required secret variable: DISCORD_WEBHOOK_URL")
    secrets_intact = False

if not secrets_intact:
    print("🚨 [DEBUG CRITICAL] Cloud configuration incomplete. Terminating script.")
    sys.exit(1)

print("✅ [DEBUG] Cloud environment variables successfully mapped.")

# 2. DEFINING TARGET CRITERIA
TARGET_REGOS = {"VH-X4A", "VH-8VI", "VH-ZND", "B-1168", "VH-OGG"}

WIDEBODY_TYPES = {
    "77W", "772", "773", "77L", "77F",  # Boeing 777 variants
    "788", "789", "78X",                # Boeing 787 Dreamliners
    "359", "35K",                       # Airbus A350 variants
    "332", "333", "343", "346",         # Airbus A330 / A340
    "744", "748", "74F",                # Boeing 747 Queens
    "380", "388"                        # Airbus A380 Giants
}

SPECIAL_AIRLINES = {"QTR", "SIA", "MAS", "FJI", "ANZ"} 

def track_ypad_movements():
    url = "https://airlabs.co/api/v9/schedules"
    params = {
        "api_key": API_KEY, 
        "arr_icao": "YPAD",
        "limit": 50  
    }
    
    print(f"📡 [DEBUG] Sending request to AirLabs for YPAD arrivals...")
    try:
        response = requests.get(url, params=params, timeout=15)
        print(f"📡 [DEBUG] HTTP Server Response Code: {response.status_code}")
        response.raise_for_status()
        
        raw_text = response.text.strip()
        if not (raw_text.startswith("{") or raw_text.startswith("[")):
            print("🚨 [DEBUG CRITICAL] Server did not return JSON format data!")
            sys.exit(0) 
            
        data = response.json()
    except Exception as api_err:
        print(f"❌ [DEBUG CRITICAL] Network transmission or parser error: {api_err}")
        sys.exit(1)

    if "error" in data:
        print(f"❌ [DEBUG API ERROR] AirLabs explicitly rejected the request: {data['error']}")
        sys.exit(0)

    arrivals = data.get("response", [])
    print(f"📊 [DEBUG] Successfully parsed {len(arrivals)} total upcoming flights for YPAD.")

    matches = []
    dashboard_assets = []

    for idx, flight in enumerate(arrivals):
        rego = str(flight.get("reg_number", "")).upper().strip()
        aircraft = str(flight.get("aircraft_icao", "")).upper().strip()
        airline = str(flight.get("airline_icao", "")).upper().strip()
        flight_num = flight.get("flight_iata", "Unknown Flight")
        origin = flight.get("dep_iata", "UNK")
        arr_time = flight.get("arr_time", "Unknown Time")

        match_rego = rego in TARGET_REGOS
        match_widebody = aircraft in WIDEBODY_TYPES
        match_special_carrier = airline in SPECIAL_AIRLINES and match_widebody

        if match_rego or match_widebody:
            trigger_reason = []
            if match_rego: trigger_reason.append(f"Specific Rego ({rego})")
            if match_widebody: trigger_reason.append(f"Widebody Framework ({aircraft})")
            if match_special_carrier: trigger_reason.append("Flagship Long-Haul Entry")

            hit_summary = f"**Flight {flight_num}** ({aircraft} | Rego: `{rego if rego else 'N/A'}`) from **{origin}**\n↳ 🕒 Scheduled Arrival: `{arr_time}`\n↳ 🏷️ Reason: *{', '.join(trigger_reason)}*"
            print(f"🎯 [DEBUG HIT] Match found at row index {idx}: {flight_num}")
            matches.append(hit_summary)

            # Package structured payload data safely for the GitHub Pages static front-end
            dashboard_assets.append({
                "flight": flight_num,
                "rego": rego if rego else "N/A",
                "aircraft": aircraft,
                "airline": airline,
                "origin": origin,
                "arrival_time": arr_time,
                "reasons": trigger_reason
            })

    # Save output data state directly into the workspace repository environment
    export_payload = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "total_tracked_count": len(dashboard_assets),
        "assets": dashboard_assets
    }
    
    with open("data.json", "w") as f:
        json.dump(export_payload, f, indent=4)
    print("💾 [DEBUG] Local workflow snapshot data.json state written out to directory successfully.")

    if matches:
        print(f"✉️ [DEBUG] Found {len(matches)} alerts. Assembling Discord payload...")
        send_to_discord(matches)
    else:
        print("🧘 [DEBUG] Finished scan. No heavy or targeted assets detected in this schedule block.")

def send_to_discord(flight_list):
    content = "🚨 **YPAD ALERT: Heavies & Targeted Assets Confirmed!** 🚨\n\n"
    content += "\n\n".join(flight_list)
    content += "\n\nGood luck out on the airfield rails! 📸"

    payload = {"content": content}

    print(f"🚀 [DEBUG] Sending POST payload down the Discord webhook pipeline...")
    try:
        response = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if 200 <= response.status_code < 300:
            print("🎉 [DEBUG] Discord ping delivered flawlessly.")
        else:
            print(f"❌ [DEBUG ERROR] Discord rejected message payload: {response.text}")
    except Exception as discord_err:
        print(f"❌ [DEBUG ERROR] Pipeline transmission failure: {discord_err}")

if __name__ == "__main__":
    track_ypad_movements()
    print("🏁 [DEBUG] Run iteration finalized cleanly.")
