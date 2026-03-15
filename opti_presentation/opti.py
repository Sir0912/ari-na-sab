from flask import Flask, render_template, request, redirect, send_from_directory, url_for, session, jsonify, send_file
from flask_socketio import SocketIO
from datetime import datetime, time as dtime
import pymysql
from werkzeug.security import generate_password_hash, check_password_hash
import io, csv
import os
from datetime import timedelta
import threading
import time

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
app.secret_key = "blackpower"


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
# ADMIN CREDENTIALS
# =====================================================
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = generate_password_hash("admin123")


# =====================================================
# HELPER: CONVERT TIMEDELTA TO HH:MM STRING
# MySQL TIME columns return as timedelta in pymysql
# =====================================================
def to_time_str(val):
    if val is None:
        return None
    if hasattr(val, 'total_seconds'):
        total_secs = int(val.total_seconds())
        h = total_secs // 3600
        m = (total_secs % 3600) // 60
        return f"{h:02d}:{m:02d}"
    s = str(val).strip()
    return s if s else None


# =====================================================
# HELPER: GET SALARY SETTINGS
# =====================================================
def get_salary_settings():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM opti_settings WHERE id = 1")
    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if result:
        return {
            "salary_per_minute": float(result.get("salary_per_minute", 5.00)),
            "break_start": to_time_str(result.get("break_start")),
            "break_end":   to_time_str(result.get("break_end")),
            "pay_start":   to_time_str(result.get("pay_start")),
            "pay_end":     to_time_str(result.get("pay_end")),
        }
    return {
        "salary_per_minute": 5.00,
        "break_start": None,
        "break_end": None,
        "pay_start": None,
        "pay_end": None,
    }


def get_salary_per_minute():
    return get_salary_settings()["salary_per_minute"]


# =====================================================
# HELPER: COMPUTE PAID MINUTES
# Clamps to pay window and subtracts break time
# =====================================================
def compute_paid_minutes(time_in, time_out, settings):
    if time_out is None:
        time_out = datetime.now()

    pay_start_str = to_time_str(settings.get("pay_start"))
    pay_end_str   = to_time_str(settings.get("pay_end"))

    effective_in  = time_in
    effective_out = time_out

    if pay_start_str:
        h, m = map(int, pay_start_str.split(":"))
        window_start = time_in.replace(hour=h, minute=m, second=0, microsecond=0)
        if effective_in < window_start:
            effective_in = window_start

    if pay_end_str:
        h, m = map(int, pay_end_str.split(":"))
        window_end = time_in.replace(hour=h, minute=m, second=0, microsecond=0)
        if effective_out > window_end:
            effective_out = window_end

    if effective_out <= effective_in:
        return 0

    total_minutes = int((effective_out - effective_in).total_seconds() // 60)

    break_start_str = to_time_str(settings.get("break_start"))
    break_end_str   = to_time_str(settings.get("break_end"))

    if break_start_str and break_end_str:
        bh, bm = map(int, break_start_str.split(":"))
        eh, em = map(int, break_end_str.split(":"))
        break_start_dt = time_in.replace(hour=bh, minute=bm, second=0, microsecond=0)
        break_end_dt   = time_in.replace(hour=eh, minute=em, second=0, microsecond=0)

        overlap_start = max(effective_in, break_start_dt)
        overlap_end   = min(effective_out, break_end_dt)

        if overlap_end > overlap_start:
            break_minutes = int((overlap_end - overlap_start).total_seconds() // 60)
            total_minutes = max(0, total_minutes - break_minutes)

    return total_minutes


# =====================================================
# AUTH ROUTES
# =====================================================
@app.route("/", methods=["GET"])
def landing_page():
    return render_template("admin_login.html", error=None)


@app.route("/log_in_admin", methods=["POST"])
def log_in_admin():
    admin = request.form.get("username")
    password = request.form.get("password")

    if admin == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
        session["admin"] = admin
        return redirect(url_for("admin_dashboard"))

    return render_template("admin_login.html", error="Invalid credentials")


@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("landing_page"))


# =====================================================
# DASHBOARD
# =====================================================
@app.route("/admin_dashboard")
def admin_dashboard():
    if "admin" not in session:
        return redirect(url_for("landing_page"))

    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT opti.name, opti_rec.time_in, opti_rec.time_out,
               opti_rec.duration, opti_rec.salary,
               opti_rec.late_minutes, opti_rec.undertime_minutes,
               opti_rec.id, opti_rec.id_employee
        FROM opti_rec
        JOIN opti ON opti_rec.id_employee = opti.id_employee
        WHERE DATE(opti_rec.time_in)=%s
        ORDER BY opti_rec.id DESC
    """, (today,))
    records = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) AS total FROM opti")
    total_employees = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS present FROM opti_rec WHERE DATE(time_in)=%s AND time_out IS NULL", (today,))
    present_today = cursor.fetchone()["present"]

    cursor.execute("SELECT IFNULL(SUM(salary),0) AS total_salary FROM opti_rec WHERE DATE(time_in)=%s", (today,))
    total_salary = cursor.fetchone()["total_salary"]

    cursor.execute("SELECT * FROM opti ORDER BY id_employee ASC")
    employees = cursor.fetchall()

    cursor.close()
    conn.close()

    settings = get_salary_settings()

    return render_template(
        "admin_dashboard.html",
        admin_name=session.get("admin", "Admin"),
        total_employees=total_employees,
        present_today=present_today,
        total_salary=total_salary,
        records=records,
        employees=employees,
        salary_rate=settings["salary_per_minute"],
        break_start=settings["break_start"] or "",
        break_end=settings["break_end"] or "",
        pay_start=settings["pay_start"] or "",
        pay_end=settings["pay_end"] or "",
    )


# =====================================================
# EXPORT TO EXCEL
# =====================================================
@app.route("/export_excel")
def export_excel():
    if "admin" not in session:
        return redirect(url_for("landing_page"))

    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT opti.name, opti_rec.time_in, opti_rec.time_out,
               opti_rec.duration, opti_rec.salary
        FROM opti_rec
        JOIN opti ON opti_rec.id_employee = opti.id_employee
        WHERE DATE(opti_rec.time_in)=%s
        ORDER BY opti_rec.id DESC
    """, (today,))
    records = cursor.fetchall()
    cursor.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Time In", "Time Out", "Duration (min)", "Salary"])
    for r in records:
        writer.writerow([
            r["name"],
            r["time_in"].strftime("%H:%M") if r["time_in"] else "",
            r["time_out"].strftime("%H:%M") if r["time_out"] else "",
            r.get("duration", ""),
            r.get("salary", "")
        ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"attendance_{today}.csv"
    )


# =====================================================
# HISTORY RECORDS
# =====================================================
HISTORY_FOLDER = os.path.join(os.getcwd(), "history_records")
os.makedirs(HISTORY_FOLDER, exist_ok=True)


@app.route("/history_records")
def history_records():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM opti_history ORDER BY created_at DESC")
    files = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("history_records.html", files=files)


@app.route("/history_download/<filename>")
def history_download(filename):
    return send_file(os.path.join(HISTORY_FOLDER, filename), as_attachment=True)


def archive_yesterday_records():
    conn = get_connection()
    cursor = conn.cursor()
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT o.name, r.time_in, r.time_out, r.duration, r.salary
        FROM opti_rec r
        JOIN opti o ON r.id_employee = o.id_employee
        WHERE DATE(r.time_in) = %s
    """, (yesterday,))
    records = cursor.fetchall()

    if records:
        filename = f"attendance_{yesterday}.csv"
        path = os.path.join(HISTORY_FOLDER, filename)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Name", "Time In", "Time Out", "Duration (min)", "Salary"])
            for r in records:
                writer.writerow([
                    r["name"],
                    r["time_in"].strftime("%H:%M") if r["time_in"] else "",
                    r["time_out"].strftime("%H:%M") if r["time_out"] else "",
                    r.get("duration", ""),
                    r.get("salary", "")
                ])
        cursor.execute("INSERT INTO opti_history (file_name) VALUES (%s)", (filename,))

    cursor.close()
    conn.close()


@app.route("/history_records_api")
def history_records_api():
    files = [f for f in os.listdir(HISTORY_FOLDER) if f.endswith(".csv")]
    return jsonify(files)


@app.route("/history_records/download/<filename>")
def download_history_file(filename):
    return send_from_directory(HISTORY_FOLDER, filename, as_attachment=True)


# =====================================================
# SALARY RATE & SETTINGS API
# =====================================================
@app.route("/api/get_salary_rate")
def get_salary_rate():
    return jsonify({"salary_per_minute": get_salary_per_minute()})


@app.route("/api/get_salary_settings")
def get_salary_settings_api():
    return jsonify(get_salary_settings())


@app.route("/api/update_salary_rate", methods=["POST"])
def update_salary_rate():
    data = request.json
    new_rate = float(data.get("salary_per_minute", 5.00))
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE opti_settings SET salary_per_minute=%s WHERE id=1", (new_rate,))
    cursor.close()
    conn.close()
    return jsonify({"status": "success", "salary_per_minute": new_rate})


@app.route("/api/update_salary_settings", methods=["POST"])
def update_salary_settings():
    data = request.json

    def clean_time(val):
        if not val or str(val).strip() == "":
            return None
        return str(val).strip()

    salary_per_minute = float(data.get("salary_per_minute", 5.00))
    break_start = clean_time(data.get("break_start"))
    break_end   = clean_time(data.get("break_end"))
    pay_start   = clean_time(data.get("pay_start"))
    pay_end     = clean_time(data.get("pay_end"))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE opti_settings
        SET salary_per_minute=%s, break_start=%s, break_end=%s, pay_start=%s, pay_end=%s
        WHERE id=1
    """, (salary_per_minute, break_start, break_end, pay_start, pay_end))
    cursor.close()
    conn.close()

    return jsonify({
        "status": "success",
        "salary_per_minute": salary_per_minute,
        "break_start": break_start,
        "break_end": break_end,
        "pay_start": pay_start,
        "pay_end": pay_end,
    })


# =====================================================
# EMPLOYEE MANAGEMENT
# =====================================================
@app.route("/add_employee", methods=["POST"])
def add_employee():
    data = request.form
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id_employee FROM opti WHERE name=%s", (data.get("name_inp"),))
    if cursor.fetchone():
        cursor.close(); conn.close()
        return jsonify({"status": "error", "message": "Employee with this name already exists!"})

    cursor.execute("SELECT id_employee FROM opti WHERE rfid=%s", (data.get("rfid_inp"),))
    if cursor.fetchone():
        cursor.close(); conn.close()
        return jsonify({"status": "error", "message": "Employee with this RFID already exists!"})

    cursor.execute("SELECT id_employee FROM opti WHERE email=%s", (data.get("email_inp"),))
    if cursor.fetchone():
        cursor.close(); conn.close()
        return jsonify({"status": "error", "message": "Employee with this email already exists!"})

    cursor.execute("SELECT id_employee FROM opti ORDER BY id_employee ASC")
    existing_ids = [row["id_employee"] for row in cursor.fetchall()]
    next_id = 1
    for eid in existing_ids:
        if eid == next_id:
            next_id += 1
        else:
            break

    cursor.execute("""
        INSERT INTO opti (id_employee, name, age, sex, email, number, rfid)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (next_id, data.get("name_inp"), data.get("age_inp"), data.get("sex_inp"),
          data.get("email_inp"), data.get("num_inp"), data.get("rfid_inp")))

    cursor.execute("SELECT * FROM opti WHERE id_employee=%s", (next_id,))
    new_emp = cursor.fetchone()
    cursor.close(); conn.close()
    return jsonify(new_emp)


@app.route("/drop_employee", methods=["POST"])
def drop_employee():
    emp_id = int(request.form.get("employ_id"))
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM opti WHERE id_employee=%s", (emp_id,))
    cursor.close(); conn.close()
    return jsonify({"status": "success"})


# =====================================================
# SCAN RFID
# =====================================================
@app.route("/scan", methods=["POST"])
def scan():
    uid = request.json.get("uid").replace(" ", "").upper()
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM opti WHERE UPPER(REPLACE(rfid,' ',''))=%s", (uid,))
    employee = cursor.fetchone()

    if not employee:
        cursor.close(); conn.close()
        return jsonify({"status": "not_found"})

    cursor.execute("SELECT * FROM opti_rec WHERE id_employee=%s AND DATE(time_in)=%s",
                   (employee["id_employee"], today_str))
    record = cursor.fetchone()

    # ---------- TIME IN ----------
    if not record:
        cursor.execute("INSERT INTO opti_rec (id_employee, time_in) VALUES (%s,%s)",
                       (employee["id_employee"], now))
        cursor.execute("SELECT id FROM opti_rec WHERE id_employee=%s AND time_in=%s",
                       (employee["id_employee"], now))
        new_record = cursor.fetchone()

        cursor.execute("SELECT COUNT(*) AS present FROM opti_rec WHERE DATE(time_in)=CURDATE() AND time_out IS NULL")
        present_count = cursor.fetchone()["present"]
        cursor.execute("SELECT IFNULL(SUM(salary),0) AS total_salary FROM opti_rec WHERE DATE(time_in)=CURDATE()")
        total_salary = cursor.fetchone()["total_salary"]
        cursor.close(); conn.close()

        socketio.emit("attendance_update", {
            "action": "time_in",
            "record_id": new_record["id"],
            "employee_id": employee["id_employee"],
            "name": employee["name"],
            "time_in": now.strftime("%I:%M %p"),
            "time_out": "-",
            "duration": 0,
            "salary": 0,
            "present_count": present_count,
            "total_salary": float(total_salary)
        })

        return jsonify({"status": "time_in", "name": employee["name"], "time": now.strftime("%I:%M %p")})

    # ---------- DOUBLE TAP PROTECTION ----------
    elif record and not record["time_out"]:
        minutes_since_in = int((now - record["time_in"]).total_seconds() // 60)

        if minutes_since_in < 60:
            # Too soon — block the sign out
            remaining = 60 - minutes_since_in
            cursor.close(); conn.close()

            socketio.emit("too_soon", {
                "name":    employee["name"],
                "message": f"{employee['name']} must wait {remaining} more minute(s) before signing out.",
            })

            return jsonify({
                "status":    "too_soon",
                "name":      employee["name"],
                "message":   f"Please wait {remaining} more minute(s) before signing out.",
                "remaining": remaining
            })

        # ---------- TIME OUT ----------
        settings = get_salary_settings()
        paid_minutes = compute_paid_minutes(record["time_in"], now, settings)
        salary = paid_minutes * settings["salary_per_minute"]

        cursor.execute("UPDATE opti_rec SET time_out=%s, duration=%s, salary=%s WHERE id=%s",
                       (now, paid_minutes, salary, record["id"]))

        cursor.execute("SELECT COUNT(*) AS present FROM opti_rec WHERE DATE(time_in)=CURDATE() AND time_out IS NULL")
        present_count = cursor.fetchone()["present"]
        cursor.execute("SELECT IFNULL(SUM(salary),0) AS total_salary FROM opti_rec WHERE DATE(time_in)=CURDATE()")
        total_salary = cursor.fetchone()["total_salary"]
        cursor.close(); conn.close()

        socketio.emit("attendance_update", {
            "action": "time_out",
            "record_id": record["id"],
            "employee_id": employee["id_employee"],
            "name": employee["name"],
            "time_in": record["time_in"].strftime("%I:%M %p"),
            "time_out": now.strftime("%I:%M %p"),
            "duration": paid_minutes,
            "salary": salary,
            "present_count": present_count,
            "total_salary": float(total_salary)
        })

        return jsonify({"status": "time_out", "name": employee["name"], "time": now.strftime("%I:%M %p")})

    else:
        cursor.close(); conn.close()
        return jsonify({"status": "already_done"})


# =====================================================
# FEATURE 3: MANUAL TIME IN
# =====================================================
@app.route("/api/manual_time_in", methods=["POST"])
def manual_time_in():
    data = request.json
    emp_id = int(data.get("employee_id"))
    time_in_str = data.get("time_in")
    today_str = datetime.now().strftime("%Y-%m-%d")

    try:
        time_in_dt = datetime.strptime(f"{today_str} {time_in_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid time format. Use HH:MM"}), 400

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM opti WHERE id_employee=%s", (emp_id,))
    employee = cursor.fetchone()
    if not employee:
        cursor.close(); conn.close()
        return jsonify({"status": "error", "message": "Employee not found"})

    cursor.execute("SELECT * FROM opti_rec WHERE id_employee=%s AND DATE(time_in)=%s", (emp_id, today_str))
    if cursor.fetchone():
        cursor.close(); conn.close()
        return jsonify({"status": "error", "message": f"{employee['name']} already has an attendance record today."})

    cursor.execute("INSERT INTO opti_rec (id_employee, time_in) VALUES (%s,%s)", (emp_id, time_in_dt))
    cursor.execute("SELECT id FROM opti_rec WHERE id_employee=%s AND time_in=%s", (emp_id, time_in_dt))
    new_record = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) AS present FROM opti_rec WHERE DATE(time_in)=CURDATE() AND time_out IS NULL")
    present_count = cursor.fetchone()["present"]
    cursor.execute("SELECT IFNULL(SUM(salary),0) AS total_salary FROM opti_rec WHERE DATE(time_in)=CURDATE()")
    total_salary = cursor.fetchone()["total_salary"]
    cursor.close(); conn.close()

    socketio.emit("attendance_update", {
        "action": "time_in",
        "record_id": new_record["id"],
        "employee_id": emp_id,
        "name": employee["name"],
        "time_in": time_in_dt.strftime("%I:%M %p"),
        "time_out": "-",
        "duration": 0,
        "salary": 0,
        "present_count": present_count,
        "total_salary": float(total_salary),
        "manual": True
    })
    return jsonify({"status": "success", "message": f"Manual time in set for {employee['name']} at {time_in_dt.strftime('%I:%M %p')}"})


# =====================================================
# FEATURE 3: MANUAL TIME OUT
# =====================================================
@app.route("/api/manual_time_out", methods=["POST"])
def manual_time_out():
    data = request.json
    emp_id = int(data.get("employee_id"))
    time_out_str = data.get("time_out")
    today_str = datetime.now().strftime("%Y-%m-%d")

    try:
        time_out_dt = datetime.strptime(f"{today_str} {time_out_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid time format. Use HH:MM"}), 400

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT opti_rec.*, opti.name FROM opti_rec
        JOIN opti ON opti_rec.id_employee = opti.id_employee
        WHERE opti_rec.id_employee=%s AND DATE(opti_rec.time_in)=%s AND opti_rec.time_out IS NULL
    """, (emp_id, today_str))
    record = cursor.fetchone()

    if not record:
        cursor.close(); conn.close()
        return jsonify({"status": "error", "message": "No active time-in record found for this employee today."})

    if time_out_dt <= record["time_in"]:
        cursor.close(); conn.close()
        return jsonify({"status": "error", "message": "Time out must be after time in."})

    settings = get_salary_settings()
    paid_minutes = compute_paid_minutes(record["time_in"], time_out_dt, settings)
    salary = paid_minutes * settings["salary_per_minute"]

    cursor.execute("UPDATE opti_rec SET time_out=%s, duration=%s, salary=%s WHERE id=%s",
                   (time_out_dt, paid_minutes, salary, record["id"]))

    cursor.execute("SELECT COUNT(*) AS present FROM opti_rec WHERE DATE(time_in)=CURDATE() AND time_out IS NULL")
    present_count = cursor.fetchone()["present"]
    cursor.execute("SELECT IFNULL(SUM(salary),0) AS total_salary FROM opti_rec WHERE DATE(time_in)=CURDATE()")
    total_salary = cursor.fetchone()["total_salary"]
    cursor.close(); conn.close()

    socketio.emit("attendance_update", {
        "action": "time_out",
        "record_id": record["id"],
        "employee_id": emp_id,
        "name": record["name"],
        "time_in": record["time_in"].strftime("%I:%M %p"),
        "time_out": time_out_dt.strftime("%I:%M %p"),
        "duration": paid_minutes,
        "salary": salary,
        "present_count": present_count,
        "total_salary": float(total_salary),
        "manual": True
    })
    return jsonify({"status": "success", "message": f"Manual time out set for {record['name']} at {time_out_dt.strftime('%I:%M %p')}"})


# =====================================================
# FEATURE 4: FORCE SIGN-OUT (Stop button)
# =====================================================
@app.route("/api/force_signout/<int:record_id>", methods=["POST"])
def force_signout(record_id):
    now = datetime.now()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT opti_rec.*, opti.name FROM opti_rec
        JOIN opti ON opti_rec.id_employee = opti.id_employee
        WHERE opti_rec.id=%s AND opti_rec.time_out IS NULL
    """, (record_id,))
    record = cursor.fetchone()

    if not record:
        cursor.close(); conn.close()
        return jsonify({"status": "error", "message": "Record not found or already signed out."})

    settings = get_salary_settings()
    paid_minutes = compute_paid_minutes(record["time_in"], now, settings)
    salary = paid_minutes * settings["salary_per_minute"]

    cursor.execute("UPDATE opti_rec SET time_out=%s, duration=%s, salary=%s WHERE id=%s",
                   (now, paid_minutes, salary, record_id))

    cursor.execute("SELECT COUNT(*) AS present FROM opti_rec WHERE DATE(time_in)=CURDATE() AND time_out IS NULL")
    present_count = cursor.fetchone()["present"]
    cursor.execute("SELECT IFNULL(SUM(salary),0) AS total_salary FROM opti_rec WHERE DATE(time_in)=CURDATE()")
    total_salary = cursor.fetchone()["total_salary"]
    cursor.close(); conn.close()

    socketio.emit("attendance_update", {
        "action": "time_out",
        "record_id": record_id,
        "employee_id": record["id_employee"],
        "name": record["name"],
        "time_in": record["time_in"].strftime("%I:%M %p"),
        "time_out": now.strftime("%I:%M %p"),
        "duration": paid_minutes,
        "salary": salary,
        "present_count": present_count,
        "total_salary": float(total_salary),
        "forced": True
    })

    return jsonify({
        "status": "success",
        "message": f"{record['name']} has been signed out.",
        "time_out": now.strftime("%I:%M %p"),
        "duration": paid_minutes,
        "salary": round(salary, 2)
    })


# =====================================================
# STATS API
# =====================================================
@app.route("/dashboard_stats_api")
def dashboard_stats_api():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS total FROM opti")
    total = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) AS present FROM opti_rec WHERE DATE(time_in)=CURDATE() AND time_out IS NULL")
    present = cursor.fetchone()["present"]
    cursor.execute("SELECT IFNULL(SUM(salary),0) AS total_salary FROM opti_rec WHERE DATE(time_in)=CURDATE()")
    total_salary = cursor.fetchone()["total_salary"]
    cursor.close(); conn.close()
    return jsonify({"total_employees": total, "present_today": present, "total_salary": float(total_salary)})


# =====================================================
# ATTENDANCE TABLE API
# =====================================================
@app.route("/attendance_table_api")
def attendance_table_api():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.id, o.name,
               DATE_FORMAT(r.time_in, '%h:%i %p')  AS time_in,
               DATE_FORMAT(r.time_out, '%h:%i %p') AS time_out
        FROM opti_rec r
        JOIN opti o ON r.id_employee = o.id_employee
        WHERE DATE(r.time_in) = CURDATE()
        ORDER BY r.id DESC
    """)
    records = cursor.fetchall()
    cursor.close(); conn.close()
    return jsonify(records)


# =====================================================
# SALARY TABLE API
# =====================================================
@app.route("/salary_table_api")
def salary_table_api():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT r.id, o.name, r.time_in, r.time_out, r.salary, r.duration
            FROM opti_rec r
            JOIN opti o ON r.id_employee = o.id_employee
            WHERE DATE(r.time_in) = CURDATE()
            ORDER BY r.id DESC
        """)
        records = cursor.fetchall()
        for r in records:
            r["time_in"]  = r["time_in"].strftime("%I:%M %p")  if r["time_in"]  else "-"
            r["time_out"] = r["time_out"].strftime("%I:%M %p") if r["time_out"] else "-"
        return jsonify(records)
    except Exception as e:
        print(f"Error in salary_table_api: {e}")
        return jsonify([]), 500
    finally:
        cursor.close(); conn.close()


# =====================================================
# EDIT / UPDATE EMPLOYEE
# =====================================================
@app.route("/edit_employee/<int:emp_id>")
def edit_employee(emp_id):
    if "admin" not in session:
        return redirect(url_for("landing_page"))
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM opti WHERE id_employee=%s", (emp_id,))
    employee = cursor.fetchone()
    cursor.close(); conn.close()
    if not employee:
        return redirect(url_for("admin_dashboard"))
    return render_template("edit_employee.html", employee=employee, admin_name=session.get("admin", "Admin"))


@app.route("/api/get_employee/<int:emp_id>")
def get_employee(emp_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM opti WHERE id_employee=%s", (emp_id,))
    employee = cursor.fetchone()
    cursor.close(); conn.close()
    if employee:
        return jsonify({"status": "success", "employee": employee})
    return jsonify({"status": "error", "message": "Employee not found"}), 404


@app.route("/update_employee", methods=["POST"])
def update_employee():
    data = request.form
    emp_id = int(data.get("id_inp"))
    conn = get_connection()
    cursor = conn.cursor()

    if data.get("name_inp") != data.get("old_name"):
        cursor.execute("SELECT id_employee FROM opti WHERE name=%s AND id_employee != %s",
                       (data.get("name_inp"), emp_id))
        if cursor.fetchone():
            cursor.close(); conn.close()
            return jsonify({"status": "error", "message": "Employee with this name already exists!"})

    if data.get("rfid_inp") != data.get("old_rfid"):
        cursor.execute("SELECT id_employee FROM opti WHERE rfid=%s AND id_employee != %s",
                       (data.get("rfid_inp"), emp_id))
        if cursor.fetchone():
            cursor.close(); conn.close()
            return jsonify({"status": "error", "message": "Employee with this RFID already exists!"})

    if data.get("email_inp") != data.get("old_email"):
        cursor.execute("SELECT id_employee FROM opti WHERE email=%s AND id_employee != %s",
                       (data.get("email_inp"), emp_id))
        if cursor.fetchone():
            cursor.close(); conn.close()
            return jsonify({"status": "error", "message": "Employee with this email already exists!"})

    cursor.execute("""
        UPDATE opti SET name=%s, age=%s, sex=%s, email=%s, number=%s, rfid=%s
        WHERE id_employee=%s
    """, (data.get("name_inp"), data.get("age_inp"), data.get("sex_inp"),
          data.get("email_inp"), data.get("num_inp"), data.get("rfid_inp"), emp_id))

    cursor.execute("SELECT * FROM opti WHERE id_employee=%s", (emp_id,))
    updated_emp = cursor.fetchone()
    cursor.close(); conn.close()
    return jsonify(updated_emp)


# =====================================================
# ADMIN: EMPLOYEE SUMMARY (days, hours, salary, balance, claims)
# =====================================================
@app.route("/api/admin/employee_summary/<int:emp_id>", methods=["GET"])
def admin_employee_summary(emp_id):
    conn = get_connection()
    cursor = conn.cursor()

    # Total completed days
    cursor.execute("""
        SELECT COUNT(*) AS total_days
        FROM opti_rec
        WHERE id_employee=%s AND time_in IS NOT NULL AND time_out IS NOT NULL
    """, (str(emp_id),))
    total_days = cursor.fetchone()["total_days"]

    # Total minutes and earned salary
    cursor.execute("""
        SELECT IFNULL(SUM(duration), 0) AS total_minutes,
               IFNULL(SUM(salary), 0)   AS total_earned
        FROM opti_rec
        WHERE id_employee=%s AND time_in IS NOT NULL AND time_out IS NOT NULL
    """, (str(emp_id),))
    totals = cursor.fetchone()

    # Total claimed
    cursor.execute("""
        SELECT IFNULL(SUM(amount), 0) AS total_claimed
        FROM opti_claims WHERE id_employee=%s
    """, (emp_id,))
    total_claimed = float(cursor.fetchone()["total_claimed"])

    # Claims history
    cursor.execute("""
        SELECT id, amount, note, claim_at
        FROM opti_claims
        WHERE id_employee=%s
        ORDER BY claim_at DESC
    """, (emp_id,))
    claims_rows = cursor.fetchall()

    cursor.close(); conn.close()

    total_minutes = int(totals["total_minutes"])
    total_earned  = float(totals["total_earned"])
    balance       = total_earned - total_claimed

    claims = []
    for c in claims_rows:
        claims.append({
            "id":         c["id"],
            "amount":     float(c["amount"]),
            "note":       c["note"] or "",
            "claim_at": c["claim_at"].strftime("%Y-%m-%d %I:%M %p"),
        })

    return jsonify({
        "status":        "success",
        "total_days":    total_days,
        "total_minutes": total_minutes,
        "total_hours":   round(total_minutes / 60, 2),
        "total_earned":  total_earned,
        "total_claimed": total_claimed,
        "balance":       round(balance, 2),
        "claims":        claims,
    })


# =====================================================
# ADMIN: RECORD A CLAIM (deducts from employee balance)
# =====================================================
@app.route("/api/admin/claim", methods=["POST"])
def admin_claim():
    data   = request.json or {}
    emp_id = data.get("employee_id")
    amount = data.get("amount")
    note   = data.get("note", "").strip()

    if not emp_id or not amount:
        return jsonify({"status": "error", "message": "Employee and amount are required."}), 400

    try:
        amount = float(amount)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid amount."}), 400

    if amount <= 0:
        return jsonify({"status": "error", "message": "Amount must be greater than zero."}), 400

    conn = get_connection()
    cursor = conn.cursor()

    # Get employee name
    cursor.execute("SELECT name FROM opti WHERE id_employee=%s", (emp_id,))
    emp = cursor.fetchone()
    if not emp:
        cursor.close(); conn.close()
        return jsonify({"status": "error", "message": "Employee not found."}), 404

    # Check balance
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
            "message": f"Insufficient balance. {emp['name']} only has ₱{balance:.2f} available."
        }), 400

    cursor.execute("""
        INSERT INTO opti_claims (id_employee, amount, note) VALUES (%s, %s, %s)
    """, (emp_id, amount, note or None))

    cursor.close(); conn.close()

    return jsonify({
        "status":      "success",
        "message":     f"₱{amount:.2f} claimed for {emp['name']}. New balance: ₱{(balance - amount):.2f}",
        "new_balance": round(balance - amount, 2),
    })


# =====================================================
# ADMIN: GET ALL CLAIMS
# =====================================================
@app.route("/api/admin/all_claims", methods=["GET"])
def admin_all_claims():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, c.amount, c.note, c.claim_at, o.name AS employee_name
        FROM opti_claims c
        JOIN opti o ON c.id_employee = o.id_employee
        ORDER BY c.claim_at DESC
    """)
    claims = cursor.fetchall()
    cursor.close(); conn.close()

    result = []
    for c in claims:
        result.append({
            "id":            c["id"],
            "employee_name": c["employee_name"],
            "amount":        float(c["amount"]),
            "note":          c["note"] or "",
            "claim_at":    c["claim_at"].strftime("%Y-%m-%d %I:%M %p"),
        })
    return jsonify({"status": "success", "claims": result})


# =====================================================
# PASSWORD RESET REQUESTS (Admin side)
# =====================================================
@app.route("/api/password_requests", methods=["GET"])
def get_password_requests():
    """Get all pending password reset requests for admin dashboard."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.id, r.id_employee, r.status, r.requested_at,
               o.name AS employee_name
        FROM opti_password_requests r
        JOIN opti o ON r.id_employee = o.id_employee
        ORDER BY r.requested_at DESC
    """)
    requests = cursor.fetchall()
    cursor.close(); conn.close()

    result = []
    for r in requests:
        result.append({
            "id":            r["id"],
            "employee_id":   r["id_employee"],
            "employee_name": r["employee_name"],
            "status":        r["status"],
            "requested_at":  r["requested_at"].strftime("%Y-%m-%d %I:%M %p"),
        })
    return jsonify(result)


@app.route("/api/password_requests/approve/<int:req_id>", methods=["POST"])
def approve_password_request(req_id):
    """Admin approves reset request and sets a temporary password."""
    data          = request.json or {}
    temp_password = str(data.get("temp_password", "")).strip()

    if not temp_password:
        return jsonify({"status": "error", "message": "Temporary password is required."}), 400

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE opti_password_requests
        SET status='approved', temp_password=%s, resolved_at=NOW()
        WHERE id=%s
    """, (temp_password, req_id))

    cursor.close(); conn.close()
    return jsonify({"status": "success", "message": "Request approved."})


@app.route("/api/password_requests/reject/<int:req_id>", methods=["POST"])
def reject_password_request(req_id):
    """Admin rejects a reset request."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE opti_password_requests
        SET status='rejected', resolved_at=NOW()
        WHERE id=%s
    """, (req_id,))
    cursor.close(); conn.close()
    return jsonify({"status": "success", "message": "Request rejected."})


# =====================================================
# REAL-TIME SALARY BACKGROUND THREAD
# =====================================================
def update_salary_background():
    while True:
        time.sleep(1)
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT r.id, r.time_in, r.duration, r.salary, o.name
            FROM opti_rec r
            JOIN opti o ON r.id_employee = o.id_employee
            WHERE DATE(r.time_in) = CURDATE() AND r.time_out IS NULL
        """)
        active_records = cursor.fetchall()
        settings = get_salary_settings()

        for record in active_records:
            new_duration = compute_paid_minutes(record["time_in"], None, settings)
            new_salary   = new_duration * settings["salary_per_minute"]

            cursor.execute("UPDATE opti_rec SET duration=%s, salary=%s WHERE id=%s",
                           (new_duration, new_salary, record["id"]))

            socketio.emit("salary_update", {
                "record_id": record["id"],
                "name":      record["name"],
                "duration":  new_duration,
                "salary":    new_salary,
                "time_in":   record["time_in"].strftime("%I:%M %p")
            })

        cursor.close()
        conn.close()


salary_thread = threading.Thread(target=update_salary_background, daemon=True)
salary_thread.start()


if __name__ == "__main__":
    socketio.run(app, port=5000, debug=True)
