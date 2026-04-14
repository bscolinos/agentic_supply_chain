"""
NERVE S3 Streaming Data Generator

Continuously generates shipment_events and weather_events as NDJSON files
and uploads them to S3 every tick (default 1s). Runs until Ctrl+C.

Each tick produces one small file per table folder. SingleStore Pipelines
pick up new files in real time, so the dashboard shows live streaming data.

Folders:
    s3://<bucket>/<prefix>/shipment_events/
    s3://<bucket>/<prefix>/weather_events/

Join integrity rules:
    - shipment_events.shipment_id  in [1 .. SHIPMENT_COUNT]  (matches seeded rows)
    - shipment_events.tracking_number = deterministic hash of shipment_id
    - shipment_events.facility_code   in FACILITY_CODES
    - weather_events.affected_facilities subset of FACILITY_CODES (JSON array)

Usage:
    python -m simulator.s3_data_gen                              # stream with defaults
    python -m simulator.s3_data_gen --events-per-tick 50         # fewer events per second
    python -m simulator.s3_data_gen --tick-interval 2            # every 2 seconds
    python -m simulator.s3_data_gen --weather-every 30           # weather event every 30 ticks
"""

import argparse
import hashlib
import json
import os
import random
import signal
import sys
import tempfile
import time as time_mod
from datetime import datetime, timedelta
from typing import List

import boto3

# ==========================================
# DEFAULTS
# ==========================================

DEFAULT_BUCKET = "fedex-demo-625151782031-us-east-1-an"
DEFAULT_PREFIX = "nerve"
DEFAULT_REGION = "us-east-1"

# Per-tick generation rates
DEFAULT_EVENTS_PER_TICK = 20        # shipment events per tick
DEFAULT_TICK_INTERVAL = 1.0         # seconds between ticks
DEFAULT_WEATHER_EVERY = 45          # emit a weather event every N ticks

# Seeded shipments (from seed.py: 10K shipments, auto_increment from 1)
SHIPMENT_COUNT = 10_000

# ==========================================
# Facility reference data (must match seed.py)
# ==========================================

FACILITY_CODES = [
    "MEM", "SDF", "IND", "OAK", "EWR", "DFW", "ORD",
    "ATL", "MIA", "SEA", "DEN", "PHX", "BNA", "CLT", "RDU",
]

FACILITY_COORDS = {
    "MEM": (35.0424, -89.9767), "SDF": (38.1744, -85.7360),
    "IND": (39.7173, -86.2944), "OAK": (37.7213, -122.2208),
    "EWR": (40.6895, -74.1745), "DFW": (32.8998, -97.0403),
    "ORD": (41.9742, -87.9073), "ATL": (33.6407, -84.4277),
    "MIA": (25.7959, -80.2870), "SEA": (47.4502, -122.3088),
    "DEN": (39.8561, -104.6737), "PHX": (33.4373, -112.0078),
    "BNA": (36.1263, -86.6774), "CLT": (35.2144, -80.9473),
    "RDU": (35.8801, -78.7880),
}

# ==========================================
# Shipment event constants
# ==========================================

EVENT_TYPES = [
    "picked_up", "departed", "arrived", "in_transit",
    "out_for_delivery", "customs_cleared", "sorted", "loaded",
]
EVENT_TYPE_WEIGHTS = [0.08, 0.18, 0.18, 0.25, 0.08, 0.03, 0.12, 0.08]

EVENT_DESCRIPTIONS = {
    "picked_up":        "Package picked up at {fac}",
    "departed":         "Departed {fac} facility",
    "arrived":          "Arrived at {fac}",
    "in_transit":       "In transit — scanned at {fac}",
    "out_for_delivery": "Out for delivery from {fac}",
    "customs_cleared":  "Customs cleared at {fac}",
    "sorted":           "Sorted at {fac} sort center",
    "loaded":           "Loaded onto vehicle at {fac}",
}

# ==========================================
# Weather event constants
# ==========================================

WEATHER_EVENT_TYPES = [
    "winter_storm", "hurricane", "tornado", "flooding",
    "extreme_heat", "fog", "thunderstorm",
]

WEATHER_SEVERITY = ["watch", "warning", "emergency"]
SEVERITY_WEIGHTS = [0.25, 0.45, 0.30]

WEATHER_NAMES = {
    "winter_storm":  ["Arctic Blast", "Polar Vortex", "Winter Storm", "Ice Storm", "Blizzard", "Nor'easter"],
    "hurricane":     ["Hurricane", "Tropical Storm", "Cyclone"],
    "tornado":       ["Tornado Watch", "Tornado Warning", "Supercell"],
    "flooding":      ["Flash Flood", "River Flooding", "Urban Flooding", "Coastal Surge"],
    "extreme_heat":  ["Heat Wave", "Extreme Heat Advisory", "Heat Dome"],
    "fog":           ["Dense Fog Advisory", "Fog Warning", "Freezing Fog"],
    "thunderstorm":  ["Severe Thunderstorm", "Lightning Storm", "Hail Storm", "Derecho"],
}

WEATHER_REGIONS = [
    (["MEM", "BNA"],           "Mid-South"),
    (["MEM", "BNA", "ATL"],    "Southeast Corridor"),
    (["EWR", "CLT", "RDU"],    "Eastern Seaboard"),
    (["ORD", "IND", "SDF"],    "Midwest"),
    (["OAK", "SEA"],           "Pacific Coast"),
    (["DFW", "PHX"],           "Southern Plains"),
    (["MIA", "ATL"],           "Gulf Coast"),
    (["DEN", "PHX"],           "Mountain West"),
    (["SEA", "DEN"],           "Northwest Corridor"),
    (["SDF", "IND", "ORD"],    "Ohio Valley"),
    (["MEM"],                  "Memphis Metro"),
    (["ATL", "CLT", "BNA"],    "Southern Appalachia"),
]


# ==========================================
# Tracking number (must match seed.py)
# ==========================================

def _tracking_number(shipment_id: int) -> str:
    idx = shipment_id - 1
    h = hashlib.md5(f"nerve-shipment-{idx}".encode()).hexdigest()
    digits = "".join(str(int(c, 16) % 10) for c in h[:12])
    return f"FDX{digits}"


# ==========================================
# Row generators
# ==========================================

def _make_shipment_events(n: int, now: datetime) -> List[dict]:
    rows = []
    for _ in range(n):
        sid = random.randint(1, SHIPMENT_COUNT)
        etype = random.choices(EVENT_TYPES, weights=EVENT_TYPE_WEIGHTS, k=1)[0]
        fac = random.choice(FACILITY_CODES)
        # Jitter timestamp slightly within the last second
        ts = now - timedelta(milliseconds=random.randint(0, 999))

        rows.append({
            "shipment_id": sid,
            "tracking_number": _tracking_number(sid),
            "event_type": etype,
            "facility_code": fac,
            "event_timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "description": EVENT_DESCRIPTIONS[etype].format(fac=fac),
        })
    return rows


def _make_weather_event(now: datetime) -> dict:
    wtype = random.choice(WEATHER_EVENT_TYPES)
    sev = random.choices(WEATHER_SEVERITY, weights=SEVERITY_WEIGHTS, k=1)[0]
    duration_h = random.uniform(2, 24)

    affected_codes, region_name = random.choice(WEATHER_REGIONS)
    primary_fac = affected_codes[0]
    lat, lng = FACILITY_COORDS[primary_fac]
    lat += random.uniform(-0.5, 0.5)
    lng += random.uniform(-0.5, 0.5)

    name = random.choice(WEATHER_NAMES[wtype])

    wind = int(random.uniform(15, 120)) if wtype in ("hurricane", "tornado", "thunderstorm", "winter_storm") else None
    precip = round(random.uniform(0.5, 8.0), 2) if wtype in ("flooding", "hurricane", "thunderstorm", "winter_storm") else None
    temp = None
    if wtype == "extreme_heat":
        temp = int(random.uniform(100, 120))
    elif wtype == "winter_storm":
        temp = int(random.uniform(-10, 25))

    radius = int(random.uniform(25, 150))

    desc = f"{name} affecting {region_name} region. "
    if sev == "emergency":
        desc += f"Severe conditions expected for {duration_h:.0f} hours. "
    elif sev == "warning":
        desc += "Hazardous conditions developing. "
    else:
        desc += "Monitoring conditions. "
    if wind:
        desc += f"Winds up to {wind} knots. "
    if precip:
        desc += f"Expected precipitation: {precip} inches. "

    end = now + timedelta(hours=duration_h)

    return {
        "event_name": f"{name} — {region_name}",
        "event_type": wtype,
        "severity": sev,
        "affected_region": region_name,
        "affected_facilities": json.dumps(affected_codes),
        "latitude": round(lat, 6),
        "longitude": round(lng, 6),
        "radius_miles": radius,
        "start_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "end_time": end.strftime("%Y-%m-%d %H:%M:%S"),
        "wind_speed_knots": wind,
        "precipitation_inches": precip,
        "temperature_f": temp,
        "description": desc.strip(),
        "is_active": 1,
    }


# ==========================================
# S3 upload helper
# ==========================================

def _upload_ndjson(s3_client, bucket: str, key: str, rows: List[dict]):
    """Write rows as NDJSON to a temp file, upload to S3."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name
        for row in rows:
            tmp.write(json.dumps(row, default=str) + "\n")
    try:
        s3_client.upload_file(tmp_path, bucket, key)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ==========================================
# Main streaming loop
# ==========================================

_running = True

def _handle_signal(sig, frame):
    global _running
    _running = False
    print("\nShutting down...")


def stream(args):
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    s3 = boto3.client("s3", region_name=args.region)
    prefix = args.prefix.strip("/")
    tick = 0
    total_se = 0
    total_we = 0

    print("=" * 60)
    print("NERVE Streaming Data Generator")
    print("=" * 60)
    print(f"Bucket:           s3://{args.bucket}/{prefix}/")
    print(f"Region:           {args.region}")
    print(f"Tick interval:    {args.tick_interval}s")
    print(f"Shipment events:  {args.events_per_tick}/tick")
    print(f"Weather events:   every {args.weather_every} ticks")
    print(f"Shipments in DB:  {SHIPMENT_COUNT:,}")
    print()
    print("Streaming... (Ctrl+C to stop)")
    print()

    while _running:
        tick += 1
        now = datetime.utcnow()
        ts_label = now.strftime("%H:%M:%S")

        # -- Shipment events (every tick) --
        se_rows = _make_shipment_events(args.events_per_tick, now)
        se_key = f"{prefix}/shipment_events/se_{now.strftime('%Y%m%d_%H%M%S')}_{tick:06d}.json"
        _upload_ndjson(s3, args.bucket, se_key, se_rows)
        total_se += len(se_rows)

        # -- Weather event (every N ticks) --
        we_count = 0
        if tick % args.weather_every == 0:
            we_row = _make_weather_event(now)
            we_key = f"{prefix}/weather_events/we_{now.strftime('%Y%m%d_%H%M%S')}_{tick:06d}.json"
            _upload_ndjson(s3, args.bucket, we_key, [we_row])
            we_count = 1
            total_we += 1

        # Status line
        we_marker = f" + 1 weather ({we_row['severity']})" if we_count else ""
        print(f"  [{ts_label}] tick {tick:,}: {len(se_rows)} shipment events{we_marker}  "
              f"(total: {total_se:,} SE, {total_we:,} WE)")

        # Sleep until next tick
        elapsed = (datetime.utcnow() - now).total_seconds()
        sleep_time = max(0, args.tick_interval - elapsed)
        if sleep_time > 0 and _running:
            time_mod.sleep(sleep_time)

    print()
    print("=" * 60)
    print(f"Stopped. Totals: {total_se:,} shipment events, {total_we:,} weather events in {tick:,} ticks")
    print("=" * 60)


def parse_args():
    ap = argparse.ArgumentParser(
        description="Stream NERVE event data to S3 continuously"
    )
    ap.add_argument("--bucket", default=DEFAULT_BUCKET)
    ap.add_argument("--prefix", default=DEFAULT_PREFIX,
                    help="S3 key prefix (table folders go under this)")
    ap.add_argument("--region", default=DEFAULT_REGION)
    ap.add_argument("--events-per-tick", type=int, default=DEFAULT_EVENTS_PER_TICK,
                    help="Shipment events generated per tick (default: 20)")
    ap.add_argument("--tick-interval", type=float, default=DEFAULT_TICK_INTERVAL,
                    help="Seconds between ticks (default: 1.0)")
    ap.add_argument("--weather-every", type=int, default=DEFAULT_WEATHER_EVERY,
                    help="Emit a weather event every N ticks (default: 45)")
    return ap.parse_args()


if __name__ == "__main__":
    args = parse_args()
    stream(args)