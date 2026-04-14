"""
NERVE Data Seeder
Seeds the SingleStore database with realistic logistics data for demo.
Deterministic (seed=42) so every run produces identical data.
"""

import os
import random
import struct
import hashlib
from datetime import datetime, timedelta

import singlestoredb as s2
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Deterministic RNG
# ---------------------------------------------------------------------------
RNG = random.Random(42)

# ---------------------------------------------------------------------------
# DB connection helper (simulator runs standalone, not inside FastAPI)
# ---------------------------------------------------------------------------

def get_connection():
    return s2.connect(
        host=os.getenv("SINGLESTORE_HOST", "127.0.0.1"),
        port=int(os.getenv("SINGLESTORE_PORT", "3306")),
        user=os.getenv("SINGLESTORE_USER", "root"),
        password=os.getenv("SINGLESTORE_PASSWORD", ""),
        database=os.getenv("SINGLESTORE_DATABASE", "nerve"),
    )

# ---------------------------------------------------------------------------
# Reference data: 15 facilities
# ---------------------------------------------------------------------------

FACILITIES = [
    # (code, name, type, city, state, lat, lng, capacity)
    ("MEM", "Memphis World Hub",        "hub",         "Memphis",       "TN", 35.0424, -89.9767, 180000),
    ("SDF", "Louisville Hub",           "hub",         "Louisville",    "KY", 38.1744, -85.7360, 120000),
    ("IND", "Indianapolis Hub",         "hub",         "Indianapolis",  "IN", 39.7173, -86.2944, 100000),
    ("OAK", "Oakland Hub",             "hub",         "Oakland",       "CA", 37.7213, -122.2208, 90000),
    ("EWR", "Newark Hub",              "hub",         "Newark",        "NJ", 40.6895, -74.1745, 110000),
    ("DFW", "Dallas-Fort Worth Hub",   "hub",         "Dallas",        "TX", 32.8998, -97.0403, 95000),
    ("ORD", "Chicago Sort Center",     "sort_center", "Chicago",       "IL", 41.9742, -87.9073, 80000),
    ("ATL", "Atlanta Station",         "station",     "Atlanta",       "GA", 33.6407, -84.4277, 60000),
    ("MIA", "Miami Gateway",           "airport",     "Miami",         "FL", 25.7959, -80.2870, 55000),
    ("SEA", "Seattle Station",         "station",     "Seattle",       "WA", 47.4502, -122.3088, 50000),
    ("DEN", "Denver Sort Center",      "sort_center", "Denver",        "CO", 39.8561, -104.6737, 65000),
    ("PHX", "Phoenix Station",         "station",     "Phoenix",       "AZ", 33.4373, -112.0078, 45000),
    ("BNA", "Nashville Station",       "station",     "Nashville",     "TN", 36.1263, -86.6774, 40000),
    ("CLT", "Charlotte Station",       "station",     "Charlotte",     "NC", 35.2144, -80.9473, 42000),
    ("RDU", "Raleigh-Durham Station",  "station",     "Raleigh",       "NC", 35.8801, -78.7880, 38000),
]

FACILITY_CODES = [f[0] for f in FACILITIES]
HUB_CODES = [f[0] for f in FACILITIES if f[2] == "hub"]

# ---------------------------------------------------------------------------
# Realistic customer names & city pairs
# ---------------------------------------------------------------------------

FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael",
    "Linda", "David", "Elizabeth", "William", "Barbara", "Richard", "Susan",
    "Joseph", "Jessica", "Thomas", "Sarah", "Christopher", "Karen", "Daniel",
    "Lisa", "Matthew", "Nancy", "Anthony", "Betty", "Mark", "Margaret",
    "Steven", "Sandra", "Andrew", "Ashley", "Paul", "Emily", "Joshua",
    "Donna", "Kenneth", "Michelle", "Kevin", "Dorothy", "Brian", "Carol",
    "George", "Amanda", "Timothy", "Melissa", "Ronald", "Deborah", "Edward",
    "Stephanie", "Jason", "Rebecca", "Jeffrey", "Sharon", "Ryan", "Laura",
    "Jacob", "Cynthia", "Gary", "Kathleen", "Nicholas", "Amy", "Eric",
    "Angela", "Jonathan", "Shirley", "Stephen", "Anna", "Larry", "Brenda",
    "Justin", "Pamela", "Scott", "Emma", "Brandon", "Nicole", "Benjamin",
    "Helen", "Samuel", "Samantha", "Raymond", "Katherine", "Gregory", "Christine",
    "Frank", "Debra", "Alexander", "Rachel", "Patrick", "Carolyn", "Jack",
    "Janet", "Dennis", "Catherine", "Jerry", "Maria", "Tyler", "Heather",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz",
    "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris",
    "Morales", "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan",
    "Cooper", "Peterson", "Bailey", "Reed", "Kelly", "Howard", "Ramos",
    "Kim", "Cox", "Ward", "Richardson", "Watson", "Brooks", "Chavez",
    "Wood", "James", "Bennett", "Gray", "Mendoza", "Ruiz", "Hughes",
    "Price", "Alvarez", "Castillo", "Sanders", "Patel", "Myers", "Long",
]

COMPANY_NAMES = [
    "Acme Medical Supplies", "Heartland Pharmaceuticals", "TechVault Inc",
    "BlueRidge Healthcare", "Summit Electronics", "Prairie Wind Energy",
    "Coastal Biomedical", "Northstar Diagnostics", "RedHawk Logistics",
    "Valley Surgical", "Pinnacle Labs", "Meridian Health Systems",
    "Atlas Industrial", "Clearwater Medical", "Granite State Devices",
    "Ironwood Therapeutics", "Lakeshore Instruments", "Maple Leaf Pharma",
    "Pacific Rim Components", "Silverline Solutions", "Crestview BioTech",
    "Evergreen Medical", "Harbor Point Industries", "Keystone Health",
    "Ridgeline Optics", "Sunbelt Prosthetics", "Tidewater Implants",
    "Westfield Reagents", "Zenith Surgical Systems", "Orion Diagnostics",
]

# Realistic origin-destination city pairs (source city -> dest city, with facility codes)
# Weighted toward Memphis hub for the storm scenario
ROUTE_TEMPLATES = [
    # Through-Memphis routes (heavy weight - these are at risk in the storm)
    ("OAK", "EWR"), ("OAK", "ATL"), ("OAK", "CLT"), ("OAK", "RDU"),
    ("SEA", "ATL"), ("SEA", "MIA"), ("SEA", "CLT"), ("SEA", "EWR"),
    ("DFW", "EWR"), ("DFW", "ATL"), ("DFW", "ORD"), ("DFW", "CLT"),
    ("PHX", "EWR"), ("PHX", "ATL"), ("PHX", "CLT"), ("PHX", "MIA"),
    ("DEN", "ATL"), ("DEN", "EWR"), ("DEN", "MIA"), ("DEN", "CLT"),
    ("MIA", "ORD"), ("MIA", "SEA"), ("MIA", "DEN"), ("MIA", "OAK"),
    ("ATL", "OAK"), ("ATL", "SEA"), ("ATL", "DEN"), ("ATL", "DFW"),
    ("EWR", "OAK"), ("EWR", "SEA"), ("EWR", "DFW"), ("EWR", "PHX"),
    ("ORD", "MIA"), ("ORD", "ATL"), ("ORD", "DFW"), ("ORD", "PHX"),
    ("SDF", "MIA"), ("SDF", "ATL"), ("SDF", "PHX"), ("SDF", "OAK"),
    ("IND", "MIA"), ("IND", "ATL"), ("IND", "DFW"), ("IND", "OAK"),
    ("BNA", "EWR"), ("BNA", "OAK"), ("BNA", "MIA"), ("BNA", "SEA"),
    ("CLT", "OAK"), ("CLT", "SEA"), ("CLT", "DEN"), ("CLT", "PHX"),
    ("RDU", "OAK"), ("RDU", "DFW"), ("RDU", "DEN"), ("RDU", "SEA"),
    # Direct routes not through Memphis
    ("SDF", "IND"), ("IND", "SDF"), ("ORD", "SDF"), ("ATL", "CLT"),
]

EMAIL_DOMAINS = [
    "gmail.com", "yahoo.com", "outlook.com", "aol.com", "icloud.com",
    "hotmail.com", "protonmail.com", "comcast.net", "verizon.net", "att.net",
]

# ---------------------------------------------------------------------------
# Statuses and their relative positions in the delivery lifecycle
# ---------------------------------------------------------------------------

STATUS_WEIGHTS = {
    "created":          0.05,
    "picked_up":        0.08,
    "in_transit":       0.35,
    "at_hub":           0.25,
    "out_for_delivery": 0.12,
    "delivered":        0.15,
}

STATUS_LIST = list(STATUS_WEIGHTS.keys())
STATUS_CUM_WEIGHTS = []
_total = 0
for s in STATUS_LIST:
    _total += STATUS_WEIGHTS[s]
    STATUS_CUM_WEIGHTS.append(_total)

PRIORITY_WEIGHTS = {
    "standard":   0.70,
    "express":    0.15,
    "critical":   0.10,
    "healthcare": 0.05,
}
PRIORITY_LIST = list(PRIORITY_WEIGHTS.keys())
PRIORITY_CUM_WEIGHTS = []
_total = 0
for p in PRIORITY_LIST:
    _total += PRIORITY_WEIGHTS[p]
    PRIORITY_CUM_WEIGHTS.append(_total)


def _weighted_choice(items, cum_weights):
    r = RNG.random()
    for item, cw in zip(items, cum_weights):
        if r <= cw:
            return item
    return items[-1]


# ---------------------------------------------------------------------------
# Historical disruption data for vector search
# ---------------------------------------------------------------------------

DISRUPTION_TYPES = ["weather", "capacity", "carrier", "labor", "demand_surge"]
WEATHER_TYPES = ["winter_storm", "hurricane", "tornado", "flooding", "extreme_heat", "fog", "thunderstorm"]
SEVERITY_LEVELS = ["watch", "warning", "emergency"]
RESOLUTION_ACTIONS = ["full_reroute", "priority_reroute", "hold_and_wait", "split_strategy", "monitor"]

OUTCOME_TEMPLATES = [
    "Rerouted {n} shipments through {alt} hub. {pct}% met original SLA. Avg delay {hrs}h.",
    "Held shipments at {fac} for {hrs}h until conditions cleared. {pct}% of SLAs met.",
    "Split strategy: critical via ground through {alt}, standard held. {pct}% critical on-time.",
    "Full network reroute through {alt} and {alt2}. Cost +${cost}K but {pct}% SLA compliance.",
    "Monitored situation; storm passed in {hrs}h. Minimal impact, {pct}% on-time.",
    "Priority reroute for {n} healthcare/critical shipments. All delivered within SLA.",
    "Activated backup sort at {alt}. Processed {n} packages/hour. Delay reduced to {hrs}h.",
]


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

def _tracking_number(idx: int) -> str:
    """FDX + 12 digits, deterministic from index."""
    h = hashlib.md5(f"nerve-shipment-{idx}".encode()).hexdigest()
    digits = "".join(str(int(c, 16) % 10) for c in h[:12])
    return f"FDX{digits}"


def _customer_name(idx: int) -> str:
    """70% individuals, 30% companies."""
    if RNG.random() < 0.70:
        first = RNG.choice(FIRST_NAMES)
        last = RNG.choice(LAST_NAMES)
        return f"{first} {last}"
    return RNG.choice(COMPANY_NAMES)


def _customer_email(name: str) -> str:
    clean = name.lower().replace(" ", ".").replace(",", "").replace("&", "and")
    # Truncate long names
    clean = clean[:30]
    domain = RNG.choice(EMAIL_DOMAINS)
    suffix = RNG.randint(1, 999)
    return f"{clean}{suffix}@{domain}"


def _random_embedding(dim: int = 1536) -> bytes:
    """Random float32 vector packed as bytes for VECTOR(1536) column."""
    floats = [RNG.gauss(0, 1) for _ in range(dim)]
    return struct.pack(f"{dim}f", *floats)


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------

def seed_facilities(conn):
    """Insert 15 facilities."""
    print("[seed] Inserting facilities...")
    cur = conn.cursor()
    cur.execute("DELETE FROM facilities")
    sql = """
        INSERT INTO facilities
            (facility_code, facility_name, facility_type, city, state, latitude, longitude, capacity_packages_per_hour)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    cur.executemany(sql, FACILITIES)
    conn.commit()
    print(f"[seed]   -> {len(FACILITIES)} facilities inserted.")


def seed_shipments(conn, count: int = 10_000):
    """Insert 10,000 shipments with realistic data."""
    print(f"[seed] Generating {count} shipments...")
    now = datetime.utcnow()
    cur = conn.cursor()
    cur.execute("DELETE FROM shipment_events")
    cur.execute("DELETE FROM shipments")
    conn.commit()

    batch = []
    batch_size = 500

    for i in range(count):
        tracking = _tracking_number(i)
        origin, dest = RNG.choice(ROUTE_TEMPLATES)

        priority = _weighted_choice(PRIORITY_LIST, PRIORITY_CUM_WEIGHTS)
        status = _weighted_choice(STATUS_LIST, STATUS_CUM_WEIGHTS)

        # Current facility depends on status
        if status == "created":
            current = origin
        elif status == "picked_up":
            current = origin
        elif status == "delivered":
            current = dest
        elif status == "out_for_delivery":
            current = dest
        elif status == "at_hub":
            # Most likely at Memphis hub for through-Memphis routes
            current = RNG.choice(HUB_CODES)
        else:  # in_transit
            current = RNG.choice(FACILITY_CODES)

        # SLA: 12-48h from now depending on priority
        if priority == "healthcare":
            sla_hours = RNG.uniform(8, 18)
        elif priority == "critical":
            sla_hours = RNG.uniform(10, 24)
        elif priority == "express":
            sla_hours = RNG.uniform(18, 36)
        else:
            sla_hours = RNG.uniform(24, 48)

        sla_deadline = now + timedelta(hours=sla_hours)

        # Estimated arrival: usually before SLA, sometimes after
        eta_offset = RNG.gauss(-2, 4)  # hours before SLA
        estimated_arrival = sla_deadline + timedelta(hours=eta_offset)

        actual_arrival = None
        if status == "delivered":
            # Delivered: actual is in the past
            actual_arrival = now - timedelta(hours=RNG.uniform(0.5, 12))

        cust_name = _customer_name(i)
        cust_id = f"C{RNG.randint(100000, 999999)}"
        cust_email = _customer_email(cust_name)

        weight = round(RNG.uniform(0.3, 65.0), 2)
        value = RNG.randint(500, 250000)  # cents

        # Risk score: higher if SLA is tight or priority is high
        base_risk = RNG.uniform(0, 30)
        if priority in ("healthcare", "critical"):
            base_risk += RNG.uniform(10, 40)
        if sla_hours < 16:
            base_risk += RNG.uniform(5, 20)
        risk_score = min(round(base_risk, 2), 99.99)

        created_at = now - timedelta(hours=RNG.uniform(1, 72))

        batch.append((
            tracking, origin, dest, current, priority, status,
            sla_deadline.strftime("%Y-%m-%d %H:%M:%S"),
            estimated_arrival.strftime("%Y-%m-%d %H:%M:%S"),
            actual_arrival.strftime("%Y-%m-%d %H:%M:%S") if actual_arrival else None,
            cust_id, cust_name, cust_email,
            weight, value, risk_score,
            created_at.strftime("%Y-%m-%d %H:%M:%S"),
        ))

        if len(batch) >= batch_size:
            _insert_shipment_batch(cur, batch)
            batch = []

    if batch:
        _insert_shipment_batch(cur, batch)

    conn.commit()
    print(f"[seed]   -> {count} shipments inserted.")


def _insert_shipment_batch(cur, batch):
    sql = """
        INSERT INTO shipments
            (tracking_number, origin_facility, destination_facility, current_facility,
             priority, status, sla_deadline, estimated_arrival, actual_arrival,
             customer_id, customer_name, customer_email,
             package_weight_lbs, declared_value_cents, risk_score, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    cur.executemany(sql, batch)


def seed_disruption_history(conn, count: int = 50):
    """Insert 50 historical disruption records with embeddings."""
    print(f"[seed] Generating {count} historical disruption records...")
    cur = conn.cursor()
    cur.execute("DELETE FROM disruption_history")
    conn.commit()

    alt_hubs = ["SDF", "IND", "OAK", "EWR", "DFW", "ORD"]

    batch = []
    for i in range(count):
        d_type = RNG.choice(DISRUPTION_TYPES)
        facility = RNG.choice(FACILITY_CODES)
        w_type = RNG.choice(WEATHER_TYPES) if d_type == "weather" else None
        severity = RNG.choice(SEVERITY_LEVELS)
        month = RNG.randint(1, 12)
        shipments = RNG.randint(50, 3000)
        delay = round(RNG.uniform(1.0, 18.0), 1)
        action = RNG.choice(RESOLUTION_ACTIONS)
        cost = RNG.randint(5000_00, 500_000_00)   # cents
        savings = RNG.randint(10000_00, 2_000_000_00)  # cents

        # Build outcome description
        template = RNG.choice(OUTCOME_TEMPLATES)
        alt = RNG.choice(alt_hubs)
        alt2 = RNG.choice([h for h in alt_hubs if h != alt])
        outcome = template.format(
            n=shipments, alt=alt, alt2=alt2, fac=facility,
            pct=RNG.randint(82, 99), hrs=delay,
            cost=round(cost / 100_000, 1),
        )

        embedding = _random_embedding(1536)

        batch.append((
            d_type, facility, w_type, severity, month,
            shipments, delay, action, cost, savings, outcome, embedding,
        ))

    sql = """
        INSERT INTO disruption_history
            (disruption_type, affected_facility, weather_type, severity,
             month_of_year, shipments_affected, delay_hours, resolution_action,
             cost_cents, savings_cents, outcome_description, embedding)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    cur.executemany(sql, batch)
    conn.commit()
    print(f"[seed]   -> {count} disruption history records inserted.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_seed():
    """Full seed: facilities -> shipments -> disruption history."""
    print("=" * 60)
    print("NERVE Data Seeder")
    print("=" * 60)
    conn = get_connection()
    try:
        seed_facilities(conn)
        seed_shipments(conn, count=10_000)
        seed_disruption_history(conn, count=50)
        print("=" * 60)
        print("[seed] Done. Database is ready for demo.")
        print("=" * 60)
    finally:
        conn.close()


if __name__ == "__main__":
    run_seed()
