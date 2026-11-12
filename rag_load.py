"""7단계-4 rag 스키마 적재: 규정 문서·조문 조각·임베딩을 hrdb 의 rag 스키마에 넣음.

실행: .venv/bin/python rag_load.py   (규정: rag_build.py → rag_embed.py / 법령: law_build.py → rag_embed.py data/laws 다음)

테이블
  rag.documents : 문서 1건 = 1행 (내부규정 33건 + 법령 13건. doc_kind 로 구분. 규정명, 핵심/보조/법령, 기본 카테고리, 개정·시행일, 파일, 쪽수, 조각 수,
                  법령이면 공포일·법령구분·소관부처·출처 URL)
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
LAW = HERE / "data/laws"


def read(folder, kind):
    """폴더의 조각·문서·임베딩을 읽어 doc_kind 를 붙여 돌려줌"""
    chunks = [json.loads(l) for l in open(folder / "chunks.jsonl", encoding="utf-8")]
    docs = json.load(open(folder / "documents.json", encoding="utf-8"))
    for c in chunks:
        c.setdefault("doc_kind", kind)
    for d in docs:
        d.setdefault("doc_kind", kind)
    emb = np.load(folder / "embeddings.npy")
    ids = json.load(open(folder / "embedding_ids.json"))
    meta = json.load(open(folder / "embedding_meta.json"))
    return chunks, docs, {cid: emb[i] for i, cid in enumerate(ids)}, meta


def main():
    chunks, docs, vec, meta = read(REG, "내부규정")
    if (LAW / "chunks.jsonl").exists():
        c2, d2, v2, m2 = read(LAW, "법령")
        assert m2["model"] == meta["model"] and m2["dim"] == meta["dim"], "규정과 법령의 임베딩 모델이 다름"
        chunks += c2
        docs += d2
        vec.update(v2)
    dim = meta["dim"]

    with connect(get_server()) as con:
        con.execute("CREATE EXTENSION IF NOT EXISTS vector")
        con.execute("DROP SCHEMA IF EXISTS rag CASCADE")
        con.execute("CREATE SCHEMA rag")
        con.execute("COMMENT ON SCHEMA rag IS '규정 문서 조문 조각과 임베딩(pgvector). 7단계 rag_load.py'")
        con.execute("""CREATE TABLE rag.documents (
            document_id text PRIMARY KEY, company_id text NOT NULL, doc_name text NOT NULL, tier text,
            category text, effective_date date, source_file text, file_kind text, pages integer,
            chunks integer, searchable integer, chars integer,
            doc_kind text NOT NULL, promulgated_date date, law_type text, dept text, source_url text,
            law_mst text, status text, base_date date)""")
        con.execute(f"""CREATE TABLE rag.chunks (
            chunk_id text PRIMARY KEY, document_id text NOT NULL REFERENCES rag.documents(document_id),
            company_id text NOT NULL, doc_kind text NOT NULL, doc_name text NOT NULL, article text, article_title text, part integer,
            chunk_type text NOT NULL, category text NOT NULL, searchable boolean NOT NULL,
            text text NOT NULL, effective_date date, page integer, source_file text,
            embedding vector({dim}), tsv tsvector)""")
        for col, txt in [("documents.doc_kind", "문서 종류: 내부규정(ALIO 코레일 규정을 누리철도㈜로 바꾼 것) / 법령(국가법령정보센터 원문)"),
                         ("documents.effective_date", "내부규정은 개정일, 법령은 시행일(오늘보다 뒤면 시행 예정 개정본)"),
                         ("documents.promulgated_date", "법령 공포일 (내부규정은 NULL)"),
                         ("documents.law_type", "법령 구분: 법률 / 대통령령 / 고용노동부령 등 (내부규정은 NULL)"),
                         ("documents.dept", "법령 소관부처 (내부규정은 NULL)"),
                         ("documents.source_url", "법령 원문 주소 (내부규정은 NULL)"),
                         ("documents.law_mst", "법령 일련번호(MST): 법제처 Open API에서 받은 판의 번호 (내부규정은 NULL)"),
                         ("documents.status", "법령 판 상태: 현행 (시행 예정판은 넣지 않음, 내부규정은 NULL)"),
                         ("documents.base_date", "법령 기준일: 이 날 시행 중이던 판을 받음 (내부규정은 NULL)"),
                         ("chunks.doc_kind", "문서 종류: 내부규정 / 법령 (documents.doc_kind 복사, 조인 없이 거르기용)")]:
            con.execute(f"COMMENT ON COLUMN rag.{col} IS '{txt}'")
        con.execute("COMMENT ON COLUMN rag.chunks.embedding IS %s" .replace("%s", f"'{meta['model']} {dim}차원, 정규화, 입력 = 규정명 조문 제목 + 본문'"))
        with con.cursor().copy("COPY rag.documents FROM STDIN") as cp:
            for d in docs:
                cp.write_row([d["document_id"], "nuri", d["doc_name"], d["tier"], d["category"], d["effective_date"],
                              d["source_file"], d["file_kind"], d["pages"], d["chunks"], d["searchable"], d["chars"],
                              d["doc_kind"], d.get("promulgated") or None, d.get("law_type"), d.get("dept"), d.get("source_url"),
                              d.get("law_mst"), d.get("status"), d.get("base_date")])
        with con.cursor().copy("COPY rag.chunks (chunk_id, document_id, company_id, doc_kind, doc_name, article, article_title, part, "
                               "chunk_type, category, searchable, text, effective_date, page, source_file, embedding) FROM STDIN") as cp:
            for c in chunks:
                v = vec.get(c["chunk_id"])
                cp.write_row([c["chunk_id"], c["document_id"], c["company_id"], c["doc_kind"], c["doc_name"], c["article"],
                              c["article_title"], c["part"], c["chunk_type"], c["category"], c["searchable"], c["text"],
                              c["effective_date"], c["page"], c["source_file"],
                              None if v is None else "[" + ",".join(f"{x:.6f}" for x in v) + "]"])
        con.execute("UPDATE rag.chunks SET tsv = to_tsvector('simple', coalesce(doc_name,'') || ' ' || coalesce(article_title,'') || ' ' || text)")
        con.execute("CREATE INDEX ON rag.chunks USING hnsw (embedding vector_cosine_ops)")
        con.execute("CREATE INDEX ON rag.chunks USING gin (tsv)")
        con.execute("CREATE INDEX ON rag.chunks (company_id, category)")
        con.execute("CREATE INDEX ON rag.chunks (document_id)")
        con.execute("CREATE INDEX ON rag.chunks (doc_kind)")
        n, ne, nd = con.execute("SELECT count(*), count(embedding), count(DISTINCT document_id) FROM rag.chunks").fetchone()
        bad = con.execute("SELECT count(*) FROM rag.chunks WHERE searchable AND embedding IS NULL").fetchone()[0]
    ok = n == len(chunks) and ne == len(vec) and bad == 0
    print(f"rag.documents {nd}건, rag.chunks {n}개 (임베딩 {ne}개, 검색 대상인데 임베딩 없는 조각 {bad}개) — {'일치' if ok else '불일치!'}")


if __name__ == "__main__":
    main()
