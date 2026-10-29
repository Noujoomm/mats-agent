# -*- coding: utf-8 -*-
"""
Generate the fully fictional "MATS Demo Campaign" SQLite database.

Deterministic (fixed seed). No real pilgrim data: every name is built from
invented family names that literally mean "demo / sample / fictional" in
Arabic, phones use the reserved-looking +966-500-555-xxxx pattern, and bus
plates start with DEMO / تجربة.

The clock is frozen at SIMULATED_NOW, in the middle of the Mina -> Arafat
movement, so groups are in different trip states (arrived, departed,
boarding, delayed, scheduled) and 7 pilgrims are missing.

Usage:  python data/generate_mock_data.py [output_path]
"""
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

SEED = 1447
ROOT = Path(__file__).resolve().parent
DEFAULT_PATH = ROOT / "mats_demo.db"

CAMPAIGN_AR = "حملة ماتس التجريبية"
CAMPAIGN_EN = "MATS Demo Campaign"
SIMULATED_NOW = datetime(2026, 5, 26, 8, 40)          # 9 Dhul-Hijjah (fictional timeline)
DAY8 = datetime(2026, 5, 25)
DAY9 = datetime(2026, 5, 26)

N_GROUPS = 20
PILGRIMS_PER_GROUP = 100
BUSES_PER_GROUP = 2
N_MISSING = 7

NATIONALITIES = [
    ("SA", "سعودي", "Saudi"),
    ("EG", "مصري", "Egyptian"),
    ("PK", "باكستاني", "Pakistani"),
    ("ID", "إندونيسي", "Indonesian"),
    ("IN", "هندي", "Indian"),
    ("NG", "نيجيري", "Nigerian"),
    ("TR", "تركي", "Turkish"),
    ("BD", "بنغلاديشي", "Bangladeshi"),
]

FIRST_M = [("أحمد", "Ahmed"), ("محمد", "Mohammed"), ("عبدالله", "Abdullah"),
           ("خالد", "Khalid"), ("يوسف", "Yousef"), ("إبراهيم", "Ibrahim"),
           ("عمر", "Omar"), ("حسن", "Hassan"), ("سعيد", "Saeed"),
           ("فيصل", "Faisal"), ("مصطفى", "Mustafa"), ("علي", "Ali")]
FIRST_F = [("فاطمة", "Fatimah"), ("عائشة", "Aisha"), ("مريم", "Maryam"),
           ("نورة", "Noura"), ("خديجة", "Khadijah"), ("زينب", "Zainab"),
           ("سارة", "Sarah"), ("هدى", "Huda"), ("أسماء", "Asma"), ("ليلى", "Layla")]
# Invented family names that mean "demo", "sample", "fictional", "virtual"...
FAMILY = [("التجريبي", "Al-Tajribi"), ("الوهمي", "Al-Wahmi"),
          ("الافتراضي", "Al-Iftiradi"), ("النموذجي", "Al-Namoothaji"),
          ("المثالي", "Al-Mithali"), ("العيّني", "Al-Ayyini"),
          ("الاختباري", "Al-Ikhtibari"), ("التمثيلي", "Al-Tamthili")]

ROUTES = [  # code, ar, en, from_ar, from_en, to_ar, to_en, day, first departure hour
    ("MAK-MNA", "مكة ← منى", "Makkah → Mina", "مكة", "Makkah", "منى", "Mina", DAY8, 7),
    ("MNA-ARF", "منى ← عرفات", "Mina → Arafat", "منى", "Mina", "عرفات", "Arafat", DAY9, 7),
    ("ARF-MUZ", "عرفات ← مزدلفة", "Arafat → Muzdalifah", "عرفات", "Arafat", "مزدلفة", "Muzdalifah", DAY9, 19),
    ("MUZ-MNA", "مزدلفة ← منى", "Muzdalifah → Mina", "مزدلفة", "Muzdalifah", "منى", "Mina", DAY9, 23),
]

TRIP_STATUSES = [
    ("scheduled", "مجدولة", "Scheduled"),
    ("boarding", "جاري الصعود", "Boarding"),
    ("departed", "انطلقت", "Departed"),
    ("arrived", "وصلت", "Arrived"),
    ("delayed", "متأخرة", "Delayed"),
]

INCIDENT_TYPES = [
    ("lost_person", "حاج مفقود", "Lost person"),
    ("lost_item", "مفقودات", "Lost item"),
    ("medical_assist", "مساعدة طبية", "Medical assistance"),
    ("bus_delay", "تأخر باص", "Bus delay"),
    ("complaint", "شكوى", "Complaint"),
]

# Mina -> Arafat state per group number, frozen at SIMULATED_NOW (08:40)
MNA_ARF_STATE = {}
for g in range(1, 21):
    MNA_ARF_STATE[g] = ("arrived" if g <= 5 else "departed" if g <= 9 else
                        "boarding" if g <= 13 else "delayed" if g <= 16 else
                        "scheduled")

SCHEMA = """
CREATE TABLE campaign (
    id INTEGER PRIMARY KEY, name_ar TEXT, name_en TEXT,
    season_hijri INTEGER, simulated_now TEXT, note_en TEXT);
CREATE TABLE nationalities (
    id INTEGER PRIMARY KEY, code TEXT UNIQUE, name_ar TEXT, name_en TEXT);
CREATE TABLE supervisors (
    id INTEGER PRIMARY KEY, name_ar TEXT, name_en TEXT,
    role TEXT, role_ar TEXT, role_en TEXT, phone TEXT);
CREATE TABLE camps (
    id INTEGER PRIMARY KEY, code TEXT UNIQUE, site TEXT,
    site_ar TEXT, site_en TEXT, name_ar TEXT, name_en TEXT, capacity INTEGER);
CREATE TABLE groups (
    id INTEGER PRIMARY KEY, group_no INTEGER UNIQUE, name_ar TEXT, name_en TEXT,
    supervisor_id INTEGER REFERENCES supervisors(id),
    mina_camp_id INTEGER REFERENCES camps(id),
    arafat_camp_id INTEGER REFERENCES camps(id));
CREATE TABLE pilgrims (
    id INTEGER PRIMARY KEY, pilgrim_no TEXT UNIQUE, name_ar TEXT, name_en TEXT,
    gender TEXT, age INTEGER,
    nationality_id INTEGER REFERENCES nationalities(id),
    group_id INTEGER REFERENCES groups(id),
    phone TEXT, needs_wheelchair INTEGER,
    status TEXT);               -- active | missing
CREATE TABLE buses (
    id INTEGER PRIMARY KEY, bus_no INTEGER UNIQUE, plate TEXT, capacity INTEGER,
    group_id INTEGER REFERENCES groups(id),
    driver_name_ar TEXT, driver_name_en TEXT, driver_phone TEXT);
CREATE TABLE routes (
    id INTEGER PRIMARY KEY, code TEXT UNIQUE, seq INTEGER,
    route_ar TEXT, route_en TEXT,
    from_ar TEXT, from_en TEXT, to_ar TEXT, to_en TEXT);
CREATE TABLE trip_statuses (
    code TEXT PRIMARY KEY, label_ar TEXT, label_en TEXT);
CREATE TABLE trips (
    id INTEGER PRIMARY KEY,
    group_id INTEGER REFERENCES groups(id),
    bus_id INTEGER REFERENCES buses(id),
    route_id INTEGER REFERENCES routes(id),
    status TEXT REFERENCES trip_statuses(code),
    scheduled_departure TEXT, actual_departure TEXT,
    eta TEXT, arrived_at TEXT, delay_minutes INTEGER,
    expected_passengers INTEGER);
CREATE TABLE boarding_scans (
    id INTEGER PRIMARY KEY,
    trip_id INTEGER REFERENCES trips(id),
    pilgrim_id INTEGER REFERENCES pilgrims(id),
    scanned_at TEXT);
CREATE TABLE incident_types (
    code TEXT PRIMARY KEY, label_ar TEXT, label_en TEXT);
CREATE TABLE incidents (
    id INTEGER PRIMARY KEY,
    type TEXT REFERENCES incident_types(code),
    group_id INTEGER REFERENCES groups(id),
    pilgrim_id INTEGER REFERENCES pilgrims(id),
    trip_id INTEGER REFERENCES trips(id),
    reported_at TEXT, status TEXT,       -- open | resolved
    severity TEXT,                       -- low | medium | high
    location_ar TEXT, location_en TEXT,
    description_ar TEXT, description_en TEXT);
CREATE INDEX ix_pilgrims_group ON pilgrims(group_id);
CREATE INDEX ix_scans_trip ON boarding_scans(trip_id);
CREATE INDEX ix_scans_pilgrim ON boarding_scans(pilgrim_id);
CREATE INDEX ix_trips_group ON trips(group_id);
"""

AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M") if dt else None


def fake_phone(n):
    return f"+966-500-555-{n:04d}"


def build(path=DEFAULT_PATH):
    rnd = random.Random(SEED)
    path = Path(path)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    ins = lambda table, rows: conn.executemany(  # noqa: E731
        f"INSERT INTO {table} VALUES ({','.join('?' * len(rows[0]))})", rows)

    ins("campaign", [(1, CAMPAIGN_AR, CAMPAIGN_EN, 1447, ts(SIMULATED_NOW),
                      "All data is fictional and generated for demo purposes.")])
    ins("nationalities", [(i + 1, c, ar, en) for i, (c, ar, en) in enumerate(NATIONALITIES)])
    ins("trip_statuses", TRIP_STATUSES)
    ins("incident_types", INCIDENT_TYPES)

    # Supervisors: one per group + 4 field/medical leads
    sups, phone_n = [], 1
    for g in range(1, N_GROUPS + 1):
        (fa, fe), (la, le) = rnd.choice(FIRST_M), rnd.choice(FAMILY)
        sups.append((g, f"{fa} {la}", f"{fe} {le}", "group_leader",
                     "مشرف فوج", "Group supervisor", fake_phone(phone_n)))
        phone_n += 1
    for i, (role, ra, re_) in enumerate([
            ("field_lead", "مشرف ميداني", "Field supervisor"),
            ("field_lead", "مشرف ميداني", "Field supervisor"),
            ("medical_lead", "مشرف طبي", "Medical supervisor"),
            ("transport_lead", "مشرف نقل", "Transport supervisor")]):
        (fa, fe), (la, le) = rnd.choice(FIRST_M), rnd.choice(FAMILY)
        sups.append((N_GROUPS + i + 1, f"{fa} {la}", f"{fe} {le}", role, ra, re_,
                     fake_phone(phone_n)))
        phone_n += 1
    ins("supervisors", sups)

    # Camps: 5 in Mina, 5 in Arafat, 4 groups share each camp
    camps = []
    for i in range(5):
        camps.append((i + 1, f"MNA-{i + 1:02d}", "mina", "منى", "Mina",
                      f"مخيم منى {str(i + 1).translate(AR_DIGITS)}", f"Mina Camp {i + 1}", 450))
    for i in range(5):
        camps.append((i + 6, f"ARF-{i + 1:02d}", "arafat", "عرفات", "Arafat",
                      f"مخيم عرفات {str(i + 1).translate(AR_DIGITS)}", f"Arafat Camp {i + 1}", 450))
    ins("camps", camps)

    groups = []
    for g in range(1, N_GROUPS + 1):
        c = (g - 1) // 4
        groups.append((g, g, f"الفوج {str(g).translate(AR_DIGITS)}", f"Group {g}",
                       g, c + 1, c + 6))
    ins("groups", groups)

    # Pilgrims
    pilgrims = []
    pid = 0
    for g in range(1, N_GROUPS + 1):
        base_nat = (g - 1) % len(NATIONALITIES) + 1
        for _ in range(PILGRIMS_PER_GROUP):
            pid += 1
            female = rnd.random() < 0.45
            fa, fe = rnd.choice(FIRST_F if female else FIRST_M)
            pa, pe = rnd.choice(FIRST_M)
            la, le = rnd.choice(FAMILY)
            nat = base_nat if rnd.random() < 0.7 else rnd.randint(1, len(NATIONALITIES))
            age = rnd.randint(22, 84)
            pilgrims.append([
                pid, f"P-{pid:05d}", f"{fa} {pa} {la}", f"{fe} {pe} {le}",
                "F" if female else "M", age, nat, g, fake_phone(1000 + pid),
                1 if (age > 70 and rnd.random() < 0.35) else 0, "active"])

    # 7 missing pilgrims, all in groups whose Mina->Arafat bus already left
    left_groups = [g for g, s in MNA_ARF_STATE.items() if s in ("arrived", "departed")]
    missing_groups = rnd.sample(left_groups, N_MISSING)
    missing_ids = set()
    for g in missing_groups:
        candidates = [p for p in pilgrims if p[7] == g]
        p = rnd.choice(candidates)
        p[10] = "missing"
        missing_ids.add(p[0])
    ins("pilgrims", [tuple(p) for p in pilgrims])

    # Buses: 2 per group
    buses, bus_id = [], 0
    for g in range(1, N_GROUPS + 1):
        for _ in range(BUSES_PER_GROUP):
            bus_id += 1
            (fa, fe), (la, le) = rnd.choice(FIRST_M), rnd.choice(FAMILY)
            n = 1000 + bus_id * 7
            buses.append((bus_id, 100 + bus_id,
                          f"DEMO {n} | تجربة {str(n).translate(AR_DIGITS)}", 55, g,
                          f"{fa} {la}", f"{fe} {le}", fake_phone(5000 + bus_id)))
    ins("buses", buses)

    ins("routes", [(i + 1, r[0], i + 1, r[1], r[2], r[3], r[4], r[5], r[6])
                   for i, r in enumerate(ROUTES)])

    # Trips: every group x every route x each of its 2 buses
    trips, scans, trip_id, scan_id = [], [], 0, 0
    by_group = {g: [p for p in pilgrims if p[7] == g] for g in range(1, N_GROUPS + 1)}
    for r_idx, r in enumerate(ROUTES):
        route_id, day, hour = r_idx + 1, r[7], r[8]
        for g in range(1, N_GROUPS + 1):
            members = by_group[g]
            halves = [members[:50], members[50:]]
            for b in range(BUSES_PER_GROUP):
                trip_id += 1
                bus = (g - 1) * BUSES_PER_GROUP + b + 1
                sched = day + timedelta(hours=hour, minutes=((g - 1) // 2) * 12 + b * 5)
                if route_id == 1:
                    status = "arrived"
                elif route_id == 2:
                    status = MNA_ARF_STATE[g]
                else:
                    status = "scheduled"
                travel = timedelta(minutes=rnd.randint(55, 85))
                actual = eta = arrived = None
                delay = 0
                if status == "arrived":
                    actual = sched + timedelta(minutes=rnd.randint(0, 10))
                    arrived = actual + travel
                elif status == "departed":
                    actual = sched + timedelta(minutes=rnd.randint(0, 12))
                    eta = actual + travel
                elif status == "delayed":
                    delay = rnd.randint(25, 70)
                    eta = sched + timedelta(minutes=delay) + travel
                elif status in ("boarding", "scheduled"):
                    eta = sched + travel
                trips.append((trip_id, g, bus, route_id, status, ts(sched), ts(actual),
                              ts(eta), ts(arrived), delay, len(halves[b])))

                # Boarding scans
                if status in ("arrived", "departed"):
                    riders = [p for p in halves[b]
                              if not (route_id == 2 and p[0] in missing_ids)]
                elif status == "boarding":
                    riders = halves[b][: rnd.randint(18, 40)]
                else:
                    riders = []
                for p in riders:
                    scan_id += 1
                    t = sched - timedelta(minutes=rnd.randint(1, 25))
                    if status == "boarding":
                        t = min(t, SIMULATED_NOW - timedelta(minutes=rnd.randint(0, 10)))
                    scans.append((scan_id, trip_id, p[0], ts(t)))
    ins("trips", trips)
    ins("boarding_scans", scans)

    # Incidents
    inc, iid = [], 0
    trip_of = {(t[1], t[3], t[2]): t[0] for t in trips}
    for p in pilgrims:
        if p[0] in missing_ids:
            iid += 1
            g = p[7]
            bus = (g - 1) * BUSES_PER_GROUP + (1 if p in by_group[g][:50] else 2)
            when = SIMULATED_NOW - timedelta(minutes=rnd.randint(10, 80))
            inc.append((iid, "lost_person", g, p[0], trip_of[(g, 2, bus)], ts(when),
                        "open", "high", "منى", "Mina",
                        "لم يُسجَّل صعوده لباص منى ← عرفات ولا يرد على الجوال",
                        "Not scanned onto the Mina → Arafat bus and not answering phone"))
    for g in range(14, 17):  # delayed groups
        iid += 1
        bus = (g - 1) * BUSES_PER_GROUP + 1
        inc.append((iid, "bus_delay", g, None, trip_of[(g, 2, bus)],
                    ts(SIMULATED_NOW - timedelta(minutes=rnd.randint(5, 30))),
                    "open", "medium", "منى", "Mina",
                    "الباص عالق في الزحام عند مخرج منى",
                    "Bus stuck in traffic at the Mina exit"))
    extras = [
        ("lost_item", "low", "منى", "Mina", "شنطة يد سوداء مفقودة", "Black handbag lost"),
        ("lost_item", "low", "عرفات", "Arafat", "جوال مفقود", "Lost mobile phone"),
        ("lost_item", "low", "منى", "Mina", "محفظة فيها أوراق", "Wallet with documents"),
        ("medical_assist", "high", "عرفات", "Arafat", "إجهاد حراري", "Heat exhaustion"),
        ("medical_assist", "medium", "منى", "Mina", "دوخة وارتفاع ضغط", "Dizziness and high blood pressure"),
        ("medical_assist", "medium", "منى", "Mina", "يحتاج كرسي متحرك", "Needs a wheelchair"),
        ("medical_assist", "low", "عرفات", "Arafat", "جرح بسيط في القدم", "Minor foot cut"),
        ("complaint", "low", "منى", "Mina", "التكييف ضعيف في الخيمة", "Weak air conditioning in the tent"),
        ("complaint", "medium", "منى", "Mina", "تأخر توزيع الوجبات", "Late meal distribution"),
        ("complaint", "low", "عرفات", "Arafat", "نقص في المياه الباردة", "Shortage of cold water"),
    ]
    for _ in range(3):
        for typ, sev, la, le, da, de in extras:
            iid += 1
            g = rnd.randint(1, N_GROUPS)
            p = rnd.choice(by_group[g])[0] if typ != "complaint" else None
            when = SIMULATED_NOW - timedelta(minutes=rnd.randint(20, 26 * 60))
            status = "resolved" if rnd.random() < 0.6 else "open"
            inc.append((iid, typ, g, p, None, ts(when), status, sev, la, le, da, de))
    ins("incidents", inc)

    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    return path


if __name__ == "__main__":
    out = build(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH)
    print(f"MATS Demo Campaign database written to {out}")
