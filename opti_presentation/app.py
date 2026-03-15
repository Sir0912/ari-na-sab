"""
app.py — Mobile API Backend for OPTI Employee App
Runs on port 5001 (separate from opti.py which runs on 5000)
Same database (opti_test)

Run:  python app.py
Install: pip install flask flask-cors pymysql
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import pymysql

app = Flask(__name__)
CORS(app)


# =====================================================
# DATABASE CONNECTION
# =====================================================
def get_connection():
    return pymysql.connect(
        host="localhost",
        user="root",
        password="Myservermybestfriend09941991294",
        database="opti_test",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )


# =====================================================
# HEALTH CHECK
# =====================================================
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "OPTI Mobile API", "port": 5001})


# =====================================================
# EMPLOYEE LOGIN
# POST /api/employee/login
# =====================================================
@app.route("/api/employee/login", methods=["POST"])
def employee_login():
    data     = request.json or {}
    name     = data.get("name", "").strip()
    password = data.get("password", "").strip()

    if not name or not password:
        return jsonify({"status": "error", "message": "Name and password are required."}), 400

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id_employee, name, age, sex, email, number, password
        FROM opti WHERE name=%s
    """, (name,))
    employee = cursor.fetchone()
    cursor.close()
    conn.close()

    if not employee:
        return jsonify({"status": "error", "message": "Employee not found."}), 404

    if str(employee["password"]) != str(password):
        return jsonify({"status": "error", "message": "Incorrect password."}), 401

    return jsonify({
        "status": "success",
        "employee": {
            "id":     employee["id_employee"],
            "name":   employee["name"],
            "age":    employee["age"],
            "sex":    employee["sex"],
            "email":  employee["email"],
            "number": employee["number"],
        }
    })


# =====================================================
# EMPLOYEE SUMMARY
# GET /api/employee/summary/<id>
# Returns total days, minutes, hours, salary, claims, balance, today
# =====================================================
@app.route("/api/employee/summary/<int:emp_id>", methods=["GET"])
def employee_summary(emp_id):
    conn = get_connection()
    cursor = conn.cursor()

    # Total completed days
    cursor.execute("""
        SELECT COUNT(*) AS total_days
        FROM opti_rec
        WHERE id_employee=%s AND time_in IS NOT NULL AND time_out IS NOT NULL
    """, (str(emp_id),))
    total_days = cursor.fetchone()["total_days"]

    # Total earned salary and minutes
    cursor.execute("""
        SELECT IFNULL(SUM(duration), 0) AS total_minutes,
               IFNULL(SUM(salary), 0)   AS total_earned
        FROM opti_rec
        WHERE id_employee=%s AND time_in IS NOT NULL AND time_out IS NOT NULL
    """, (str(emp_id),))
    totals = cursor.fetchone()

    # Total claimed (withdrawn)
    cursor.execute("""
        SELECT IFNULL(SUM(amount), 0) AS total_claimed
        FROM opti_claims
        WHERE id_employee=%s
    """, (emp_id,))
    claims_total = cursor.fetchone()["total_claimed"]

    # Today's record
    today_str = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("""
        SELECT id, time_in, time_out, duration, salary
        FROM opti_rec
        WHERE id_employee=%s AND DATE(time_in)=%s
    """, (str(emp_id), today_str))
    today_rec = cursor.fetchone()

    cursor.close()
    conn.close()

    total_minutes = int(totals["total_minutes"])
    total_earned  = float(totals["total_earned"])
    total_claimed = float(claims_total)
    balance       = total_earned - total_claimed

    today_data = None
    if today_rec and today_rec["time_in"]:
        today_data = {
            "id":       today_rec["id"],
            "time_in":  today_rec["time_in"].strftime("%I:%M %p"),
            "time_out": today_rec["time_out"].strftime("%I:%M %p") if today_rec["time_out"] else None,
            "duration": today_rec["duration"] or 0,
            "salary":   float(today_rec["salary"] or 0),
            "status":   "Completed" if today_rec["time_out"] else "Active",
        }

    return jsonify({
        "status":        "success",
        "total_days":    total_days,
        "total_minutes": total_minutes,
        "total_hours":   round(total_minutes / 60, 2),
        "total_earned":  total_earned,
        "total_claimed": total_claimed,
        "balance":       round(balance, 2),
        "today":         today_data,
    })


# =====================================================
# EMPLOYEE ATTENDANCE RECORDS
# GET /api/employee/records/<id>?month=YYYY-MM
# =====================================================
@app.route("/api/employee/records/<int:emp_id>", methods=["GET"])
def employee_records(emp_id):
    month = request.args.get("month")

    conn = get_connection()
    cursor = conn.cursor()

    if month:
        cursor.execute("""
            SELECT id, time_in, time_out, duration, salary
            FROM opti_rec
            WHERE id_employee=%s AND time_in IS NOT NULL
              AND DATE_FORMAT(time_in, '%%Y-%%m') = %s
            ORDER BY time_in DESC
        """, (str(emp_id), month))
    else:
        cursor.execute("""
            SELECT id, time_in, time_out, duration, salary
            FROM opti_rec
            WHERE id_employee=%s AND time_in IS NOT NULL
            ORDER BY time_in DESC
        """, (str(emp_id),))

    records = cursor.fetchall()
    cursor.close()
    conn.close()

    result = []
    for r in records:
        result.append({
            "id":       r["id"],
            "date":     r["time_in"].strftime("%Y-%m-%d"),
            "time_in":  r["time_in"].strftime("%I:%M %p"),
            "time_out": r["time_out"].strftime("%I:%M %p") if r["time_out"] else None,
            "duration": r["duration"] or 0,
            "salary":   float(r["salary"] or 0),
            "status":   "Completed" if r["time_out"] else "Active",
        })

    return jsonify({"status": "success", "records": result})


# =====================================================
# SALARY CLAIM (WITHDRAWAL)
# POST /api/employee/claim
# Body: { "employee_id": 1, "amount": 500.00, "note": "weekly pay" }
# =====================================================
@app.route("/api/employee/claim", methods=["POST"])
def employee_claim():
    data   = request.json or {}
    emp_id = data.get("employee_id")
    amount = data.get("amount")
    note   = data.get("note", "").strip()

    if not emp_id or not amount:
        return jsonify({"status": "error", "message": "employee_id and amount are required."}), 400

    try:
        amount = float(amount)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid amount."}), 400

    if amount <= 0:
        return jsonify({"status": "error", "message": "Amount must be greater than zero."}), 400

    conn = get_connection()
    cursor = conn.cursor()

    # Get current balance
    cursor.execute("""
        SELECT IFNULL(SUM(salary), 0) AS total_earned
        FROM opti_rec
        WHERE id_employee=%s AND time_out IS NOT NULL AND time_in IS NOT NULL
    """, (str(emp_id),))
    total_earned = float(cursor.fetchone()["total_earned"])

    cursor.execute("""
        SELECT IFNULL(SUM(amount), 0) AS total_claimed
        FROM opti_claims WHERE id_employee=%s
    """, (emp_id,))
    total_claimed = float(cursor.fetchone()["total_claimed"])

    balance = total_earned - total_claimed

    if amount > balance:
        cursor.close(); conn.close()
        return jsonify({
            "status":  "error",
            "message": f"Insufficient balance. Your current balance is ₱{balance:.2f}."
        }), 400

    # Insert claim record
    cursor.execute("""
        INSERT INTO opti_claims (id_employee, amount, note)
        VALUES (%s, %s, %s)
    """, (emp_id, amount, note or None))

    new_balance = balance - amount

    cursor.close(); conn.close()

    return jsonify({
        "status":      "success",
        "message":     f"₱{amount:.2f} claimed successfully.",
        "amount":      amount,
        "new_balance": round(new_balance, 2),
    })


# =====================================================
# CLAIM HISTORY
# GET /api/employee/claims/<id>
# =====================================================
@app.route("/api/employee/claims/<int:emp_id>", methods=["GET"])
def employee_claims(emp_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, amount, note, claim_at
        FROM opti_claims
        WHERE id_employee=%s
        ORDER BY claim_at DESC
    """, (emp_id,))
    claims = cursor.fetchall()
    cursor.close(); conn.close()

    result = []
    for c in claims:
        result.append({
            "id":         c["id"],
            "amount":     float(c["amount"]),
            "note":       c["note"] or "",
            "claim_at": c["claim_at"].strftime("%Y-%m-%d %I:%M %p"),
        })

    return jsonify({"status": "success", "claims": result})


# =====================================================
# FIND EMPLOYEE BY NAME (used for forgot password from login)
# POST /api/employee/find_by_name
# =====================================================
@app.route("/api/employee/find_by_name", methods=["POST"])
def find_by_name():
    data = request.json or {}
    name = data.get("name", "").strip()

    if not name:
        return jsonify({"status": "error", "message": "Name is required."}), 400

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id_employee FROM opti WHERE name=%s", (name,))
    row = cursor.fetchone()
    cursor.close(); conn.close()

    if not row:
        return jsonify({"status": "error", "message": "Employee not found."}), 404

    return jsonify({"status": "success", "employee_id": row["id_employee"]})


# =====================================================
# CHANGE PASSWORD (employee knows old password)
# POST /api/employee/change_password
# Body: { "employee_id": 1, "old_password": "123", "new_password": "456" }
# =====================================================
@app.route("/api/employee/change_password", methods=["POST"])
def change_password():
    data         = request.json or {}
    emp_id       = data.get("employee_id")
    old_password = str(data.get("old_password", "")).strip()
    new_password = str(data.get("new_password", "")).strip()

    if not emp_id or not old_password or not new_password:
        return jsonify({"status": "error", "message": "All fields are required."}), 400

    if len(new_password) < 4:
        return jsonify({"status": "error", "message": "New password must be at least 4 characters."}), 400

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT password FROM opti WHERE id_employee=%s", (emp_id,))
    row = cursor.fetchone()

    if not row:
        cursor.close(); conn.close()
        return jsonify({"status": "error", "message": "Employee not found."}), 404

    if str(row["password"]) != old_password:
        cursor.close(); conn.close()
        return jsonify({"status": "error", "message": "Old password is incorrect."}), 401

    cursor.execute("UPDATE opti SET password=%s WHERE id_employee=%s", (new_password, emp_id))
    cursor.close(); conn.close()

    return jsonify({"status": "success", "message": "Password changed successfully."})


# =====================================================
# REQUEST PASSWORD RESET (forgot password — sends to admin)
# POST /api/employee/request_reset
# Body: { "employee_id": 1 }
# =====================================================
@app.route("/api/employee/request_reset", methods=["POST"])
def request_reset():
    data   = request.json or {}
    emp_id = data.get("employee_id")

    if not emp_id:
        return jsonify({"status": "error", "message": "employee_id is required."}), 400

    conn = get_connection()
    cursor = conn.cursor()

    # Check employee exists
    cursor.execute("SELECT name FROM opti WHERE id_employee=%s", (emp_id,))
    emp = cursor.fetchone()
    if not emp:
        cursor.close(); conn.close()
        return jsonify({"status": "error", "message": "Employee not found."}), 404

    # Check if there's already a pending request
    cursor.execute("""
        SELECT id, status FROM opti_password_requests
        WHERE id_employee=%s AND status='pending'
    """, (emp_id,))
    existing = cursor.fetchone()

    if existing:
        cursor.close(); conn.close()
        return jsonify({
            "status":  "already_pending",
            "message": "You already have a pending reset request. Please wait for admin approval."
        })

    # Insert new request
    cursor.execute("""
        INSERT INTO opti_password_requests (id_employee) VALUES (%s)
    """, (emp_id,))

    cursor.close(); conn.close()

    return jsonify({
        "status":  "success",
        "message": "Reset request sent. Please wait for your admin to approve it."
    })


# =====================================================
# CHECK RESET REQUEST STATUS
# GET /api/employee/reset_status/<emp_id>
# Returns: pending / approved (with temp_password) / rejected / none
# =====================================================
@app.route("/api/employee/reset_status/<int:emp_id>", methods=["GET"])
def reset_status(emp_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, status, temp_password, requested_at
        FROM opti_password_requests
        WHERE id_employee=%s
        ORDER BY requested_at DESC
        LIMIT 1
    """, (emp_id,))
    req = cursor.fetchone()
    cursor.close(); conn.close()

    if not req:
        return jsonify({"status": "success", "request": None})

    return jsonify({
        "status": "success",
        "request": {
            "id":            req["id"],
            "request_status": req["status"],
            "temp_password": req["temp_password"] if req["status"] == "approved" else None,
            "requested_at":  req["requested_at"].strftime("%Y-%m-%d %I:%M %p"),
        }
    })


# =====================================================
# APPLY TEMP PASSWORD (after admin approves)
# POST /api/employee/apply_temp_password
# Body: { "employee_id": 1, "temp_password": "xxx", "new_password": "yyy" }
# =====================================================
@app.route("/api/employee/apply_temp_password", methods=["POST"])
def apply_temp_password():
    data          = request.json or {}
    emp_id        = data.get("employee_id")
    temp_password = str(data.get("temp_password", "")).strip()
    new_password  = str(data.get("new_password", "")).strip()

    if not emp_id or not temp_password or not new_password:
        return jsonify({"status": "error", "message": "All fields are required."}), 400

    if len(new_password) < 4:
        return jsonify({"status": "error", "message": "New password must be at least 4 characters."}), 400

    conn = get_connection()
    cursor = conn.cursor()

    # Verify temp password matches the approved request
    cursor.execute("""
        SELECT id FROM opti_password_requests
        WHERE id_employee=%s AND status='approved' AND temp_password=%s
        ORDER BY requested_at DESC LIMIT 1
    """, (emp_id, temp_password))
    req = cursor.fetchone()

    if not req:
        cursor.close(); conn.close()
        return jsonify({"status": "error", "message": "Invalid or expired temporary password."}), 401

    # Update password
    cursor.execute("UPDATE opti SET password=%s WHERE id_employee=%s", (new_password, emp_id))

    # Mark request as used (delete it)
    cursor.execute("DELETE FROM opti_password_requests WHERE id=%s", (req["id"],))

    cursor.close(); conn.close()

    return jsonify({"status": "success", "message": "Password updated successfully. Please log in with your new password."})


# =====================================================
# RUN ON PORT 5001
# =====================================================
if __name__ == "__main__":
    print("=" * 50)
    print("  OPTI Mobile API  —  port 5001")
    print("  Admin dashboard  —  port 5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5001, debug=True)
