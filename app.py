"""
Rural Navi — Upgraded Backend Server
-------------------------------------
RESTful APIs, multi-stakeholder workflows, multi-factor address disambiguation,
evidence-based verification, safe corrections, audit logging, and PWA support.
"""

from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import sqlite3
import os
import secrets
import csv
import io
from datetime import datetime

from database import get_db, normalize_house_no, calculate_confidence, init_db

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "rural_navi_civic_secret_2026")

# Ensure DB is created
init_db()


# ---------------------------------------------------------------------
# FRONTEND ROUTES
# ---------------------------------------------------------------------

@app.route("/")
def home():
    """Touchscreen Kiosk as primary interface."""
    return render_template("kiosk.html")


@app.route("/classic")
def classic_mode():
    """Classic multi-stakeholder interface fallback."""
    return render_template("index.html")


@app.route("/delivery")
def delivery_mode():
    """Delivery Personnel & Field Worker Workflow."""
    return render_template("index.html", initial_mode="delivery")


@app.route("/resident")
def resident_mode():
    """Rural Resident Self-Service Portal."""
    return render_template("index.html", initial_mode="resident")


@app.route("/field")
def field_mode():
    """Healthcare & ASHA Field Emergency Search Workflow."""
    return render_template("index.html", initial_mode="field")


@app.route("/kiosk")
def kiosk_mode():
    """Simplified Touchscreen Public Kiosk Interface."""
    return render_template("kiosk.html")


@app.route("/admin")
def admin_page():
    """Panchayat Administrative Verification & Audit Portal."""
    return render_template("admin.html")


@app.route("/nav/<token>")
def nav_redirect(token):
    """
    Privacy-Preserving Dynamic Navigation Route:
    Resolves an opaque token to verified coordinates and redirects
    to open map navigation without exposing resident identity.
    """
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    SELECT h.*, v.name as village_name FROM houses h 
    JOIN villages v ON h.village_id = v.id 
    WHERE h.nav_token = ?
    """, (token,))
    row = c.fetchone()
    conn.close()

    if not row:
        return render_template("not_found.html", token=token), 404

    # Redirect to OpenStreetMap or Google Maps
    maps_url = f"https://www.google.com/maps?q={row['latitude']},{row['longitude']}"
    return redirect(maps_url)


# ---------------------------------------------------------------------
# RESTful API ENDPOINTS
# ---------------------------------------------------------------------

@app.route("/lookup")
def legacy_lookup():
    """
    Backward-compatible endpoint: GET /lookup?house=3-82&village=Alanganallur
    Used by existing scripts and automated queries.
    """
    house_raw = request.args.get("house", "").strip()
    village_name = request.args.get("village", "").strip()

    if not house_raw:
        return jsonify({"found": False, "error": "No house number provided"}), 400

    norm = normalize_house_no(house_raw)
    conn = get_db()
    c = conn.cursor()

    query = """
    SELECT h.*, v.name as village_name, v.name_ta as village_name_ta
    FROM houses h
    JOIN villages v ON h.village_id = v.id
    WHERE h.normalized_no = ?
    """
    params = [norm]

    if village_name:
        query += " AND LOWER(v.name) = LOWER(?)"
        params.append(village_name)

    c.execute(query, params)
    rows = c.fetchall()
    conn.close()

    if not rows:
        return jsonify({"found": False, "house_no": house_raw})

    row = rows[0]
    return jsonify({
        "found": True,
        "house_no": row["house_no"],
        "village": row["village_name"],
        "ward_no": row["ward_no"],
        "lat": float(row["latitude"]),
        "lng": float(row["longitude"]),
        "note": str(row["landmark"]),
        "status": row["status"],
        "confidence_tier": row["confidence_tier"],
        "confidence_score": row["confidence_score"],
        "nav_token": row["nav_token"]
    })


@app.route("/api/villages")
def get_villages():
    """Returns list of registered administrative villages."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, name_ta, block, district FROM villages ORDER BY name ASC")
    villages = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"success": True, "villages": villages})


@app.route("/api/search")
def search_address():
    """
    Multi-Factor Ambiguity-Aware Address Search:
    Handles exact match, multiple ward matches, fuzzy formatting,
    and returns rich location confidence metadata.
    """
    raw_query = request.args.get("q", "").strip()
    village_id = request.args.get("village_id", "").strip()
    ward_no = request.args.get("ward", "").strip()

    if not raw_query:
        return jsonify({"success": False, "error": "Search query is required"}), 400

    norm_query = normalize_house_no(raw_query)
    conn = get_db()
    c = conn.cursor()

    sql = """
    SELECT h.*, v.name as village_name, v.name_ta as village_name_ta, v.district
    FROM houses h
    JOIN villages v ON h.village_id = v.id
    WHERE (h.normalized_no = ? OR h.house_no LIKE ? OR h.landmark LIKE ?)
    """
    params = [norm_query, f"%{raw_query}%", f"%{raw_query}%"]

    if village_id:
        sql += " AND h.village_id = ?"
        params.append(village_id)
    if ward_no:
        sql += " AND h.ward_no = ?"
        params.append(ward_no)

    sql += " ORDER BY h.confidence_score DESC"
    c.execute(sql, params)
    rows = c.fetchall()
    conn.close()

    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "house_no": r["house_no"],
            "normalized_no": r["normalized_no"],
            "ward_no": r["ward_no"],
            "village_id": r["village_id"],
            "village_name": r["village_name"],
            "village_name_ta": r["village_name_ta"],
            "district": r["district"],
            "lat": float(r["latitude"]),
            "lng": float(r["longitude"]),
            "landmark": r["landmark"],
            "status": r["status"],
            "source": r["verification_source"],
            "gps_accuracy": r["gps_accuracy"],
            "confidence_score": r["confidence_score"],
            "confidence_tier": r["confidence_tier"],
            "confirmations_count": r["confirmations_count"],
            "has_physical_qr": bool(r["has_physical_qr"]),
            "nav_token": r["nav_token"]
        })

    # Categorize match state
    if len(results) == 1:
        match_type = "EXACT_MATCH"
    elif len(results) > 1:
        match_type = "MULTIPLE_MATCHES"  # Ambiguity detected
    else:
        match_type = "NO_MATCH"

    return jsonify({
        "success": True,
        "query": raw_query,
        "normalized": norm_query,
        "match_type": match_type,
        "count": len(results),
        "results": results
    })


@app.route("/api/report", methods=["POST"])
def submit_report():
    """
    Allows delivery personnel or residents to submit address correction reports
    without altering official records directly.
    """
    data = request.get_json() or {}
    house_id = data.get("house_id")
    report_type = data.get("report_type", "incorrect_location")
    reporter_role = data.get("reporter_role", "delivery")
    description = data.get("description", "").strip()
    proposed_lat = data.get("proposed_lat")
    proposed_lng = data.get("proposed_lng")

    if not description:
        return jsonify({"success": False, "error": "Description is required"}), 400

    conn = get_db()
    c = conn.cursor()

    c.execute("""
    INSERT INTO reports (house_id, report_type, reporter_role, proposed_lat, proposed_lng, description, status)
    VALUES (?, ?, ?, ?, ?, ?, 'pending')
    """, (house_id, report_type, reporter_role, proposed_lat, proposed_lng, description))
    report_id = c.lastrowid

    # Add audit log
    c.execute("""
    INSERT INTO audit_logs (action, entity_type, entity_id, details, performed_by)
    VALUES ('SUBMIT_REPORT', 'reports', ?, ?, ?)
    """, (report_id, f"Type: {report_type}, Role: {reporter_role}, HouseID: {house_id}", reporter_role))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": "Report logged successfully for Panchayat administrative review.",
        "report_id": report_id
    })


# ---------------------------------------------------------------------
# PANCHAYAT ADMIN & AUDIT APIS
# ---------------------------------------------------------------------

@app.route("/api/admin/stats")
def admin_stats():
    """Overview statistics for Panchayat administration."""
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM houses")
    total_houses = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM houses WHERE status = 'verified'")
    verified_houses = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM reports WHERE status = 'pending'")
    pending_reports = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM audit_logs")
    total_logs = c.fetchone()[0]

    # Confidence distribution
    c.execute("SELECT confidence_tier, COUNT(*) FROM houses GROUP BY confidence_tier")
    tiers = {r[0]: r[1] for r in c.fetchall()}

    conn.close()
    return jsonify({
        "success": True,
        "stats": {
            "total_houses": total_houses,
            "verified_houses": verified_houses,
            "pending_reports": pending_reports,
            "total_audit_events": total_logs,
            "tiers": tiers
        }
    })


@app.route("/api/admin/reports")
def admin_reports():
    """Lists correction and issue reports."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    SELECT r.*, h.house_no, h.landmark, v.name as village_name
    FROM reports r
    LEFT JOIN houses h ON r.house_id = h.id
    LEFT JOIN villages v ON h.village_id = v.id
    ORDER BY r.created_at DESC
    """)
    reports = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"success": True, "reports": reports})


@app.route("/api/admin/reports/<int:report_id>/resolve", methods=["POST"])
def resolve_report(report_id):
    """Admin approves or rejects a reported correction."""
    data = request.get_json() or {}
    action = data.get("action")  # 'approve' or 'reject'
    admin_notes = data.get("notes", "Reviewed by Panchayat Administrator")

    if action not in ("approve", "reject"):
        return jsonify({"success": False, "error": "Invalid action"}), 400

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
    rep = c.fetchone()
    if not rep:
        conn.close()
        return jsonify({"success": False, "error": "Report not found"}), 404

    new_status = "approved" if action == "approve" else "rejected"
    c.execute("""
    UPDATE reports SET status = ?, admin_notes = ?, resolved_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (new_status, admin_notes, report_id))

    # If approved and proposed coordinates exist, update house
    if action == "approve" and rep["proposed_lat"] and rep["proposed_lng"] and rep["house_id"]:
        c.execute("""
        UPDATE houses 
        SET latitude = ?, longitude = ?, status = 'verified', 
            confirmations_count = confirmations_count + 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (rep["proposed_lat"], rep["proposed_lng"], rep["house_id"]))

    c.execute("""
    INSERT INTO audit_logs (action, entity_type, entity_id, details, performed_by)
    VALUES (?, 'reports', ?, ?, 'panchayat_admin')
    """, (f"REPORT_{action.upper()}", report_id, f"Report #{report_id} {new_status}: {admin_notes}"))

    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Report #{report_id} {new_status} successfully."})


@app.route("/api/admin/houses", methods=["GET", "POST"])
def admin_houses():
    """Fetch or insert official Panchayat house record."""
    conn = get_db()
    c = conn.cursor()

    if request.method == "POST":
        data = request.get_json() or {}
        village_id = data.get("village_id", 1)
        ward_no = data.get("ward_no", "1").strip()
        house_no = data.get("house_no", "").strip()
        lat = data.get("latitude")
        lng = data.get("longitude")
        landmark = data.get("landmark", "").strip()

        if not house_no or lat is None or lng is None:
            conn.close()
            return jsonify({"success": False, "error": "House number, lat, and lng are required"}), 400

        norm = normalize_house_no(house_no)
        token = secrets.token_urlsafe(8)
        score, tier = calculate_confidence("verified", "panchayat_survey", 3.0, 1)

        try:
            c.execute("""
            INSERT INTO houses (village_id, ward_no, house_no, normalized_no, latitude, longitude, landmark, status, verification_source, gps_accuracy, confidence_score, confidence_tier, confirmations_count, nav_token)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'verified', 'panchayat_survey', 3.0, ?, ?, 1, ?)
            """, (village_id, ward_no, house_no, norm, float(lat), float(lng), landmark, score, tier, token))
            new_id = c.lastrowid

            c.execute("""
            INSERT INTO audit_logs (action, entity_type, entity_id, details, performed_by)
            VALUES ('ADD_HOUSE', 'houses', ?, ?, 'panchayat_admin')
            """, (new_id, f"Added official house {house_no} in village {village_id}"))

            conn.commit()
            conn.close()
            return jsonify({"success": True, "message": "House added successfully", "id": new_id})
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({"success": False, "error": f"House {house_no} already exists in this village."}), 409

    # GET: return list of houses with village info
    c.execute("""
    SELECT h.*, v.name as village_name FROM houses h
    JOIN villages v ON h.village_id = v.id
    ORDER BY h.id DESC
    """)
    houses = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"success": True, "houses": houses})


@app.route("/api/admin/houses/<int:house_id>", methods=["PUT", "DELETE"])
def admin_manage_house(house_id):
    """Update or delete an existing Panchayat house record."""
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM houses WHERE id = ?", (house_id,))
    existing = c.fetchone()
    if not existing:
        conn.close()
        return jsonify({"success": False, "error": f"House #{house_id} not found"}), 404

    if request.method == "DELETE":
        house_no = existing["house_no"]
        c.execute("DELETE FROM houses WHERE id = ?", (house_id,))
        c.execute("""
        INSERT INTO audit_logs (action, entity_type, entity_id, details, performed_by)
        VALUES ('DELETE_HOUSE', 'houses', ?, ?, 'panchayat_admin')
        """, (house_id, f"Deleted house {house_no} (ID: {house_id})"))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": f"House #{house_id} ({house_no}) deleted successfully."})

    # PUT: update record
    data = request.get_json() or {}
    ward_no = data.get("ward_no", existing["ward_no"])
    house_no = data.get("house_no", existing["house_no"]).strip()
    lat = data.get("latitude", existing["latitude"])
    lng = data.get("longitude", existing["longitude"])
    landmark = data.get("landmark", existing["landmark"]).strip()
    status = data.get("status", existing["status"])

    norm = normalize_house_no(house_no)

    try:
        c.execute("""
        UPDATE houses
        SET ward_no = ?, house_no = ?, normalized_no = ?, latitude = ?, longitude = ?, landmark = ?, status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (ward_no, house_no, norm, float(lat), float(lng), landmark, status, house_id))

        c.execute("""
        INSERT INTO audit_logs (action, entity_type, entity_id, details, performed_by)
        VALUES ('UPDATE_HOUSE', 'houses', ?, ?, 'panchayat_admin')
        """, (house_id, f"Updated house {house_no}: lat={lat}, lng={lng}, ward={ward_no}"))

        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": f"House #{house_id} ({house_no}) updated successfully."})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 400



@app.route("/api/admin/audit")
def admin_audit():
    """Returns complete audit log history."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 100")
    logs = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"success": True, "logs": logs})


@app.route("/api/admin/export")
def admin_export():
    """Exports verified house records as CSV."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    SELECT h.id, v.name as village, h.ward_no, h.house_no, h.normalized_no,
           h.latitude, h.longitude, h.landmark, h.status, h.confidence_tier, h.confidence_score, h.nav_token
    FROM houses h
    JOIN villages v ON h.village_id = v.id
    ORDER BY v.name ASC, h.ward_no ASC, h.normalized_no ASC
    """)
    rows = c.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Village", "Ward", "HouseNo", "NormalizedNo", "Latitude", "Longitude", "Landmark", "Status", "ConfidenceTier", "ConfidenceScore", "NavToken"])
    for r in rows:
        writer.writerow(list(r))

    output.seek(0)
    return (
        output.getvalue(),
        200,
        {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": "attachment; filename=rural_navi_verified_records.csv"
        }
    )


# ---------------------------------------------------------------------
# MAIN RUNNER
# ---------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Rural Navi — Address Identification & Navigation Server")
    print("Live on: http://127.0.0.1:5000")
    print("=" * 60)
    app.run(debug=True, port=5000)