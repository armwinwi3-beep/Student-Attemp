import csv
import hmac
import io
import os
import sqlite3
from datetime import date, datetime
from functools import wraps
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen
from urllib.error import HTTPError, URLError
from flask import Flask, jsonify, render_template, request, Response, redirect, session, url_for

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "attendance.db"))
app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.secret_key = os.environ.get("SECRET_KEY", "replace-this-secret-before-public-deploy")
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


def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    con = db()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT UNIQUE,
            room TEXT NOT NULL,
            number TEXT,
            full_name TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            event_date TEXT NOT NULL,
            UNIQUE(name, event_date)
        );
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            event_id INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('present','late','absent')),
            checked_at TEXT NOT NULL,
            note TEXT DEFAULT '',
            UNIQUE(student_id, event_id),
            FOREIGN KEY(student_id) REFERENCES students(id),
            FOREIGN KEY(event_id) REFERENCES events(id)
        );
        CREATE TABLE IF NOT EXISTS room_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room TEXT NOT NULL UNIQUE,
            sheet_url TEXT NOT NULL,
            gid TEXT NOT NULL DEFAULT '0',
            updated_at TEXT NOT NULL
        );
    """)
    columns = [column[1] for column in con.execute("PRAGMA table_info(students)")]
    if "source_id" not in columns:
        con.execute("ALTER TABLE students ADD COLUMN source_id INTEGER")
    con.commit()
    con.close()


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
    con = db()
    con.executemany("""INSERT INTO students(student_code, room, number, full_name, source_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(student_code) DO UPDATE SET room=excluded.room, number=excluded.number,
        full_name=excluded.full_name, source_id=excluded.source_id, updated_at=excluded.updated_at""", cleaned)
    con.commit()
    con.close()
    return len(cleaned)


def get_or_create_event(name, event_date):
    con = db()
    con.execute("INSERT OR IGNORE INTO events(name,event_date) VALUES (?,?)", (name.strip(), event_date))
    event = con.execute("SELECT * FROM events WHERE name=? AND event_date=?", (name.strip(), event_date)).fetchone()
    con.commit(); con.close()
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
    con = db()
    rooms = [dict(row) for row in con.execute("""SELECT rs.*, COUNT(s.id) AS student_count
        FROM room_sources rs LEFT JOIN students s ON s.source_id=rs.id
        GROUP BY rs.id ORDER BY rs.room""")]
    con.close()
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
        # 1. โหลดข้อมูลจากชีตเพื่อค้นหาชื่อห้องก่อน
        with urlopen(google_csv_url(sheet_url, gid), timeout=20) as response:
            content = response.read().decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(content)))
        
        if not rows:
            return jsonify(error="ไม่พบข้อมูลในชีต"), 400
            
        # 2. ค้นหาชื่อห้องจากแถวแรกที่มีข้อมูล
        room = None
        for row in rows:
            room = normalized(row, "ห้อง", "ชั้น", "room", "class")
            if room: 
                break
                
        if not room:
            return jsonify(error="ไม่พบคอลัมน์ 'ห้อง' หรือไม่มีข้อมูลในชีต"), 400
            
        # 3. บันทึกข้อมูลแหล่งที่มาของห้องลง Database
        con = db()
        con.execute("""INSERT INTO room_sources(room,sheet_url,gid,updated_at) VALUES (?,?,?,?)
            ON CONFLICT(room) DO UPDATE SET sheet_url=excluded.sheet_url,gid=excluded.gid,updated_at=excluded.updated_at""",
            (room, sheet_url, gid, datetime.now().isoformat(timespec="seconds")))
        source = con.execute("SELECT * FROM room_sources WHERE room=?", (room,)).fetchone()
        con.commit()
        con.close()
        
        # 4. ซิงก์รายชื่อนักเรียนเข้าสู่ระบบ
        count = sync_roster(sheet_url, gid, room, source["id"])
        return jsonify(ok=True, count=count, room=dict(source))
        
    except (HTTPError, URLError, ValueError) as err:
        return jsonify(error=f"ซิงก์ข้อมูลไม่สำเร็จ: {err}"), 400
@app.post("/api/admin/rooms/<int:source_id>/sync")
@admin_required
def sync_room_source(source_id):
    con = db(); source = con.execute("SELECT * FROM room_sources WHERE id=?", (source_id,)).fetchone(); con.close()
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
    con = db(); source = con.execute("SELECT * FROM room_sources WHERE id=?", (source_id,)).fetchone()
    if not source:
        con.close(); return jsonify(error="ไม่พบห้องเรียน"), 404
    con.execute("DELETE FROM attendance WHERE student_id IN (SELECT id FROM students WHERE source_id=?)", (source_id,))
    con.execute("DELETE FROM students WHERE source_id=?", (source_id,))
    con.execute("DELETE FROM room_sources WHERE id=?", (source_id,))
    con.commit(); con.close()
    return jsonify(ok=True)


@app.get("/api/bootstrap")
def bootstrap():
    con = db()
    source_count = con.execute("SELECT COUNT(*) FROM room_sources").fetchone()[0]
    if source_count:
        rooms = [r[0] for r in con.execute("SELECT room FROM room_sources ORDER BY room")]
    else:
        rooms = [r[0] for r in con.execute("SELECT DISTINCT room FROM students ORDER BY room")]
    events = [dict(r) for r in con.execute("SELECT * FROM events ORDER BY event_date DESC, id DESC LIMIT 30")]
    total = con.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    con.close()
    return jsonify({"rooms": rooms, "events": events, "student_count": total, "today": date.today().isoformat()})


@app.get("/api/students")
def students():
    room, event_id = request.args.get("room", ""), request.args.get("event_id", "")
    con = db()
    query = """SELECT s.*, a.status, a.checked_at, a.note FROM students s
        LEFT JOIN attendance a ON a.student_id=s.id AND a.event_id=?"""
    params = [event_id or -1]
    if room:
        query += " WHERE s.room=?"; params.append(room)
    elif con.execute("SELECT COUNT(*) FROM room_sources").fetchone()[0]:
        query += " WHERE s.source_id IS NOT NULL"
    query += " ORDER BY s.room, CAST(s.number AS INTEGER), s.full_name"
    result = [dict(r) for r in con.execute(query, params)]
    con.close()
    return jsonify(result)


@app.get("/api/admin/report")
@admin_required
def admin_report():
    event_id = request.args.get("event_id", type=int)
    if not event_id:
        return jsonify(error="กรุณาเลือกกิจกรรม"), 400
    con = db()
    event = con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        con.close()
        return jsonify(error="ไม่พบกิจกรรม"), 404
    source_count = con.execute("SELECT COUNT(*) FROM room_sources").fetchone()[0]
    query = """SELECT s.room, COUNT(*) AS total,
        SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) AS present,
        SUM(CASE WHEN a.status='late' THEN 1 ELSE 0 END) AS late,
        SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) AS absent,
        SUM(CASE WHEN a.status IS NULL THEN 1 ELSE 0 END) AS unmarked
        FROM students s LEFT JOIN attendance a ON a.student_id=s.id AND a.event_id=?"""
    if source_count:
        query += " WHERE s.source_id IS NOT NULL"
    query += " GROUP BY s.room ORDER BY s.room"
    rows = con.execute(query, (event_id,)).fetchall()
    con.close()
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
    if not data.get("name", "").strip() or not data.get("event_date"):
        return jsonify(error="กรุณาระบุชื่อกิจกรรมและวันที่"), 400
    return jsonify(get_or_create_event(data["name"], data["event_date"]))


@app.patch("/api/admin/events/<int:event_id>")
@admin_required
def update_event(event_id):
    data = request.get_json(force=True)
    name, event_date = data.get("name", "").strip(), data.get("event_date", "")
    if not name or not event_date:
        return jsonify(error="กรุณาระบุชื่อกิจกรรมและวันที่"), 400
    con = db()
    existing = con.execute("SELECT id FROM events WHERE id=?", (event_id,)).fetchone()
    duplicate = con.execute("SELECT id FROM events WHERE name=? AND event_date=? AND id<>?", (name, event_date, event_id)).fetchone()
    if not existing:
        con.close(); return jsonify(error="ไม่พบกิจกรรม"), 404
    if duplicate:
        con.close(); return jsonify(error="มีกิจกรรมชื่อนี้ในวันที่เลือกแล้ว"), 400
    con.execute("UPDATE events SET name=?, event_date=? WHERE id=?", (name, event_date, event_id))
    event = con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    con.commit(); con.close()
    return jsonify(dict(event))


@app.delete("/api/admin/events/<int:event_id>")
@admin_required
def delete_event(event_id):
    con = db()
    event = con.execute("SELECT id FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        con.close(); return jsonify(error="ไม่พบกิจกรรม"), 404
    con.execute("DELETE FROM attendance WHERE event_id=?", (event_id,))
    con.execute("DELETE FROM events WHERE id=?", (event_id,))
    con.commit(); con.close()
    return jsonify(ok=True)


@app.post("/api/attendance")
def save_attendance():
    data = request.get_json(force=True)
    if data.get("status") not in ("present", "late", "absent"):
        return jsonify(error="สถานะไม่ถูกต้อง"), 400
    con = db()
    con.execute("""INSERT INTO attendance(student_id,event_id,status,checked_at,note) VALUES (?,?,?,?,?)
        ON CONFLICT(student_id,event_id) DO UPDATE SET status=excluded.status, checked_at=excluded.checked_at, note=excluded.note""",
        (data["student_id"], data["event_id"], data["status"], datetime.now().isoformat(timespec="seconds"), data.get("note", "")))
    con.commit(); con.close()
    return jsonify(ok=True)


@app.post("/api/roster/sync")
def roster_sync():
    data = request.get_json(force=True)
    url = data.get("sheet_url") or os.environ.get("SHEET_URL")
    if not url:
        return jsonify(error="กรุณาวางลิงก์ Google Sheet ก่อน"), 400
    try:
        count = sync_roster(url, data.get("gid", os.environ.get("SHEET_GID", "0")))
        return jsonify(ok=True, count=count)
    except (HTTPError, URLError, ValueError) as err:
        return jsonify(error=str(err)), 400


@app.get("/api/report.csv")
@admin_required
def report():
    event_id = request.args.get("event_id", type=int)
    con = db()
    event = con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        con.close(); return jsonify(error="ไม่พบกิจกรรม"), 404
    source_count = con.execute("SELECT COUNT(*) FROM room_sources").fetchone()[0]
    query = """SELECT s.room,s.number,s.student_code,s.full_name,
        COALESCE(a.status,'unmarked') AS status,a.checked_at,a.note
        FROM students s LEFT JOIN attendance a ON a.student_id=s.id AND a.event_id=?"""
    if source_count:
        query += " WHERE s.source_id IS NOT NULL"
    query += " ORDER BY s.room, CAST(s.number AS INTEGER), s.full_name"
    rows = con.execute(query, (event_id,)).fetchall()
    con.close()
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["กิจกรรม", event["name"], "วันที่", event["event_date"]])
    writer.writerow(["ห้อง", "เลขที่", "รหัสนักเรียน", "ชื่อ-นามสกุล", "สถานะ", "เวลาเช็ก", "หมายเหตุ"])
    labels = {"present": "มา", "late": "สาย", "absent": "ขาด", "unmarked": "ยังไม่เช็ก"}
    for r in rows: writer.writerow([r["room"],r["number"],r["student_code"],r["full_name"],labels[r["status"]],r["checked_at"] or "",r["note"] or ""])
    filename = f"attendance-{event['event_date']}.csv"
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={filename}"})


init_db()
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
