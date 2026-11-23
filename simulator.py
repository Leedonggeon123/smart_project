"""[1] 가상 센서 (F-01)

아두이노 대신, 이전 값에서 조금씩 바뀐 센서 값을 만든다.
켜져 있는 장치의 효과(환기팬 → 온도 하강 등)도 여기서 반영한다.
"""
import random
from datetime import datetime

# 시작 값
START = {"temperature": 24.0, "humidity": 65.0, "soil_moisture": 50.0, "light": 20000}

# 값이 넘어가면 안 되는 범위 (데이터 정의서 4번 시트)
LIMITS = {"temperature": (-5, 45), "humidity": (0, 100), "soil_moisture": (0, 100), "light": (0, 100000)}

# 시연용 상황 만들기 (F-07)
SCENARIOS = {
    "HEATWAVE": {"temperature": 33.0, "light": 60000},
    "DROUGHT": {"soil_moisture": 25.0},
    "COLD": {"temperature": 14.0},
    "HUMID": {"humidity": 90.0},
}


def clamp(key, value):
    low, high = LIMITS[key]
    return max(low, min(high, value))


def make_next(prev, devices):
    """이전 값(prev)과 장치 상태(devices)로 다음 센서 값을 만든다"""
    if prev is None:
        prev = START
    hour = datetime.now().hour
    is_day = 6 <= hour < 18

    # 1) 환경이 저절로 변함 (낮에는 덥고 밝아지고, 밤에는 식고 어두워지는 쪽으로 조금씩 끌려감)
    target_temp = 30 if is_day else 16
    target_light = 25000 if is_day else 0
    temp = prev["temperature"] + (target_temp - prev["temperature"]) * 0.05 + random.uniform(-0.3, 0.3)
    hum = prev["humidity"] + (70 - prev["humidity"]) * 0.05 + random.uniform(-1.0, 1.0)
    soil = prev["soil_moisture"] - random.uniform(0.2, 1.5)       # 흙은 점점 마름
    light = prev["light"] + (target_light - prev["light"]) * 0.2 + (random.uniform(-2000, 2000) if is_day else 0)

    # 2) 켜진 장치의 효과 반영
    if devices.get("FAN"):
        temp -= 2.0
        hum -= 3.0
    if devices.get("HEATER"):
        temp += 1.5
    if devices.get("PUMP"):
        soil += 6.0
    if devices.get("LED"):
        light += 8000

    return {
        "temperature": round(clamp("temperature", temp), 1),
        "humidity": round(clamp("humidity", hum), 1),
        "soil_moisture": round(clamp("soil_moisture", soil), 1),
        "light": int(clamp("light", light)),
    }


def apply_scenario(values, scenario):
    """상황 만들기를 고르면 해당 값으로 바로 바꾼다"""
    if scenario in SCENARIOS:
        values = {**values, **SCENARIOS[scenario]}
    return values
