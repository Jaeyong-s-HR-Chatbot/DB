"""항 단위 조각(data/hang, rag_rechunk.py 결과)을 hrdb 의 rag 스키마에 넣기.

실행 (torch + sentence-transformers 가 있는 환경, 예: backend 가상환경):
  set HRDB_URL=postgresql://hr:hrpass@localhost:5433/hrdb
  ..\\backend\\.venv\\Scripts\\python rag_load_hang.py

하는 일
1. 예전 조문 단위 rag.chunks 를 rag.chunks_article 로 이름만 바꿔 남김 (처음 한 번. 비교·되돌리기용)
2. 글자가 같은 조각은 예전 임베딩을 그대로 쓰고, 새로 생긴 조각만 BGE-M3 로 임베딩 (data/hang/embeddings.npy 에 저장해 다시 실행하면 재사용)
3. rag.chunks 를 새로 만듦: 예전 칸 그대로 + article_id(조문 묶음), hang(항 번호), granularity(항/조/그대로)
   → 기존 검색 코드(SELECT … FROM rag.chunks WHERE searchable …)는 고치지 않아도 돌아감
4. rag.articles: 조문 전체 원문. 항으로 찾고 답할 때 같은 article_id 의 조문 전체를 붙여 줄 수 있음
5. rag.documents 의 조각 수 갱신
되돌리기: DROP TABLE rag.chunks; ALTER TABLE rag.chunks_article RENAME TO chunks;
"""
import json
import os
import time
from pathlib import Path

import numpy as np
import psycopg

HERE = Path(__file__).parent
HANG = HERE / "data/hang"
URL = os.environ.get("HRDB_URL", "postgresql://hr:hrpass@localhost:5433/hrdb")
MODEL = "BAAI/bge-m3"


def doc_text(c):  # rag_embed.py 와 같은 입력 형식
    head = f"{c['doc_name']} {c['article']} {c['article_title']}".strip()
    return f"{head}\n{c['text']}"


def vec_lit(v):
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def main():
    chunks = [json.loads(l) for l in open(HANG / "chunks.jsonl", encoding="utf-8")]
    articles = [json.loads(l) for l in open(HANG / "articles.jsonl", encoding="utf-8")]
    docs = json.load(open(HANG / "documents.json", encoding="utf-8"))

    with psycopg.connect(URL, autocommit=True) as con:
        has_old = con.execute("SELECT to_regclass('rag.chunks_article')").fetchone()[0]
        if not has_old:
            con.execute("ALTER TABLE rag.chunks RENAME TO chunks_article")
            con.execute("COMMENT ON TABLE rag.chunks_article IS '조문 단위 예전 조각 (rag_load_hang.py 가 남김, 비교·되돌리기용)'")
            print("예전 rag.chunks → rag.chunks_article 로 보관")
        old = {r[0]: (r[1], r[2]) for r in con.execute(
            "SELECT chunk_id, text, embedding::text FROM rag.chunks_article WHERE embedding IS NOT NULL")}

    # 임베딩: 예전 것 재사용 → 저장해 둔 새 임베딩 재사용 → 나머지만 계산
    cache = {}
    if (HANG / "embeddings.npy").exists():
        ids = json.load(open(HANG / "embedding_ids.json", encoding="utf-8"))
        texts = json.load(open(HANG / "embedding_texts.json", encoding="utf-8"))
        arr = np.load(HANG / "embeddings.npy")
        cache = {cid: (t, arr[i]) for i, (cid, t) in enumerate(zip(ids, texts))}
    emb, todo = {}, []
    for c in chunks:
        if not c["searchable"]:
            continue
        o = old.get(c["chunk_id"])
        if o and o[0] == c["text"]:
            emb[c["chunk_id"]] = o[1]
        elif c["chunk_id"] in cache and cache[c["chunk_id"]][0] == doc_text(c):
            emb[c["chunk_id"]] = vec_lit(cache[c["chunk_id"]][1])
        else:
            todo.append(c)
    print(f"검색 조각 {len(emb) + len(todo)}개: 임베딩 재사용 {len(emb)}, 새로 계산 {len(todo)}")
    if todo:
        import torch
        from sentence_transformers import SentenceTransformer
        torch.set_num_threads(os.cpu_count() or 4)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        t0 = time.time()
        model = SentenceTransformer(MODEL, device=device)
        model.max_seq_length = 4096  # 긴 별표(최대 약 3,200토큰)가 잘리지 않게
        todo.sort(key=lambda c: len(doc_text(c)))  # 길이 비슷한 것끼리 묶으면 CPU 에서 빠름
        new = model.encode([doc_text(c) for c in todo], batch_size=16, normalize_embeddings=True,
                           show_progress_bar=True, convert_to_numpy=True).astype(np.float32)
        print(f"BGE-M3 {len(todo)}개 {time.time() - t0:.0f}초 ({device})")
        for c, v in zip(todo, new):
            emb[c["chunk_id"]] = vec_lit(v)
            cache[c["chunk_id"]] = (doc_text(c), v)
        ids = list(cache)
        np.save(HANG / "embeddings.npy", np.stack([cache[i][1] for i in ids]))
        json.dump(ids, open(HANG / "embedding_ids.json", "w", encoding="utf-8"))
        json.dump([cache[i][0] for i in ids], open(HANG / "embedding_texts.json", "w", encoding="utf-8"), ensure_ascii=False)
        json.dump({"model": MODEL, "dim": int(new.shape[1]), "count": len(ids), "normalized": True,
                   "input": "규정명 조문 제목\\n본문", "device": device},
                  open(HANG / "embedding_meta.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    with psycopg.connect(URL, autocommit=True) as con:
        # 덤프보다 나중에 생긴 문서(예: S01 팀 가정 기준, rag_supplements.py)는 rag.documents 에 먼저 넣음
        have = {r[0] for r in con.execute("SELECT document_id FROM rag.documents")}
        for d in docs:
            if d["document_id"] not in have:
                con.execute("""INSERT INTO rag.documents (document_id, company_id, doc_name, tier, category, effective_date,
                    source_file, file_kind, pages, chunks, searchable, chars, doc_kind) VALUES (%s,'nuri',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (d["document_id"], d["doc_name"], d.get("tier"), d.get("category"), d.get("effective_date"), d.get("source_file"),
                     d.get("file_kind"), d.get("pages"), d["chunks"], d["searchable"], d["chars"], d["doc_kind"]))
                print("rag.documents 에 추가:", d["document_id"], d["doc_name"])
        con.execute("DROP TABLE IF EXISTS rag.chunks")
        con.execute("DROP TABLE IF EXISTS rag.articles")
        con.execute("""CREATE TABLE rag.articles (
            article_id text PRIMARY KEY, document_id text NOT NULL REFERENCES rag.documents(document_id),
            doc_kind text NOT NULL, doc_name text NOT NULL, article text, article_title text, effective_date date, text text NOT NULL)""")
        con.execute("COMMENT ON TABLE rag.articles IS '조문 전체 원문 (항 단위로 찾은 뒤 같은 article_id 조문 전체를 답에 붙일 때). rag_load_hang.py'")
        con.execute("""CREATE TABLE rag.chunks (
            chunk_id text PRIMARY KEY, document_id text NOT NULL REFERENCES rag.documents(document_id),
            company_id text NOT NULL, doc_kind text NOT NULL, doc_name text NOT NULL, article text, article_title text, part integer,
            chunk_type text NOT NULL, categories text[] NOT NULL, searchable boolean NOT NULL,
            text text NOT NULL, effective_date date, page integer, source_file text,
            embedding vector(1024), tsv tsvector,
            article_id text NOT NULL, hang text NOT NULL DEFAULT '', granularity text NOT NULL)""")
        for col, txt in [("article_id", "조문 묶음 id (문서id:조문). rag.articles 와 연결 (별표·부칙 등은 rag.articles 에 없을 수 있음)"),
                         ("hang", "항 번호 ①②… (항으로 안 나눈 조각은 빈 글자)"),
                         ("granularity", "항: 항 하나 / 조: 조문 전체(항 없음·짧음) / 그대로: 별표·부칙·서식안내 등 원래 조각"),
                         ("text", "본문. 항 조각은 앞에 「제N조(제목)」을 붙임"),
                         ("embedding", f"{MODEL} 1024차원, 정규화, 입력 = 규정명 조문 제목 + 본문")]:
            con.execute(f"COMMENT ON COLUMN rag.chunks.{col} IS '{txt}'")
        with con.cursor().copy("COPY rag.articles FROM STDIN") as cp:
            for a in articles:
                cp.write_row([a["article_id"], a["document_id"], a["doc_kind"], a["doc_name"], a["article"],
                              a["article_title"], a["effective_date"], a["text"]])
        with con.cursor().copy("COPY rag.chunks (chunk_id, document_id, company_id, doc_kind, doc_name, article, article_title, part, "
                               "chunk_type, categories, searchable, text, effective_date, page, source_file, embedding, "
                               "article_id, hang, granularity) FROM STDIN") as cp:
            for c in chunks:
                cp.write_row([c["chunk_id"], c["document_id"], c["company_id"], c["doc_kind"], c["doc_name"], c["article"],
                              c["article_title"], c["part"], c["chunk_type"], c["categories"], c["searchable"], c["text"],
                              c["effective_date"], c["page"], c["source_file"], emb.get(c["chunk_id"]),
                              c["article_id"], c["hang"], c["granularity"]])
        con.execute("UPDATE rag.chunks SET tsv = to_tsvector('simple', coalesce(doc_name,'') || ' ' || coalesce(article_title,'') || ' ' || text)")
        con.execute("CREATE INDEX ON rag.chunks USING hnsw (embedding vector_cosine_ops)")
        con.execute("CREATE INDEX ON rag.chunks USING gin (tsv)")
        con.execute("CREATE INDEX ON rag.chunks USING gin (categories)")
        con.execute("CREATE INDEX ON rag.chunks (company_id)")
        con.execute("CREATE INDEX ON rag.chunks (document_id)")
        con.execute("CREATE INDEX ON rag.chunks (doc_kind)")
        con.execute("CREATE INDEX ON rag.chunks (article_id)")
        for d in docs:
            con.execute("UPDATE rag.documents SET chunks=%s, searchable=%s, chars=%s WHERE document_id=%s",
                        (d["chunks"], d["searchable"], d["chars"], d["document_id"]))
        # 덤프에 있던 권한 그대로 (커넥터 역할은 rag 를 못 읽음)
        n, ne, bad, na = con.execute("SELECT count(*), count(embedding), count(*) FILTER (WHERE searchable AND embedding IS NULL), "
                                     "(SELECT count(*) FROM rag.articles) FROM rag.chunks").fetchone()
    ok = n == len(chunks) and bad == 0
    print(f"rag.chunks {n}개 (임베딩 {ne}, 검색 대상인데 임베딩 없음 {bad}), rag.articles {na}건 — {'일치' if ok else '불일치!'}")


if __name__ == "__main__":
    main()
