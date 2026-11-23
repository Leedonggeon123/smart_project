"""[5] 재배 자료 등록과 검색 (F-04, RAG)

등록: docs 폴더 PDF/TXT → 글자 추출 → 500자씩 자르기 → bge-m3로 숫자 벡터 변환 → ChromaDB 저장
검색: 질문도 벡터로 바꿔서, 가장 비슷한 조각 4개를 찾는다.
"""
import csv
import os
import chromadb
import ollama
from pypdf import PdfReader
import database as db

DOCS_DIR = "docs"
EMBED_MODEL = "bge-m3"
CHUNK_SIZE = 500       # 조각 크기
OVERLAP = 100          # 앞뒤로 겹치는 글자 수
TOP_K = 4              # 검색해서 가져올 조각 수
MAX_DISTANCE = 0.5     # 이보다 멀면 '관련 문서 없음' (테스트하면서 조정)

client = chromadb.PersistentClient(path="chroma_db")
collection = client.get_or_create_collection("tomato_docs", metadata={"hnsw:space": "cosine"})


def embed(text):
    """글자를 숫자 벡터(1024개)로 바꾼다"""
    return ollama.embed(model=EMBED_MODEL, input=text)["embeddings"][0]


def read_pages(path):
    """파일에서 [(쪽 번호, 글자), ...] 를 읽는다. TXT는 쪽 번호 0"""
    if path.lower().endswith(".pdf"):
        reader = PdfReader(path)
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    with open(path, encoding="utf-8") as f:
        return [(0, f.read())]


def split_text(text):
    """500자씩 자르되 100자씩 겹치게"""
    text = " ".join(text.split())          # 줄바꿈 · 여러 칸 공백 정리
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + CHUNK_SIZE])
        start += CHUNK_SIZE - OVERLAP
    return [c for c in chunks if len(c) > 30]


def read_sources():
    """docs/sources.csv 에 적어 둔 문서 정보(제목, 출처, 분류)를 읽는다"""
    info = {}
    path = os.path.join(DOCS_DIR, "sources.csv")
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                info[row["file_name"]] = row
    return info


def register_docs():
    """아직 등록 안 된 문서만 ChromaDB에 저장"""
    sources = read_sources()
    conn = db.get_conn()
    done = {r["file_name"] for r in conn.execute("SELECT file_name FROM document")}
    count = conn.execute("SELECT COUNT(*) FROM document").fetchone()[0]

    for file_name in sorted(os.listdir(DOCS_DIR)):
        if not file_name.lower().endswith((".pdf", ".txt")) or file_name in done:
            continue
        count += 1
        doc_id = f"DOC{count:03d}"
        info = sources.get(file_name, {})
        title = info.get("title") or os.path.splitext(file_name)[0]
        source_org = info.get("source_org") or "미상"
        category = info.get("category") or "GENERAL"

        n = 0
        for page, text in read_pages(os.path.join(DOCS_DIR, file_name)):
            for chunk in split_text(text):
                collection.add(
                    ids=[f"{doc_id}_{n:04d}"],
                    documents=[chunk],
                    embeddings=[embed(chunk)],
                    metadatas=[{"doc_id": doc_id, "title": title, "source_org": source_org,
                                "category": category, "crop": "tomato", "page": page, "chunk_index": n}],
                )
                n += 1
        conn.execute("INSERT INTO document VALUES (?,?,?,?,?,?,?,?,?)",
                     (doc_id, title, source_org, info.get("source_url"), category, "tomato", file_name, n, db.now()))
        conn.commit()
        print(f"[문서 등록] {file_name} → 조각 {n}개")
    conn.close()


def search(question):
    """질문과 비슷한 문서 조각을 찾는다. 반환: [{'text','title','page','distance'}, ...]"""
    if collection.count() == 0:
        return []
    result = collection.query(query_embeddings=[embed(question)], n_results=min(TOP_K, collection.count()))
    # 터미널에 거리를 보여 줘서 MAX_DISTANCE를 조정할 때 참고한다 (작을수록 비슷함)
    print(f"[검색] {question[:20]} → 거리 {[round(x, 3) for x in result['distances'][0]]} (기준 {MAX_DISTANCE})")
    found = []
    for text, meta, dist in zip(result["documents"][0], result["metadatas"][0], result["distances"][0]):
        if dist <= MAX_DISTANCE:
            found.append({"text": text, "title": meta["title"], "page": meta["page"],
                          "doc_id": meta["doc_id"], "distance": round(dist, 3)})
    return found


if __name__ == "__main__":
    # 문서 등록 + 검색만 따로 확인:  python rag.py
    db.init_db()
    register_docs()
    for r in search("온도가 너무 높으면 어떻게 해?"):
        print(r["distance"], r["title"], r["text"][:60])
