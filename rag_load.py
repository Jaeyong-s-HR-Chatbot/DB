"""7단계-4 rag 스키마 적재: 규정 문서·조문 조각·임베딩을 hrdb 의 rag 스키마에 넣음.

실행: .venv/bin/python rag_load.py   (rag_build.py → rag_embed.py 다음)

테이블
  rag.documents : 규정 1건 = 1행 (규정명, 핵심/보조, 기본 카테고리, 개정일, 파일, 쪽수, 조각 수)
  rag.chunks    : 조문 조각 1개 = 1행 (팀 "데이터 형식 정의" 칸 + 카테고리 + 검색 여부 + 임베딩 vector(1024))
색인
  임베딩 HNSW(코사인) — 의미 검색
  본문 tsvector(simple) GIN — 낱말 검색 (한국어 형태소 분석은 아직 없음, 띄어쓰기 단위)
  company_id, category, document_id
다시 실행하면 rag 스키마를 지우고 새로 만듦. 끝나면 조각 수·임베딩 수가 파일과 같은지 확인
"""
import json
from pathlib import Path

import numpy as np

from db_setup import connect, get_server

HERE = Path(__file__).parent
REG = HERE / "data/regs"


def main():
    chunks = [json.loads(l) for l in open(REG / "chunks.jsonl", encoding="utf-8")]
    docs = json.load(open(REG / "documents.json", encoding="utf-8"))
    emb = np.load(REG / "embeddings.npy")
    ids = json.load(open(REG / "embedding_ids.json"))
    meta = json.load(open(REG / "embedding_meta.json"))
    vec = {cid: emb[i] for i, cid in enumerate(ids)}
    dim = meta["dim"]

    with connect(get_server()) as con:
        con.execute("CREATE EXTENSION IF NOT EXISTS vector")
        con.execute("DROP SCHEMA IF EXISTS rag CASCADE")
        con.execute("CREATE SCHEMA rag")
        con.execute("COMMENT ON SCHEMA rag IS '규정 문서 조문 조각과 임베딩(pgvector). 7단계 rag_load.py'")
        con.execute("""CREATE TABLE rag.documents (
            document_id text PRIMARY KEY, company_id text NOT NULL, doc_name text NOT NULL, tier text,
            category text, effective_date date, source_file text, file_kind text, pages integer,
            chunks integer, searchable integer, chars integer)""")
        con.execute(f"""CREATE TABLE rag.chunks (
            chunk_id text PRIMARY KEY, document_id text NOT NULL REFERENCES rag.documents(document_id),
            company_id text NOT NULL, doc_name text NOT NULL, article text, article_title text, part integer,
            chunk_type text NOT NULL, category text NOT NULL, searchable boolean NOT NULL,
            text text NOT NULL, effective_date date, page integer, source_file text,
            embedding vector({dim}), tsv tsvector)""")
        con.execute("COMMENT ON COLUMN rag.chunks.embedding IS %s" .replace("%s", f"'{meta['model']} {dim}차원, 정규화, 입력 = 규정명 조문 제목 + 본문'"))
        with con.cursor().copy("COPY rag.documents FROM STDIN") as cp:
            for d in docs:
                cp.write_row([d["document_id"], "nuri", d["doc_name"], d["tier"], d["category"], d["effective_date"],
                              d["source_file"], d["file_kind"], d["pages"], d["chunks"], d["searchable"], d["chars"]])
        with con.cursor().copy("COPY rag.chunks (chunk_id, document_id, company_id, doc_name, article, article_title, part, "
                               "chunk_type, category, searchable, text, effective_date, page, source_file, embedding) FROM STDIN") as cp:
            for c in chunks:
                v = vec.get(c["chunk_id"])
                cp.write_row([c["chunk_id"], c["document_id"], c["company_id"], c["doc_name"], c["article"],
                              c["article_title"], c["part"], c["chunk_type"], c["category"], c["searchable"], c["text"],
                              c["effective_date"], c["page"], c["source_file"],
                              None if v is None else "[" + ",".join(f"{x:.6f}" for x in v) + "]"])
        con.execute("UPDATE rag.chunks SET tsv = to_tsvector('simple', coalesce(doc_name,'') || ' ' || coalesce(article_title,'') || ' ' || text)")
        con.execute("CREATE INDEX ON rag.chunks USING hnsw (embedding vector_cosine_ops)")
        con.execute("CREATE INDEX ON rag.chunks USING gin (tsv)")
        con.execute("CREATE INDEX ON rag.chunks (company_id, category)")
        con.execute("CREATE INDEX ON rag.chunks (document_id)")
        n, ne, nd = con.execute("SELECT count(*), count(embedding), count(DISTINCT document_id) FROM rag.chunks").fetchone()
        bad = con.execute("SELECT count(*) FROM rag.chunks WHERE searchable AND embedding IS NULL").fetchone()[0]
    ok = n == len(chunks) and ne == len(ids) and bad == 0
    print(f"rag.documents {nd}건, rag.chunks {n}개 (임베딩 {ne}개, 검색 대상인데 임베딩 없는 조각 {bad}개) — {'일치' if ok else '불일치!'}")


if __name__ == "__main__":
    main()
