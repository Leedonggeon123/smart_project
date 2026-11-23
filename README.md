# AI 기반 스마트팜 환경 관리 시스템

토마토 재배실의 센서 값을 시뮬레이션으로 만들고(아두이노 없음), 기준을 벗어나면 장치를 자동으로 켜고 끄며,
재배 문서(RAG)를 근거로 답하는 챗봇이 있는 웹 프로그램입니다.

## 파일 구성

```
smart_project/
├─ simulator.py     [1] 가상 센서 값 만들기
├─ controller.py    [2] 정상/주의/경고 판정, 장치 자동 ON/OFF
├─ database.py      [3] 데이터베이스 (테이블 9개, 읽기·쓰기 함수)
├─ main.py          [4] 프로그램 시작 (서버 + 10초마다 측정·제어)  ← 실행하는 파일
├─ rag.py           [5] 재배 자료 등록·검색
├─ chatbot.py       [6] AI 챗봇 답변
├─ test_ai.py       [7] AI 기능 테스트 (결과보고서 3번용)
├─ requirements.txt     설치할 라이브러리 목록
├─ static/          화면 (index=대시보드, chat, settings, history, style.css)
├─ docs/            재배 자료 PDF·TXT + sources.csv(제목·출처)
├─ smartfarm.db     기록 저장 파일 (실행하면 자동 생성)
└─ chroma_db/       재배 자료 검색용 데이터 (실행하면 자동 생성)
```

**코드 읽는 순서**: 번호 [1] → [7] 순서대로 보면 됩니다.
센서 값이 만들어지고(1) → 판정·제어되고(2) → 저장되고(3) → 서버가 이것을 10초마다 반복하며 화면에 보여 주고(4),
챗봇은 자료를 찾아(5) → 답을 만듭니다(6).

| 파일 | 기능 ID |
|---|---|
| simulator.py | F-01, F-07(상황 만들기) |
| controller.py | F-02, F-03 |
| rag.py | F-04 |
| chatbot.py | F-05 |
| static/index.html | F-06 |
| static/settings.html | F-07 |
| static/history.html | F-08 |
| static/chat.html | F-05 |

## 처음 한 번 준비

1. Python 3.12 설치
2. Ollama 설치 (https://ollama.com) 후 모델 받기
   ```
   ollama pull qwen2.5:3b
   ollama pull bge-m3
   ```
3. 라이브러리 설치 (smart_project 폴더에서)
   ```
   pip install -r requirements.txt
   ```

## 실행

```
python main.py
```
브라우저에서 http://localhost:8000 을 엽니다.

## AI 기능 테스트 (결과보고서 3번 채우기)

서버를 끄고(Ollama는 켠 상태) 아래를 실행하면 T-01~T-05를 차례로 실행해 `test_result.csv`로 저장합니다.
```
python test_ai.py
```
테스트용 센서 값이 기록에 몇 줄 추가됩니다(scenario 칸이 TEST).

## 따로 확인해 보기 (웹 없이)

- `python controller.py` : 콘솔에서 측정 → 판정 → 장치 ON/OFF 반복 확인
- `python rag.py` : 문서 등록과 검색만 확인
- `python chatbot.py` : 콘솔에서 챗봇에게 질문

## 재배 자료 넣는 법

1. 농사로 등에서 받은 PDF · TXT를 `docs` 폴더에 넣습니다.
2. `docs/sources.csv`에 파일 이름, 제목, 출처 기관, 주소, 분류(ENV/WATER/DISEASE/GENERAL)를 한 줄씩 적습니다.
3. 서버를 다시 켜면 새 문서만 자동으로 등록됩니다.
   (문서를 고치거나 지웠다면 `chroma_db` 폴더와 `smartfarm.db`를 지우고 다시 실행)

## 자주 생기는 문제

- 챗봇이 "Ollama가 실행 중인지 확인" 이라고 하면: Ollama 앱이 켜져 있는지, 모델 두 개를 받았는지 확인
- 챗봇이 "관련 내용을 찾지 못했어요" 라고 하면: docs에 관련 자료가 있는지 확인, 또는 rag.py의 MAX_DISTANCE를 0.6 정도로 올려 보기
- 처음부터 다시 시작하려면: 서버를 끄고 `smartfarm.db`와 `chroma_db` 폴더 삭제

선택 기능 F-09(잎 사진 진단)는 아직 넣지 않았습니다. 필수 기능을 다 만든 뒤 추가합니다.
