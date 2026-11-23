"""[4] 프로그램 시작 파일 (FastAPI 서버)

- 시작하면: DB 준비 → 새 재배 자료 등록 → 10초마다 controller.step() 실행
- 화면(static 폴더)과 화면이 부르는 API(/api/...)를 제공한다.
실행:  python main.py  →  브라우저에서 http://localhost:8000
"""
import asyncio
import csv
import io
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import database as db
import controller
import chatbot
import rag


async def simulator_loop():
    """F-01~F-03: 측정 → 판정 → 제어를 계속 반복"""
    while True:
        controller.step()
        await asyncio.sleep(int(db.get_setting("interval_sec")))   # 기본 10초


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    rag.register_docs()                       # 새 문서가 있으면 등록
    task = asyncio.create_task(simulator_loop())
    yield
    task.cancel()                             # 서버를 끄면 시뮬레이터도 멈춤


app = FastAPI(lifespan=lifespan)


def rows(sql, params=()):
    conn = db.get_conn()
    data = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return data


# ---------- F-06 대시보드 ----------

@app.get("/api/sensors/latest")
def sensors_latest():
    sensor = db.get_latest_sensor()
    thresholds = db.get_thresholds()
    status = {}
    if sensor:
        status, _ = controller.judge_all(sensor, thresholds)
    reasons = {r["device_id"]: r for r in rows(
        "SELECT device_id, reason, created_at FROM control_log WHERE id IN (SELECT MAX(id) FROM control_log GROUP BY device_id)")}
    return {"sensor": sensor, "status": status, "thresholds": thresholds,
            "devices": db.get_devices(), "reasons": reasons, "mode": db.get_setting("control_mode")}


@app.get("/api/sensors/recent")
def sensors_recent(minutes: int = 60):
    return rows("SELECT * FROM sensor_log WHERE measured_at >= datetime('now','localtime',?) ORDER BY id",
                (f"-{minutes} minutes",))


@app.get("/api/alerts")
def alerts(limit: int = 3):
    return rows("SELECT * FROM alert_log ORDER BY id DESC LIMIT ?", (limit,))


# ---------- F-05 챗봇 ----------

class ChatIn(BaseModel):
    session_id: str
    question: str


@app.post("/api/chat")
def chat(body: ChatIn):
    if not body.question.strip():
        return {"answer": "질문을 입력해 주세요.", "sources": [], "response_ms": 0}
    try:
        return chatbot.ask(body.question.strip(), body.session_id)
    except Exception as e:                      # Ollama가 꺼져 있을 때 등
        return {"answer": f"답변을 만들지 못했어요. Ollama가 실행 중인지 확인해 주세요. ({e})",
                "sources": [], "response_ms": 0, "error": True}


@app.get("/api/chat/history")
def chat_history(session_id: str):
    return rows("SELECT role, content, sources, created_at FROM chat_history WHERE session_id=? ORDER BY id", (session_id,))


# ---------- F-07 제어 · 설정 ----------

class ModeIn(BaseModel):
    mode: str


@app.put("/api/settings/mode")
def set_mode(body: ModeIn):
    if body.mode not in ("AUTO", "MANUAL"):
        return {"ok": False, "error": "AUTO 또는 MANUAL만 가능합니다"}
    db.set_setting("control_mode", body.mode)
    return {"ok": True, "mode": body.mode}


class DeviceIn(BaseModel):
    is_on: int


@app.put("/api/devices/{device_id}")
def set_device(device_id: str, body: DeviceIn):
    if db.get_setting("control_mode") == "AUTO":
        return {"ok": False, "error": "자동 모드에서는 바꿀 수 없습니다"}
    db.set_device(device_id, body.is_on, "사용자 조작", "MANUAL")
    return {"ok": True, "device_id": device_id, "is_on": body.is_on}


@app.get("/api/thresholds")
def get_thresholds():
    return list(db.get_thresholds().values())


class ThresholdIn(BaseModel):
    sensor_key: str
    min_value: float
    max_value: float


@app.put("/api/thresholds")
def put_thresholds(items: list[ThresholdIn]):
    for t in items:
        if t.min_value >= t.max_value:
            return {"ok": False, "error": "하한은 상한보다 작아야 합니다"}
    conn = db.get_conn()
    for t in items:
        conn.execute("UPDATE threshold SET min_value=?, max_value=?, updated_at=? WHERE sensor_key=?",
                     (t.min_value, t.max_value, db.now(), t.sensor_key))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/thresholds/reset")
def reset_thresholds():
    conn = db.get_conn()
    conn.execute("DELETE FROM threshold")
    conn.executemany("INSERT INTO threshold VALUES (?,?,?,?,?,?,?,?,?,?)", db.default_thresholds())
    conn.commit()
    conn.close()
    return {"ok": True}


class ScenarioIn(BaseModel):
    scenario: str


@app.post("/api/scenario")
def scenario(body: ScenarioIn):
    db.set_setting("scenario", body.scenario)   # 다음 측정 때 한 번 적용됨
    return {"ok": True, "scenario": body.scenario}


# ---------- F-08 이력 ----------

RANGES = {"today": "start of day", "24h": "-24 hours", "7d": "-7 days"}


@app.get("/api/history")
def history(range: str = "24h"):
    r = RANGES.get(range, "-24 hours")
    where = "WHERE {col} >= datetime('now','localtime',?)"
    return {
        "sensors": rows("SELECT * FROM sensor_log " + where.format(col="measured_at") + " ORDER BY id", (r,)),
        "controls": rows("SELECT * FROM control_log " + where.format(col="created_at") + " ORDER BY id DESC LIMIT 100", (r,)),
        "alerts": rows("SELECT * FROM alert_log " + where.format(col="created_at") + " ORDER BY id DESC LIMIT 100", (r,)),
    }


@app.get("/api/history/csv")
def history_csv(range: str = "24h"):
    data = history(range)["sensors"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["측정 시각", "온도", "습도", "토양 수분", "조도", "상태"])
    for d in data:
        writer.writerow([d["measured_at"], d["temperature"], d["humidity"], d["soil_moisture"], d["light"], d["status"]])
    return StreamingResponse(io.BytesIO(buf.getvalue().encode("utf-8-sig")), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=sensor_log.csv"})


# 화면 파일 (index.html = 대시보드). API 아래에 둬야 /api 경로가 먼저 잡힌다.
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
