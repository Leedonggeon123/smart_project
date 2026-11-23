"""[3] 데이터베이스 (SQLite, smartfarm.db)

테이블 9개를 만들고 기본값을 넣는다. 다른 파일들은 여기 있는 함수로 DB를 읽고 쓴다.
"""
import sqlite3
from datetime import datetime

DB_PATH = "smartfarm.db"


def now():
    """현재 시각을 'YYYY-MM-DD HH:MM:SS' 문자열로"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row      # 결과를 딕셔너리처럼 쓰기 위해
    return conn


def init_db():
    """테이블 9개 생성 + 비어 있으면 기본값 입력"""
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS sensor_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        measured_at TEXT NOT NULL,
        temperature REAL NOT NULL,
        humidity REAL NOT NULL,
        soil_moisture REAL NOT NULL,
        light INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'NORMAL',
        scenario TEXT DEFAULT 'NONE'
    );
    CREATE TABLE IF NOT EXISTS device_state (
        device_id TEXT PRIMARY KEY,
        device_name TEXT NOT NULL,
        is_on INTEGER NOT NULL DEFAULT 0,
        effect TEXT,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS control_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        device_id TEXT NOT NULL REFERENCES device_state(device_id),
        action TEXT NOT NULL,
        reason TEXT NOT NULL,
        trigger_type TEXT NOT NULL DEFAULT 'AUTO',
        sensor_log_id INTEGER REFERENCES sensor_log(id)
    );
    CREATE TABLE IF NOT EXISTS threshold (
        sensor_key TEXT PRIMARY KEY,
        sensor_name TEXT NOT NULL,
        unit TEXT NOT NULL,
        min_value REAL NOT NULL,
        max_value REAL NOT NULL,
        off_low REAL,
        off_high REAL,
        low_device TEXT,
        high_device TEXT,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS system_setting (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS alert_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        sensor_key TEXT NOT NULL,
        level TEXT NOT NULL,
        value REAL NOT NULL,
        message TEXT NOT NULL,
        sensor_log_id INTEGER,
        is_read INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        sources TEXT,
        sensor_snapshot TEXT,
        response_ms INTEGER,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS document (
        doc_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        source_org TEXT NOT NULL,
        source_url TEXT,
        category TEXT NOT NULL,
        crop TEXT NOT NULL DEFAULT 'tomato',
        file_name TEXT NOT NULL,
        chunk_count INTEGER NOT NULL DEFAULT 0,
        registered_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS diagnosis_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        image_path TEXT NOT NULL,
        symptom TEXT NOT NULL,
        suspected TEXT,
        advice TEXT NOT NULL,
        sources TEXT,
        sensor_snapshot TEXT
    );
    """)

    # 기본 장치 4개 (데이터 정의서 4번 시트: 장치 코드)
    if conn.execute("SELECT COUNT(*) FROM device_state").fetchone()[0] == 0:
        devices = [
            ("FAN", "환기팬", "온도 -2.0, 습도 -3.0"),
            ("HEATER", "히터", "온도 +1.5"),
            ("PUMP", "급수펌프", "토양 수분 +6.0"),
            ("LED", "LED 보광등", "조도 +8000"),
        ]
        for d in devices:
            conn.execute("INSERT INTO device_state VALUES (?,?,0,?,?)", (*d, now()))

    # 기본 기준값 (데이터 정의서 5번 시트 - 예시 값, 재배 자료 보고 수정)
    if conn.execute("SELECT COUNT(*) FROM threshold").fetchone()[0] == 0:
        conn.executemany("INSERT INTO threshold VALUES (?,?,?,?,?,?,?,?,?,?)", default_thresholds())

    # 기본 설정
    defaults = {"control_mode": "AUTO", "interval_sec": "10", "crop": "tomato", "scenario": "NONE"}
    for k, v in defaults.items():
        conn.execute("INSERT OR IGNORE INTO system_setting VALUES (?,?,?)", (k, v, now()))

    conn.commit()
    conn.close()


def default_thresholds():
    t = now()
    return [
        # sensor_key, 이름, 단위, 하한, 상한, 하한OFF, 상한OFF, 하한장치, 상한장치, 수정시각
        ("temperature", "온도", "℃", 18, 28, 20, 26, "HEATER", "FAN", t),
        ("humidity", "습도", "%", 60, 80, None, 75, None, "FAN", t),
        ("soil_moisture", "토양 수분", "%", 35, 60, 45, None, "PUMP", None, t),
        ("light", "조도", "lux", 10000, 50000, 15000, None, "LED", None, t),
    ]


# ---------- 자주 쓰는 조회 · 저장 함수 ----------

def get_setting(key):
    conn = get_conn()
    row = conn.execute("SELECT value FROM system_setting WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def set_setting(key, value):
    conn = get_conn()
    conn.execute("UPDATE system_setting SET value=?, updated_at=? WHERE key=?", (str(value), now(), key))
    conn.commit()
    conn.close()


def get_thresholds():
    """{'temperature': {...}, 'humidity': {...}, ...} 형태로 반환"""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM threshold").fetchall()
    conn.close()
    return {r["sensor_key"]: dict(r) for r in rows}


def get_devices():
    """{'FAN': 1, 'HEATER': 0, ...} 형태로 반환"""
    conn = get_conn()
    rows = conn.execute("SELECT device_id, is_on FROM device_state").fetchall()
    conn.close()
    return {r["device_id"]: r["is_on"] for r in rows}


def get_latest_sensor():
    conn = get_conn()
    row = conn.execute("SELECT * FROM sensor_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def set_device(device_id, is_on, reason, trigger_type="AUTO", sensor_log_id=None):
    """장치 상태를 바꾸고 control_log에 기록"""
    conn = get_conn()
    conn.execute("UPDATE device_state SET is_on=?, updated_at=? WHERE device_id=?", (is_on, now(), device_id))
    conn.execute(
        "INSERT INTO control_log (created_at, device_id, action, reason, trigger_type, sensor_log_id) VALUES (?,?,?,?,?,?)",
        (now(), device_id, "ON" if is_on else "OFF", reason, trigger_type, sensor_log_id),
    )
    conn.commit()
    conn.close()
