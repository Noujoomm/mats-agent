"""Schema description given to the SQL models (kept short: every token costs latency)."""

SCHEMA_DOC = """SQLite database of the fictional "MATS Demo Campaign" (Hajj operations).

campaign(id, name_ar, name_en, season_hijri, simulated_now)   -- one row; simulated_now is "now"
nationalities(id, code, name_ar, name_en)
supervisors(id, name_ar, name_en, role, role_ar, role_en, phone)
    role: group_leader | field_lead | medical_lead | transport_lead
camps(id, code, site, site_ar, site_en, name_ar, name_en, capacity)   -- site: 'mina' | 'arafat'
groups(id, group_no, name_ar, name_en, supervisor_id, mina_camp_id, arafat_camp_id)
    -- "فوج 5" / "group 5" means groups.group_no = 5 (20 groups)
pilgrims(id, pilgrim_no, name_ar, name_en, gender 'M'|'F', age, nationality_id, group_id,
         phone, needs_wheelchair 0|1, status 'active'|'missing')
buses(id, bus_no, plate, capacity, group_id, driver_name_ar, driver_name_en, driver_phone)
routes(id, code, seq, route_ar, route_en, from_ar, from_en, to_ar, to_en)
    codes: 'MAK-MNA' Makkah→Mina, 'MNA-ARF' Mina→Arafat, 'ARF-MUZ' Arafat→Muzdalifah,
           'MUZ-MNA' Muzdalifah→Mina
trip_statuses(code, label_ar, label_en)   -- scheduled | boarding | departed | arrived | delayed
trips(id, group_id, bus_id, route_id, status, scheduled_departure, actual_departure,
      eta, arrived_at, delay_minutes, expected_passengers)
    -- each group has 2 buses, so 2 trips per route; times are 'YYYY-MM-DD HH:MM'
boarding_scans(id, trip_id, pilgrim_id, scanned_at)   -- a scan = the pilgrim boarded that trip
incident_types(code, label_ar, label_en)
    -- lost_person | lost_item | medical_assist | bus_delay | complaint
incidents(id, type, group_id, pilgrim_id, trip_id, reported_at, status 'open'|'resolved',
          severity 'low'|'medium'|'high', location_ar, location_en, description_ar, description_en)

Rules:
- "Not boarded" on a route = pilgrim of a group whose trip on that route is departed/arrived
  with no boarding_scans row on any trip of that route.
- "Still in Mina" during the Mina→Arafat movement = groups whose MNA-ARF trips are NOT
  departed/arrived (i.e. scheduled, boarding or delayed).
- Join trip_statuses / incident_types to show bilingual labels.
- Return both name_ar and name_en (or route_ar and route_en) when listing names.
- Arabic text matching: WHERE norm(name_ar) LIKE '%' || norm('text') || '%'.
- Use COUNT(DISTINCT p.id) when joins can duplicate pilgrims (2 trips per group).
"""
