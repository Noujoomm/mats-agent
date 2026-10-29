import re
import sqlite3

import pytest


@pytest.fixture(scope="module")
def db(db_path):
    c = sqlite3.connect(db_path)
    yield c
    c.close()


def one(db, sql):
    return db.execute(sql).fetchone()[0]


def test_counts(db):
    assert one(db, "SELECT COUNT(*) FROM groups") == 20
    assert one(db, "SELECT COUNT(*) FROM pilgrims") == 2000
    assert one(db, "SELECT COUNT(*) FROM nationalities") == 8
    assert one(db, "SELECT COUNT(*) FROM buses") == 40
    assert one(db, "SELECT COUNT(*) FROM routes") == 4
    assert one(db, "SELECT COUNT(*) FROM supervisors") >= 20
    assert one(db, "SELECT COUNT(*) FROM camps WHERE site = 'mina'") > 0
    assert one(db, "SELECT COUNT(*) FROM camps WHERE site = 'arafat'") > 0
    assert one(db, "SELECT COUNT(*) FROM boarding_scans") > 0


def test_campaign_and_simulated_now(db):
    name, now = db.execute("SELECT name_en, simulated_now FROM campaign").fetchone()
    assert name == "MATS Demo Campaign" and now.startswith("2026-05-26")


def test_mina_arafat_states_differ_across_groups(db):
    states = {r[0] for r in db.execute(
        "SELECT t.status FROM trips t JOIN routes r ON r.id = t.route_id WHERE r.code = 'MNA-ARF'")}
    assert states == {"arrived", "departed", "boarding", "delayed", "scheduled"}


def test_missing_pilgrims_and_incident_types(db):
    assert one(db, "SELECT COUNT(*) FROM pilgrims WHERE status = 'missing'") == 7
    types = {r[0] for r in db.execute("SELECT DISTINCT type FROM incidents")}
    assert types == {"lost_person", "lost_item", "medical_assist", "bus_delay", "complaint"}


@pytest.mark.parametrize("table,cols", [
    ("pilgrims", ["name_ar", "name_en"]), ("groups", ["name_ar", "name_en"]),
    ("routes", ["route_ar", "route_en"]), ("camps", ["name_ar", "name_en"]),
    ("nationalities", ["name_ar", "name_en"]), ("supervisors", ["name_ar", "name_en"]),
    ("trip_statuses", ["label_ar", "label_en"]), ("incident_types", ["label_ar", "label_en"]),
    ("incidents", ["description_ar", "description_en"]),
])
def test_bilingual_columns(db, table, cols):
    have = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
    assert set(cols) <= have


def test_data_is_clearly_fake(db):
    phones = [r[0] for r in db.execute(
        "SELECT phone FROM pilgrims UNION ALL SELECT phone FROM supervisors "
        "UNION ALL SELECT driver_phone FROM buses")]
    assert all(re.fullmatch(r"\+966-500-555-\d{4}", p) for p in phones)
    assert all(p.startswith("DEMO ") for (p,) in db.execute("SELECT plate FROM buses"))
    fake_families = ("Al-Tajribi", "Al-Wahmi", "Al-Iftiradi", "Al-Namoothaji", "Al-Mithali",
                     "Al-Ayyini", "Al-Ikhtibari", "Al-Tamthili")
    assert all(n.endswith(fake_families) for (n,) in db.execute("SELECT name_en FROM pilgrims"))


def test_deterministic(tmp_path, db):
    from data.generate_mock_data import build
    other = sqlite3.connect(build(tmp_path / "again.db"))
    q = "SELECT group_concat(name_en || status, ',') FROM pilgrims"
    assert other.execute(q).fetchone()[0] == db.execute(q).fetchone()[0]
    other.close()
