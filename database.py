"""
Rural Navi — Database Engine & Migration Module
------------------------------------------------
Provides SQLite persistence, village-ward-house hierarchies,
confidence scoring, audit logging, and automated migration from houses.xlsx.
"""

import sqlite3
import os
import secrets
import openpyxl
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "rural_navi.db")
EXCEL_PATH = os.path.join(os.path.dirname(__file__), "houses.xlsx")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def calculate_confidence(status, source, gps_accuracy, confirmations_count=0):
    """
    Computes an objective, reproducible confidence score (0 to 100)
    and categorical tier: HIGH, MEDIUM, LOW, DISPUTED.
    Based on three verifiable factors:
    1. Ground-Truth Authority (Panchayat verified = 40 pts, field survey = 25, citizen = 10)
    2. Precision / Spatial Radius (<5m = 35 pts, 5-15m = 25 pts, >15m = 10 pts)
    3. Independent Multi-Party Confirmations (up to 25 pts, 5 pts per confirmation)
    """
    score = 0

    # 1. Source Authority
    if source == "panchayat_survey" or status == "verified":
        score += 40
    elif source == "field_worker" or status == "community_confirmed":
        score += 25
    elif source == "citizen_submission":
        score += 10
    else:
        score += 5

    # 2. GPS Accuracy (in meters)
    try:
        acc = float(gps_accuracy)
        if acc <= 5.0:
            score += 35
        elif acc <= 15.0:
            score += 25
        elif acc <= 30.0:
            score += 15
        else:
            score += 5
    except (ValueError, TypeError):
        score += 15

    # 3. Confirmations
    conf_pts = min(25, int(confirmations_count) * 5)
    score += conf_pts

    # Disputed check
    if status == "disputed":
        return min(score, 30), "DISPUTED"

    if score >= 75:
        tier = "HIGH"
    elif score >= 50:
        tier = "MEDIUM"
    else:
        tier = "LOW"

    return score, tier


def normalize_house_no(raw_no):
    """
    Normalizes house numbers for robust search:
    - Strips spaces and leading zeros
    - Handles '-', '–' (en-dash), '—' (em-dash), '/' consistently
    - Treats house numbers as text without numeric/date coercion
    """
    if not raw_no:
        return ""
    s = str(raw_no).strip().upper()
    # Normalize unicode hyphens and slashes
    s = s.replace("–", "-").replace("—", "-").replace("−", "-").replace("/", "-").replace(" ", "")
    # Remove leading zeros in ward-door parts if present (e.g. 03-081 -> 3-81)
    parts = s.split("-")
    norm_parts = []
    for p in parts:
        stripped = p.lstrip("0")
        norm_parts.append(stripped if stripped else "0")
    return "-".join(norm_parts)


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Villages table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS villages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        name_ta TEXT,
        block TEXT,
        district TEXT DEFAULT 'Madurai',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Houses table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS houses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        village_id INTEGER NOT NULL,
        ward_no TEXT DEFAULT '1',
        house_no TEXT NOT NULL,
        normalized_no TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        landmark TEXT,
        status TEXT DEFAULT 'verified',
        verification_source TEXT DEFAULT 'panchayat_survey',
        gps_accuracy REAL DEFAULT 3.5,
        confidence_score INTEGER DEFAULT 85,
        confidence_tier TEXT DEFAULT 'HIGH',
        confirmations_count INTEGER DEFAULT 1,
        has_physical_qr INTEGER DEFAULT 1,
        nav_token TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(village_id) REFERENCES villages(id) ON DELETE CASCADE,
        UNIQUE(village_id, normalized_no)
    )
    """)

    # Corrections / Reports table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        house_id INTEGER,
        report_type TEXT NOT NULL, -- 'incorrect_location', 'missing_door_plate', 'unserviceable_road', 'other'
        reporter_role TEXT NOT NULL, -- 'delivery', 'resident', 'field_worker', 'kiosk'
        proposed_lat REAL,
        proposed_lng REAL,
        description TEXT NOT NULL,
        status TEXT DEFAULT 'pending', -- 'pending', 'approved', 'rejected'
        admin_notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        resolved_at TIMESTAMP,
        FOREIGN KEY(house_id) REFERENCES houses(id) ON DELETE SET NULL
    )
    """)

    # Audit Log table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id INTEGER,
        details TEXT NOT NULL,
        performed_by TEXT DEFAULT 'system',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()

    # Pre-populate sample village if empty
    cursor.execute("SELECT COUNT(*) FROM villages")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO villages (name, name_ta, block, district) VALUES
        ('Alanganallur', 'அலங்காநல்லூர்', 'Alanganallur Block', 'Madurai'),
        ('Vadipatti', 'வாடிப்பட்டி', 'Vadipatti Block', 'Madurai'),
        ('Palamedu', 'பாலமேடு', 'Alanganallur Block', 'Madurai')
        """)
        conn.commit()

    # Migrate from houses.xlsx if houses table is empty
    cursor.execute("SELECT COUNT(*) FROM houses")
    if cursor.fetchone()[0] == 0 and os.path.exists(EXCEL_PATH):
        try:
            wb = openpyxl.load_workbook(EXCEL_PATH)
            sheet = wb.active
            rows = list(sheet.iter_rows(values_only=True))
            if rows and len(rows) > 1:
                # get Alanganallur village id
                cursor.execute("SELECT id FROM villages WHERE name = 'Alanganallur'")
                v_id = cursor.fetchone()[0]

                for row in rows[1:]:
                    if not row or row[0] is None:
                        continue
                    h_no = str(row[0]).strip()
                    try:
                        lat = float(row[1])
                        lng = float(row[2])
                    except (ValueError, TypeError):
                        continue
                    note = str(row[3]) if len(row) > 3 and row[3] else "Panchayat surveyed residential structure"
                    norm = normalize_house_no(h_no)
                    token = secrets.token_urlsafe(8)

                    score, tier = calculate_confidence("verified", "panchayat_survey", 3.2, 1)

                    cursor.execute("""
                    INSERT OR IGNORE INTO houses 
                    (village_id, ward_no, house_no, normalized_no, latitude, longitude, landmark, status, verification_source, gps_accuracy, confidence_score, confidence_tier, confirmations_count, nav_token)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (v_id, "1", h_no, norm, lat, lng, note, "verified", "panchayat_survey", 3.2, score, tier, 1, token))

                cursor.execute("""
                INSERT INTO audit_logs (action, entity_type, details, performed_by)
                VALUES ('MIGRATE', 'houses', 'Imported initial seed records from houses.xlsx into SQLite', 'system')
                """)
                conn.commit()
        except Exception as e:
            print("Migration warning:", e)

    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at:", DB_PATH)
