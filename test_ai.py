"""[7] AI 기능 테스트 (결과보고서 3번 T-01 ~ T-05 채우기용)

실행 전: 서버(main.py)는 끄고, Ollama는 켜 둔다.
실행:    python test_ai.py
결과:    화면에 출력 + test_result.csv 파일로 저장 (엑셀로 열 수 있음)
"""
import csv
import database as db
import rag
import chatbot

# 테스트할 재배실 상태 (온도, 습도, 토양 수분, 조도)
NORMAL = (24.0, 65.0, 48.0, 25000)   # 모두 정상
HOT = (31.5, 70.0, 45.0, 30000)      # 온도 경고
DRY = (25.0, 62.0, 30.0, 25000)      # 토양 수분 주의

TESTS = [
    # 항목, 상태, 질문, 기대 결과
    ("T-01", HOT, "지금 온도가 높은데 어떻게 관리해야 해?", "현재 온도를 언급하고 문서 근거로 대처법, 출처 표시"),
    ("T-02", DRY, "물은 언제 줘야 해?", "관수 관련 문서를 찾아 답변, 출처 표시"),
    ("T-03", NORMAL, "오늘 주식 시장은 어때?", "관련 자료가 없다고 말하고 지어내지 않음 (출처 없음)"),
    ("T-04", NORMAL, "지금 재배실 상태 괜찮아?", "정상 상태라고 답변"),
    ("T-04", HOT, "지금 재배실 상태 괜찮아?", "온도 문제를 짚어 답변 (위 답변과 달라야 함)"),
]


def set_state(state):
    """테스트용 센서 값을 sensor_log에 넣어 '현재 상태'로 만든다"""
    t, h, s, l = state
    conn = db.get_conn()
    conn.execute("INSERT INTO sensor_log (measured_at, temperature, humidity, soil_moisture, light, status, scenario) "
                 "VALUES (?,?,?,?,?,'NORMAL','TEST')", (db.now(), t, h, s, l))
    conn.commit()
    conn.close()


db.init_db()
rag.register_docs()
rows, times = [], []
for no, state, question, expect in TESTS:
    set_state(state)
    r = chatbot.ask(question, "test")
    found = "있음" if r["sources"] else "없음"
    times.append(r["response_ms"])
    print(f"\n[{no}] 상태 {state} / 질문: {question}\n  문서: {found} {r['sources']}\n  답변: {r['answer']}\n  시간: {r['response_ms']}ms")
    rows.append([no, str(state), question, expect, r["answer"], found,
                 ", ".join(x["title"] for x in r["sources"]), r["response_ms"]])

avg = sum(times) / len(times) / 1000
print(f"\n[T-05] 평균 응답 시간: {avg:.1f}초 (기준 30초 이내)")
rows.append(["T-05", "", "위 질문들의 평균 응답 시간", "30초 이내", f"{avg:.1f}초", "", "", ""])

with open("test_result.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["항목", "센서 상태(온도,습도,토양수분,조도)", "질문", "기대 결과", "실제 답변", "문서 찾음", "출처", "시간(ms)"])
    w.writerows(rows)
print("test_result.csv 저장 완료")
