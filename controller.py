"""[2] 상태 판정(F-02)과 자동 제어(F-03)

step() 한 번 = 측정 1회:  센서 값 만들기 → 정상/주의/경고 판정 → 기록 → 장치 켜고 끄기
main.py가 10초마다 step()을 부른다.
"""
from datetime import datetime
import database as db
import simulator

LEVEL_ORDER = {"NORMAL": 0, "CAUTION": 1, "WARNING": 2}

last_status = {}      # 센서별 직전 상태 (상태가 바뀌었는지 알기 위해)


# ---------- F-02 상태 판정 ----------

def judge(value, th):
    """정상 / 주의(범위 밖) / 경고(범위에서 10% 이상 벗어남)"""
    low, high = th["min_value"], th["max_value"]
    if low <= value <= high:
        return "NORMAL"
    if value > high and value > high * 1.1:
        return "WARNING"
    if value < low and value < low * 0.9:
        return "WARNING"
    return "CAUTION"


def judge_all(values, thresholds):
    """센서 4개를 모두 판정하고, 가장 나쁜 상태를 전체 상태로"""
    result = {key: judge(values[key], th) for key, th in thresholds.items()}
    overall = max(result.values(), key=lambda s: LEVEL_ORDER[s])
    return result, overall


def save_alerts(values, status, thresholds, sensor_log_id):
    """상태가 바뀐 센서만 alert_log에 저장 (같은 상태가 이어지면 다시 저장하지 않음)"""
    conn = db.get_conn()
    for key, level in status.items():
        before = last_status.get(key, "NORMAL")
        last_status[key] = level
        if level == before:
            continue
        th = thresholds[key]
        value = f"{th['sensor_name']} {values[key]}{th['unit']}"
        if level == "NORMAL":
            level, text = "RECOVER", f"{value} - 정상 범위 복귀"
        elif values[key] > th["max_value"]:
            text = f"{value} - 상한 {th['max_value']:g}{th['unit']} 초과"
        else:
            text = f"{value} - 하한 {th['min_value']:g}{th['unit']} 미달"
        conn.execute(
            "INSERT INTO alert_log (created_at, sensor_key, level, value, message, sensor_log_id) VALUES (?,?,?,?,?,?)",
            (db.now(), key, level, values[key], text, sensor_log_id),
        )
    conn.commit()
    conn.close()


# ---------- F-03 자동 제어 ----------

def decide(values, th, devices):
    """장치별로 켤지 끌지 정한다. 반환: {장치: (새 상태, 이유)}  (바뀌는 것만)"""
    t, h, s, l = values["temperature"], values["humidity"], values["soil_moisture"], values["light"]
    T, H, S, L = th["temperature"], th["humidity"], th["soil_moisture"], th["light"]
    is_day = 6 <= datetime.now().hour < 18
    changes = {}

    # 환기팬: 온도나 습도가 상한을 넘으면 ON, 둘 다 OFF 기준 아래로 내려오면 OFF
    if not devices["FAN"] and (t > T["max_value"] or h > H["max_value"]):
        reason = f"온도 {t}℃ > 상한 {T['max_value']:g}℃" if t > T["max_value"] else f"습도 {h}% > 상한 {H['max_value']:g}%"
        changes["FAN"] = (1, reason)
    elif devices["FAN"] and t <= T["off_high"] and h <= H["off_high"]:
        changes["FAN"] = (0, f"온도 {t}℃, 습도 {h}% 목표 복귀")

    # 히터: 온도 하한 미달이면 ON, OFF 기준 이상이면 OFF (환기팬과 동시에 켜지 않음)
    if not devices["HEATER"] and t < T["min_value"]:
        changes["HEATER"] = (1, f"온도 {t}℃ < 하한 {T['min_value']:g}℃")
        if devices["FAN"]:
            changes["FAN"] = (0, "히터 가동으로 환기팬 정지")
    elif devices["HEATER"] and t >= T["off_low"]:
        changes["HEATER"] = (0, f"온도 {t}℃ 목표 복귀")

    # 급수펌프: 토양 수분 하한 미달이면 ON
    if not devices["PUMP"] and s < S["min_value"]:
        changes["PUMP"] = (1, f"토양수분 {s}% < 하한 {S['min_value']:g}%")
    elif devices["PUMP"] and s >= S["off_low"]:
        changes["PUMP"] = (0, f"토양수분 {s}% 목표 복귀")

    # LED 보광등: 낮(06~18시)에 조도 하한 미달이면 ON, 밤에는 끔
    if not devices["LED"] and is_day and l < L["min_value"]:
        changes["LED"] = (1, f"조도 {l}lux < 하한 {L['min_value']:g}lux")
    elif devices["LED"] and (l >= L["off_low"] or not is_day):
        changes["LED"] = (0, "조도 목표 복귀" if is_day else "야간 소등")

    return changes


# ---------- 10초마다 실행되는 한 주기 ----------

def step():
    thresholds = db.get_thresholds()
    devices = db.get_devices()
    prev = db.get_latest_sensor()

    # 1) 새 센서 값 만들기 (+ 상황 만들기가 있으면 적용하고 한 번만 쓰고 지움)
    values = simulator.make_next(prev, devices)
    scenario = db.get_setting("scenario")
    if scenario != "NONE":
        values = simulator.apply_scenario(values, scenario)
        db.set_setting("scenario", "NONE")

    # 2) 상태 판정 후 sensor_log 저장
    status, overall = judge_all(values, thresholds)
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO sensor_log (measured_at, temperature, humidity, soil_moisture, light, status, scenario) VALUES (?,?,?,?,?,?,?)",
        (db.now(), values["temperature"], values["humidity"], values["soil_moisture"], values["light"], overall, scenario),
    )
    sensor_log_id = cur.lastrowid
    conn.commit()
    conn.close()
    save_alerts(values, status, thresholds, sensor_log_id)

    # 3) 자동 모드면 장치 제어
    if db.get_setting("control_mode") == "AUTO":
        for device_id, (is_on, reason) in decide(values, thresholds, devices).items():
            db.set_device(device_id, is_on, reason, "AUTO", sensor_log_id)

    return values, status


if __name__ == "__main__":
    # 웹 없이 콘솔에서 자동 제어만 확인해 보기:  python controller.py
    import time
    db.init_db()
    while True:
        v, st = step()
        print(v, st, db.get_devices())
        time.sleep(int(db.get_setting("interval_sec")))
