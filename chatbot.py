"""[6] AI 챗봇 (F-05)

질문 + 현재 센서 값 + rag.py가 찾은 문서 조각 → Ollama(qwen2.5:3b)에게 보내 답을 받는다.
"""
import json
import time
import ollama
import database as db
import rag

LLM_MODEL = "qwen2.5:3b"

SYSTEM_RULE = """너는 토마토 재배를 돕는 스마트팜 도우미다.
- 한국어로 쉽고 짧게 답한다.
- [참고 문서]에 있는 내용을 근거로 답하고, 문서에 없는 내용은 추측하지 말고 모른다고 말한다.
- [현재 재배실 상태]를 보고 지금 상황에 맞게 조언한다.
- [참고 문서]가 없으면 현재 상태에 대한 질문에만 답하고, 재배 방법을 묻는 질문에는 관련 재배 자료를 찾지 못했다고 말한다.
- 위험할 수 있는 조치는 전문가 확인을 권한다."""

DEVICE_NAME = {"FAN": "환기팬", "HEATER": "히터", "PUMP": "급수펌프", "LED": "LED 보광등"}


def status_text(sensor, devices, thresholds):
    """프롬프트에 넣을 현재 상태 문장"""
    if sensor is None:
        return "아직 측정값 없음"
    parts = []
    for key, th in thresholds.items():
        parts.append(f"{th['sensor_name']} {sensor[key]}{th['unit']} (적정 {th['min_value']:g}~{th['max_value']:g})")
    on = [DEVICE_NAME[d] for d, v in devices.items() if v] or ["없음"]
    mode = "자동" if db.get_setting("control_mode") == "AUTO" else "수동"
    return ", ".join(parts) + f" / 켜진 장치: {', '.join(on)} / 제어 모드: {mode}"


def save_chat(session_id, role, content, sources=None, snapshot=None, response_ms=None):
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO chat_history (session_id, role, content, sources, sensor_snapshot, response_ms, created_at) VALUES (?,?,?,?,?,?,?)",
        (session_id, role, content,
         json.dumps(sources, ensure_ascii=False) if sources is not None else None,
         json.dumps(snapshot, ensure_ascii=False) if snapshot is not None else None,
         response_ms, db.now()),
    )
    conn.commit()
    conn.close()


def ask(question, session_id):
    start = time.time()
    sensor = db.get_latest_sensor()
    devices = db.get_devices()
    thresholds = db.get_thresholds()
    save_chat(session_id, "user", question)

    # 1) 문서 검색
    docs = rag.search(question)
    sources = []
    for d in docs:                              # 같은 문서 · 같은 쪽은 한 번만 표시
        s = {"doc_id": d["doc_id"], "title": d["title"], "page": d["page"]}
        if s not in sources:
            sources.append(s)

    # 2) 프롬프트 만들기: 상태 + 문서 + 질문
    #    (관련 문서가 없어도 '지금 상태 요약' 같은 질문은 센서 값만으로 답할 수 있으므로 LLM을 부른다)
    if docs:
        doc_text = "\n".join(f"({i+1}) {d['title']} p.{d['page']}: {d['text']}" for i, d in enumerate(docs))
    else:
        doc_text = "(관련 재배 자료 없음)"
    prompt = f"[현재 재배실 상태]\n{status_text(sensor, devices, thresholds)}\n\n[참고 문서]\n{doc_text}\n\n[질문]\n{question}"

    # 3) Ollama 답변
    res = ollama.chat(model=LLM_MODEL,
                      messages=[{"role": "system", "content": SYSTEM_RULE}, {"role": "user", "content": prompt}],
                      options={"temperature": 0.2})
    answer = res["message"]["content"]

    ms = int((time.time() - start) * 1000)
    snapshot = {"sensor": sensor, "devices": devices}
    save_chat(session_id, "assistant", answer, sources, snapshot, ms)
    return {"answer": answer, "sources": sources, "response_ms": ms}


if __name__ == "__main__":
    # 웹 없이 콘솔에서 챗봇만 확인:  python chatbot.py
    db.init_db()
    rag.register_docs()
    while True:
        q = input("질문> ").strip()
        if q:
            r = ask(q, "console")
            print(r["answer"], "\n출처:", r["sources"], f"({r['response_ms']}ms)\n")
