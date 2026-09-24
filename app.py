import csv
import json
import math
import hmac
import io
import os
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from datetime import date, datetime
from functools import wraps
from urllib.parse import parse_qs, urlparse, urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from flask import Flask, jsonify, render_template, request, Response, redirect, session, url_for

DATABASE_URL = os.environ.get("DATABASE_URL")
LINE_LIFF_ID = os.environ.get("LINE_LIFF_ID", "")
LINE_LOGIN_CHANNEL_ID = os.environ.get("LINE_LOGIN_CHANNEL_ID", "")
app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.secret_key = os.environ.get("SECRET_KEY", "replace-this-secret-before-public-deploy")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("RENDER") == "true",
)
ADMIN_PIN = os.environ.get("ADMIN_PIN", "1111")

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("is_admin"):
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify(error="กรุณาเข้าสู่ระบบผู้ดูแล"), 401
        return redirect(url_for("admin_login"))
    return wrapped

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    if not DATABASE_URL:
        return
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            student_code VARCHAR UNIQUE,
            room VARCHAR NOT NULL,
            number VARCHAR,
            full_name VARCHAR NOT NULL,
            updated_at VARCHAR NOT NULL,
            source_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            name VARCHAR NOT NULL,
            event_date VARCHAR NOT NULL,
            UNIQUE(name, event_date)
        );
        CREATE TABLE IF NOT EXISTS attendance (
            id SERIAL PRIMARY KEY,
            student_id INTEGER NOT NULL,
            event_id INTEGER NOT NULL,
            status VARCHAR NOT NULL CHECK(status IN ('present','late','absent')),
            checked_at VARCHAR NOT NULL,
            note VARCHAR DEFAULT '',
            UNIQUE(student_id, event_id),
            FOREIGN KEY(student_id) REFERENCES students(id),
            FOREIGN KEY(event_id) REFERENCES events(id)
        );
        CREATE TABLE IF NOT EXISTS room_sources (
            id SERIAL PRIMARY KEY,
            room VARCHAR NOT NULL UNIQUE,
            sheet_url VARCHAR NOT NULL,
            gid VARCHAR NOT NULL DEFAULT '0',
            updated_at VARCHAR NOT NULL
        );
        CREATE TABLE IF NOT EXISTS student_line_accounts (
            id SERIAL PRIMARY KEY,
            student_id INTEGER NOT NULL UNIQUE,
            line_user_id VARCHAR NOT NULL UNIQUE,
            display_name VARCHAR,
            picture_url TEXT,
            linked_at VARCHAR NOT NULL,
            last_login_at VARCHAR NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id)
        );
    """)
    # เติมโค้ด 4 บรรทัดนี้เข้าไป เพื่อเพิ่มคอลัมน์ GPS และ OTP
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS lat FLOAT;")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS lng FLOAT;")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS radius INTEGER DEFAULT 100;")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS otp VARCHAR;")
    conn.commit()
    conn.close()

def normalized(row, *keys):
    lowered = {str(k).strip().lower(): str(v).strip() for k, v in row.items() if k}
    for key in keys:
        if key.lower() in lowered and lowered[key.lower()]:
            return lowered[key.lower()]
    return ""

def google_csv_url(url, gid):
    if "docs.google.com/spreadsheets" not in url:
        return url
    parsed = urlparse(url)
    parts = parsed.path.split("/")
    try:
        sheet_id = parts[parts.index("d") + 1]
    except (ValueError, IndexError):
        raise ValueError("ลิงก์ Google Sheet ไม่ถูกต้อง")
    query_gid = parse_qs(parsed.query).get("gid", [gid or "0"])[0]
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={query_gid}"

def sync_roster(sheet_url, gid="0", forced_room=None, source_id=None):
    with urlopen(google_csv_url(sheet_url, gid), timeout=20) as response:
        content = response.read().decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(content)))
    if not rows:
        raise ValueError("ไม่พบข้อมูลในชีต")
    cleaned = []
    for i, row in enumerate(rows, start=1):
        room = forced_room or normalized(row, "ห้อง", "ชั้น", "room", "class")
        number = normalized(row, "เลขที่", "no", "number")
        code = normalized(row, "รหัสนักเรียน", "student id", "student_id", "id") or f"sheet-{room}-{number}-{i}"
        name = normalized(row, "ชื่อ-นามสกุล", "ชื่อ นามสกุล", "ชื่อ", "full name", "name", "student name")
        if room and name:
            cleaned.append((code, room, number, name, source_id, datetime.now().isoformat(timespec="seconds")))
    if not cleaned:
        raise ValueError("ต้องมีคอลัมน์อย่างน้อย ‘ห้อง’ และ ‘ชื่อ-นามสกุล’")
    
    conn = get_db()
    cur = conn.cursor()
    execute_values(
        cur,
        """INSERT INTO students(student_code, room, number, full_name, source_id, updated_at)
        VALUES %s
        ON CONFLICT(student_code) DO UPDATE SET room=excluded.room, number=excluded.number,
        full_name=excluded.full_name, source_id=excluded.source_id, updated_at=excluded.updated_at""",
        cleaned
    )
    conn.commit()
    conn.close()
    return len(cleaned)

def get_or_create_event(name, event_date):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("INSERT INTO events(name,event_date) VALUES (%s,%s) ON CONFLICT (name, event_date) DO NOTHING", (name.strip(), event_date))
    cur.execute("SELECT * FROM events WHERE name=%s AND event_date=%s", (name.strip(), event_date))
    event = cur.fetchone()
    conn.commit()
    conn.close()
    return dict(event)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/admin")
@admin_required
def admin():
    return render_template("admin.html")

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if hmac.compare_digest(request.form.get("pin", ""), ADMIN_PIN):
            session.clear()
            session["is_admin"] = True
            return redirect(url_for("admin"))
        error = "รหัสผ่านไม่ถูกต้อง ลองอีกครั้ง"
    return render_template("login.html", error=error)

@app.post("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

@app.get("/api/admin/rooms")
@admin_required
def admin_rooms():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""SELECT rs.*, COUNT(s.id) AS student_count
        FROM room_sources rs LEFT JOIN students s ON s.source_id=rs.id
        GROUP BY rs.id ORDER BY rs.room""")
    rooms = [dict(row) for row in cur.fetchall()]
    conn.close()
    return jsonify(rooms)

@app.post("/api/admin/rooms")
@admin_required
def add_room_source():
    data = request.get_json(force=True)
    sheet_url = data.get("sheet_url", "").strip()
    gid = str(data.get("gid", "0")).strip() or "0"
    
    if not sheet_url:
        return jsonify(error="กรุณาระบุลิงก์ Google Sheet"), 400
        
    try:
        with urlopen(google_csv_url(sheet_url, gid), timeout=20) as response:
            content = response.read().decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(content)))
        if not rows: return jsonify(error="ไม่พบข้อมูลในชีต"), 400
        
        room = None
        for row in rows:
            room = normalized(row, "ห้อง", "ชั้น", "room", "class")
            if room: break
        if not room: return jsonify(error="ไม่พบคอลัมน์ 'ห้อง'"), 400
        
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""INSERT INTO room_sources(room,sheet_url,gid,updated_at) VALUES (%s,%s,%s,%s)
            ON CONFLICT(room) DO UPDATE SET sheet_url=excluded.sheet_url,gid=excluded.gid,updated_at=excluded.updated_at""",
            (room, sheet_url, gid, datetime.now().isoformat(timespec="seconds")))
        cur.execute("SELECT * FROM room_sources WHERE room=%s", (room,))
        source = cur.fetchone()
        conn.commit()
        conn.close()
        
        count = sync_roster(sheet_url, gid, room, source["id"])
        return jsonify(ok=True, count=count, room=dict(source))
    except (HTTPError, URLError, ValueError) as err:
        return jsonify(error=f"ซิงก์ข้อมูลไม่สำเร็จ: {err}"), 400

@app.post("/api/admin/rooms/<int:source_id>/sync")
@admin_required
def sync_room_source(source_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM room_sources WHERE id=%s", (source_id,))
    source = cur.fetchone()
    conn.close()
    if not source:
        return jsonify(error="ไม่พบห้องเรียน"), 404
    try:
        count = sync_roster(source["sheet_url"], source["gid"], source["room"], source["id"])
        return jsonify(ok=True, count=count)
    except (HTTPError, URLError, ValueError) as err:
        return jsonify(error=str(err)), 400


@app.delete("/api/admin/rooms/<int:source_id>")
@admin_required
def delete_room_source(source_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM room_sources WHERE id=%s", (source_id,))
    if not cur.fetchone():
        conn.close(); return jsonify(error="ไม่พบห้องเรียน"), 404
    cur.execute("DELETE FROM attendance WHERE student_id IN (SELECT id FROM students WHERE source_id=%s)", (source_id,))
    cur.execute("DELETE FROM student_line_accounts WHERE student_id IN (SELECT id FROM students WHERE source_id=%s)", (source_id,))
    cur.execute("DELETE FROM students WHERE source_id=%s", (source_id,))
    cur.execute("DELETE FROM room_sources WHERE id=%s", (source_id,))
    conn.commit(); conn.close()
    return jsonify(ok=True)

@app.get("/api/bootstrap")
def bootstrap():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT COUNT(*) FROM room_sources")
    source_count = cur.fetchone()['count']
    if source_count:
        cur.execute("SELECT room FROM room_sources ORDER BY room")
    else:
        cur.execute("SELECT DISTINCT room FROM students ORDER BY room")
    rooms = [r['room'] for r in cur.fetchall()]
    
    cur.execute("SELECT * FROM events ORDER BY event_date DESC, id DESC LIMIT 30")
    events = [dict(r) for r in cur.fetchall()]
    
    cur.execute("SELECT COUNT(*) FROM students")
    total = cur.fetchone()['count']
    conn.close()
    return jsonify({"rooms": rooms, "events": events, "student_count": total, "today": date.today().isoformat()})

@app.get("/api/students")
def students():
    room, event_id = request.args.get("room", ""), request.args.get("event_id", "")
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    query = """SELECT s.*, a.status, a.checked_at, a.note FROM students s
        LEFT JOIN attendance a ON a.student_id=s.id AND a.event_id=%s"""
    params = [event_id or -1]
    if room:
        query += " WHERE s.room=%s"; params.append(room)
    else:
        cur.execute("SELECT COUNT(*) FROM room_sources")
        if cur.fetchone()['count']:
            query += " WHERE s.source_id IS NOT NULL"
    
    query += " ORDER BY s.room, CAST(NULLIF(s.number, '') AS INTEGER), s.full_name"
    cur.execute(query, params)
    result = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(result)

@app.get("/api/admin/report")
@admin_required
def admin_report():
    event_id = request.args.get("event_id", type=int)
    if not event_id: return jsonify(error="กรุณาเลือกกิจกรรม"), 400
    
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM events WHERE id=%s", (event_id,))
    event = cur.fetchone()
    if not event:
        conn.close(); return jsonify(error="ไม่พบกิจกรรม"), 404
        
    cur.execute("SELECT COUNT(*) FROM room_sources")
    source_count = cur.fetchone()['count']
    
    query = """SELECT s.room, COUNT(*) AS total,
        SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) AS present,
        SUM(CASE WHEN a.status='late' THEN 1 ELSE 0 END) AS late,
        SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) AS absent,
        SUM(CASE WHEN a.status IS NULL THEN 1 ELSE 0 END) AS unmarked
        FROM students s LEFT JOIN attendance a ON a.student_id=s.id AND a.event_id=%s"""
    if source_count:
        query += " WHERE s.source_id IS NOT NULL"
    query += " GROUP BY s.room ORDER BY s.room"
    
    cur.execute(query, (event_id,))
    rows = cur.fetchall()
    conn.close()
    
    rooms = []
    for row in rows:
        item = dict(row)
        item["attended"] = item["present"] + item["late"]
        item["percentage"] = round((item["attended"] / item["total"] * 100) if item["total"] else 0, 1)
        for status in ("present", "late", "absent", "unmarked"):
            item[f"{status}_percentage"] = round((item[status] / item["total"] * 100) if item["total"] else 0, 1)
        rooms.append(item)
        
    totals = {key: sum(room[key] for room in rooms) for key in ("total", "present", "late", "absent", "unmarked", "attended")}
    totals["percentage"] = round((totals["attended"] / totals["total"] * 100) if totals["total"] else 0, 1)
    for status in ("present", "late", "absent", "unmarked"):
        totals[f"{status}_percentage"] = round((totals[status] / totals["total"] * 100) if totals["total"] else 0, 1)
        
    return jsonify({"event": dict(event), "rooms": rooms, "totals": totals})

@app.post("/api/events")
@admin_required
def create_event():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    event_date = data.get("event_date")
    otp = data.get("otp", "").strip()
    lat, lng = data.get("lat"), data.get("lng")
    radius = data.get("radius", 100)

    if not name or not event_date:
        return jsonify(error="กรุณาระบุชื่อกิจกรรมและวันที่"), 400

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""INSERT INTO events(name, event_date, otp, lat, lng, radius) 
                       VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""", 
                    (name, event_date, otp, lat, lng, radius))
        event = cur.fetchone()
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify(error="มีกิจกรรมชื่อนี้ในวันที่เลือกแล้ว"), 400
    finally:
        conn.close()
    return jsonify(dict(event))

@app.patch("/api/admin/events/<int:event_id>")
@admin_required
def update_event(event_id):
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    event_date = data.get("event_date")
    otp = data.get("otp", "").strip()
    lat, lng = data.get("lat"), data.get("lng")
    radius = data.get("radius", 100)
    
    if not name or not event_date: return jsonify(error="กรุณาระบุชื่อกิจกรรมและวันที่"), 400
    
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("UPDATE events SET name=%s, event_date=%s, otp=%s, lat=%s, lng=%s, radius=%s WHERE id=%s RETURNING *", 
                (name, event_date, otp, lat, lng, radius, event_id))
    event = cur.fetchone()
    conn.commit()
    conn.close()
    if not event: return jsonify(error="ไม่พบกิจกรรม"), 404
    return jsonify(dict(event))
@app.delete("/api/admin/events/<int:event_id>")
@admin_required
def delete_event(event_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM events WHERE id=%s", (event_id,))
    if not cur.fetchone(): conn.close(); return jsonify(error="ไม่พบกิจกรรม"), 404
    
    cur.execute("DELETE FROM attendance WHERE event_id=%s", (event_id,))
    cur.execute("DELETE FROM events WHERE id=%s", (event_id,))
    conn.commit(); conn.close()
    return jsonify(ok=True)

@app.post("/api/attendance")
def save_attendance():
    data = request.get_json(force=True)
    if data.get("status") not in ("present", "late", "absent"): return jsonify(error="สถานะไม่ถูกต้อง"), 400
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""INSERT INTO attendance(student_id,event_id,status,checked_at,note) VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT(student_id,event_id) DO UPDATE SET status=excluded.status, checked_at=excluded.checked_at, note=excluded.note""",
        (data["student_id"], data["event_id"], data["status"], datetime.now().isoformat(timespec="seconds"), data.get("note", "")))
    conn.commit(); conn.close()
    return jsonify(ok=True)

@app.post("/api/roster/sync")
def roster_sync():
    data = request.get_json(force=True)
    url = data.get("sheet_url") or os.environ.get("SHEET_URL")
    if not url: return jsonify(error="กรุณาวางลิงก์ Google Sheet ก่อน"), 400
    try:
        count = sync_roster(url, data.get("gid", os.environ.get("SHEET_GID", "0")))
        return jsonify(ok=True, count=count)
    except (HTTPError, URLError, ValueError) as err:
        return jsonify(error=str(err)), 400

@app.get("/api/report.csv")
@admin_required
def report():
    event_id = request.args.get("event_id", type=int)
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM events WHERE id=%s", (event_id,))
    event = cur.fetchone()
    if not event: conn.close(); return jsonify(error="ไม่พบกิจกรรม"), 404
    
    cur.execute("SELECT COUNT(*) FROM room_sources")
    source_count = cur.fetchone()['count']
    
    query = """SELECT s.room,s.number,s.student_code,s.full_name,
        COALESCE(a.status,'unmarked') AS status,a.checked_at,a.note
        FROM students s LEFT JOIN attendance a ON a.student_id=s.id AND a.event_id=%s"""
    if source_count:
        query += " WHERE s.source_id IS NOT NULL"
    query += " ORDER BY s.room, CAST(NULLIF(s.number, '') AS INTEGER), s.full_name"
    
    cur.execute(query, (event_id,))
    rows = cur.fetchall()
    conn.close()
    
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["กิจกรรม", event["name"], "วันที่", event["event_date"]])
    writer.writerow(["ห้อง", "เลขที่", "รหัสนักเรียน", "ชื่อ-นามสกุล", "สถานะ", "เวลาเช็ก", "หมายเหตุ"])
    labels = {"present": "มา", "late": "สาย", "absent": "ขาด", "unmarked": "ยังไม่เช็ก"}
    for r in rows: writer.writerow([r["room"],r["number"],r["student_code"],r["full_name"],labels[r["status"]],r["checked_at"] or "",r["note"] or ""])
    filename = f"attendance-{event['event_date']}.csv"
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={filename}"})

if os.environ.get("DATABASE_URL"):
    init_db()
@app.route("/student")
def student_login_page():
    return render_template("student_login.html", liff_id=LINE_LIFF_ID)


def verify_line_id_token(id_token):
    if not LINE_LOGIN_CHANNEL_ID:
        raise ValueError("ยังไม่ได้ตั้งค่า LINE_LOGIN_CHANNEL_ID")
    body = urlencode({"id_token": id_token, "client_id": LINE_LOGIN_CHANNEL_ID}).encode("utf-8")
    request_obj = Request(
        "https://api.line.me/oauth2/v2.1/verify",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request_obj, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as err:
        raise ValueError("LINE Login หมดอายุหรือไม่ถูกต้อง") from err


@app.post("/api/student/line-auth")
def student_line_auth():
    data = request.get_json(force=True)
    id_token = str(data.get("id_token", "")).strip()
    student_code = str(data.get("student_code", "")).strip()
    if not id_token:
        return jsonify(error="ไม่พบข้อมูลยืนยันตัวตนจาก LINE"), 400
    try:
        line_profile = verify_line_id_token(id_token)
    except (ValueError, URLError) as err:
        return jsonify(error=str(err)), 401

    line_user_id = line_profile.get("sub")
    if not line_user_id:
        return jsonify(error="LINE ไม่ส่งรหัสผู้ใช้กลับมา"), 401

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""SELECT s.* FROM student_line_accounts la
        JOIN students s ON s.id=la.student_id WHERE la.line_user_id=%s""", (line_user_id,))
    student = cur.fetchone()
    now = datetime.now().isoformat(timespec="seconds")
    if student:
        cur.execute("""UPDATE student_line_accounts SET display_name=%s,picture_url=%s,last_login_at=%s
            WHERE line_user_id=%s""", (line_profile.get("name"), line_profile.get("picture"), now, line_user_id))
        conn.commit(); conn.close()
        session["student_id"] = student["id"]
        session["student_name"] = student["full_name"]
        session["line_user_id"] = line_user_id
        return jsonify(ok=True, linked=True, student_name=student["full_name"])

    if not student_code:
        conn.close()
        return jsonify(ok=True, linked=False, needs_student_code=True,
            line_name=line_profile.get("name"), picture=line_profile.get("picture"))

    cur.execute("SELECT * FROM students WHERE student_code=%s", (student_code,))
    student = cur.fetchone()
    if not student:
        conn.close(); return jsonify(error="ไม่พบรหัสนักเรียนนี้ในรายชื่อ"), 404
    cur.execute("SELECT line_user_id FROM student_line_accounts WHERE student_id=%s", (student["id"],))
    if cur.fetchone():
        conn.close(); return jsonify(error="รหัสนักเรียนนี้ถูกผูกกับบัญชี LINE อื่นแล้ว กรุณาติดต่อผู้ดูแล"), 409

    cur.execute("""INSERT INTO student_line_accounts(student_id,line_user_id,display_name,picture_url,linked_at,last_login_at)
        VALUES (%s,%s,%s,%s,%s,%s)""",
        (student["id"], line_user_id, line_profile.get("name"), line_profile.get("picture"), now, now))
    conn.commit(); conn.close()
    session["student_id"] = student["id"]
    session["student_name"] = student["full_name"]
    session["line_user_id"] = line_user_id
    return jsonify(ok=True, linked=True, student_name=student["full_name"])

@app.post("/api/student/login")
def student_login_api():
    return jsonify(error="กรุณาเข้าสู่ระบบผ่าน LINE"), 410


@app.post("/api/student/logout")
def student_logout():
    session.pop("student_id", None)
    session.pop("student_name", None)
    session.pop("line_user_id", None)
    return jsonify(ok=True)

# สูตรคำนวณระยะทางระหว่างพิกัด GPS 2 จุด (หน่วยเป็นเมตร)
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000 # รัศมีโลก
    phi_1, phi_2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi_1) * math.cos(phi_2) * math.sin(delta_lambda / 2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

@app.route("/student/checkin")
def student_checkin_page():
    # ถ้ายังไม่ล็อกอิน ให้เด้งกลับไปหน้าล็อกอิน
    if not session.get("student_id"):
        return redirect(url_for("student_login_page"))
    return render_template("student_checkin.html", student_name=session.get("student_name"))

@app.post("/api/student/submit_checkin")
def student_submit_checkin():
    data = request.get_json(force=True)
    student_id = session.get("student_id")
    otp = data.get("otp", "").strip()
    lat, lng = data.get("lat"), data.get("lng")
    
    if not student_id: return jsonify(error="กรุณาเข้าสู่ระบบก่อน"), 401
    if not otp or lat is None or lng is None: return jsonify(error="ข้อมูลไม่ครบถ้วน หรือยังไม่ได้ดึงพิกัด GPS"), 400
        
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # ดึงกิจกรรมของ "วันนี้" ที่รหัส OTP ตรงกัน
    today = date.today().isoformat()
    cur.execute("SELECT * FROM events WHERE event_date=%s AND otp=%s", (today, otp))
    event = cur.fetchone()
    
    if not event:
        conn.close(); return jsonify(error="รหัส OTP ไม่ถูกต้อง หรือไม่มีกิจกรรมในวันนี้"), 404
        
    # เช็คระยะทาง GPS
    event_lat, event_lng, radius = event["lat"], event["lng"], event["radius"]
    if event_lat and event_lng:
        dist = calculate_distance(lat, lng, event_lat, event_lng)
        if dist > radius:
            conn.close()
            return jsonify(error=f"คุณอยู่นอกพื้นที่จัดกิจกรรม (ห่าง {int(dist)} ม. / อนุญาต {radius} ม.)"), 403
            
    # บันทึกสถานะ "มา"
    cur.execute("""INSERT INTO attendance(student_id,event_id,status,checked_at,note) VALUES (%s,%s,'present',%s,'เช็กชื่อด้วยตัวเอง')
        ON CONFLICT(student_id,event_id) DO UPDATE SET status='present', checked_at=excluded.checked_at, note='เช็กชื่อด้วยตัวเอง'""",
        (student_id, event["id"], datetime.now().isoformat(timespec="seconds")))
    conn.commit(); conn.close()
    
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
