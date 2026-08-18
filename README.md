# Checkin Club — เว็บเช็กชื่อนักเรียน

เว็บ Flask สำหรับเช็กชื่อนักเรียนเข้ากิจกรรม แยกตามห้อง ใช้ได้ทั้งคอมพิวเตอร์และมือถือ

## เริ่มใช้ในเครื่อง

```bash
pip install -r requirements.txt
python app.py
```

จากนั้นเปิด `http://localhost:5000`

## รูปแบบ Google Sheet

แถวแรกเป็นหัวตาราง และควรมีคอลัมน์ดังนี้ (ชื่อคอลัมน์ภาษาอังกฤษก็ใช้ได้):

| ห้อง | เลขที่ | รหัสนักเรียน | ชื่อ-นามสกุล |
|---|---:|---|---|
| ม.4/1 | 1 | 65001 | สมชาย ใจดี |

ตั้งค่าสิทธิ์ไฟล์เป็น **Anyone with the link / Viewer** แล้วกด “ซิงก์รายชื่อ” ในเว็บและวางลิงก์ Google Sheet ได้ทันที

## Deploy บน Render

1. อัปโหลดโฟลเดอร์นี้ไปยัง GitHub repository
2. ใน Render เลือก **New → Blueprint** แล้วเลือก repository หรือสร้าง Web Service ด้วย `render.yaml`
3. ใส่ `SHEET_URL` ใน Environment Variables เพื่อให้กดซิงก์ได้โดยไม่ต้องวางลิงก์ทุกครั้ง
4. หากต้องการเก็บข้อมูลถาวรบน Render ให้เพิ่ม Persistent Disk และตั้ง `DATABASE_PATH` เป็น `/var/data/attendance.db`

> Render แบบไม่มี Persistent Disk จะล้างข้อมูลที่เช็กชื่อเมื่อ service ถูก deploy ใหม่หรือ restart
