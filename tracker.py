import os
import sys
import smtplib
from email.mime.text import MIMEText
import requests

# --- DEBUG INITIALISATION ---
print("⚙️ [DEBUG] Starting YPAD Tracker Engine...")

# 1. VERIFY CLOUD SECRETS ARE CONNECTED
API_KEY = os.getenv("AIRLABS_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")

secrets_intact = True
for name, val in [("AIRLABS_API_KEY", API_KEY), ("SENDER_EMAIL", SENDER_EMAIL), 
                  ("SENDER_PASSWORD", SENDER_PASSWORD), ("RECEIVER_EMAIL", RECEIVER_EMAIL)]:
    if not val:
        print(f"❌ [DEBUG ERROR] Missing required secret variable: {name}")
        secrets_intact = False

if not secrets_intact:
    print("🚨 [DEBUG CRITICAL] Configuration incomplete. Terminating script.")
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

# String match keywords to parse airlines known for special liveries at YPAD
SPECIAL_AIRLINES = {"QTR", "SIA", "MAS", "FJI", "ANZ"} 

def track_ypad_movements():
    url = "https://airlabs.co"
    params = {"api_key": API_KEY, "arr_icao": "YPAD"}
    
    print(f"📡 [DEBUG] Sending request to AirLabs for YPAD arrivals...")
    try:
        response = requests.get(url, params=params, timeout=15)
        print(f"📡 [DEBUG] HTTP Server Response Code: {response.status_code}")
        response.raise_for_status()
        data = response.json()
    except Exception as api_err:
        print(f"❌ [DEBUG CRITICAL] Network or API request crashed: {api_err}")
        sys.exit(1)

    if "error" in data:
        print(f"❌ [DEBUG API ERROR] AirLabs returned an application error: {data['error']}")
        sys.exit(1)

    arrivals = data.get("response", [])
    print(f"📊 [DEBUG] Successfully parsed {len(arrivals)} total upcoming flights for YPAD.")

    matches = []

    for idx, flight in enumerate(arrivals):
        rego = str(flight.get("reg_number", "")).upper().strip()
        aircraft = str(flight.get("aircraft_icao", "")).upper().strip()
        airline = str(flight.get("airline_icao", "")).upper().strip()
        flight_num = flight.get("flight_iata", "Unknown Flight")
        origin = flight.get("dep_iata", "UNK")
        arr_time = flight.get("arr_time", "Unknown Time")

        # Matching Logic Rules
        match_rego = rego in TARGET_REGOS
        match_widebody = aircraft in WIDEBODY_TYPES
        match_special_carrier = airline in SPECIAL_AIRLINES and match_widebody

        if match_rego or match_widebody:
            trigger_reason = []
            if match_rego: trigger_reason.append(f"Specific Rego Match ({rego})")
            if match_widebody: trigger_reason.append(f"Widebody Framework ({aircraft})")
            if match_special_carrier: trigger_reason.append("Flagship Long-Haul Entry")

            hit_summary = f"✈️ Flight {flight_num} | Type: {aircraft} | Rego: {rego if rego else 'N/A'} | From: {origin} | Scheduled: {arr_time} -> [Reason: {' + '.join(trigger_reason)}]"
            print(f"🎯 [DEBUG HIT] Match found at row index {idx}: {hit_summary}")
            matches.append(hit_summary)

    if matches:
        print(f"✉️ [DEBUG] Found {len(matches)} alerts. Assembling dispatch payload...")
        dispatch_email(matches)
    else:
        print("🧘 [DEBUG] Finished scan. No heavy or targeted assets detected in this schedule block.")

def dispatch_email(flight_list):
    content = "G'day Spotter,\n\nThe following strategic targets have popped up on the YPAD tracking schedule:\n\n"
    content += "\n".join(flight_list)
    content += "\n\nGood luck out on the airfield rails!"

    msg = MIMEText(content)
    msg["Subject"] = "🚨 YPAD Alert: Targeted Plane/Wide-body Confirmed!"
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL

    print(f"📧 [DEBUG] Connecting to secure Google SMTP Relay system...")
    try:
        with smtplib.SMTP_SSL("://gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        print("🎉 [DEBUG] Email relay accepted. Message out the door successfully.")
    except Exception as email_err:
        print(f"❌ [DEBUG ERROR] Mail pipeline delivery failure: {email_err}")

if __name__ == "__main__":
    track_ypad_movements()
    print("🏁 [DEBUG] Run iteration finalized cleanly.")
