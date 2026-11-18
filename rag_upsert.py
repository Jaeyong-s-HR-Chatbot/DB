"""이미 띄운 hrdb 에 조각 파일의 새 조각·바뀐 조각만 넣음 (rag 스키마를 지우지 않음).

rag_load.py 는 rag 스키마를 통째로 다시 만들어서 전체 임베딩(embeddings.npy)이 있어야 해요.
서식안내(rag_forms.py)·팀 가정 기준(rag_supplements.py)처럼 조각 몇 개만 늘었을 때는 이 스크립트로 충분해요.

실행: HRDB_URL=postgresql://hr:hrpass@localhost:5432/hrdb python rag_upsert.py [--dry-run]
- data/regs 의 documents.json·chunks.jsonl 과 DB 를 chunk_id 로 비교해 없는 조각은 넣고, 글이 바뀐 조각은 고침
- sentence-transformers 가 있으면 넣는 조각만 BGE-M3 로 임베딩 (rag_embed.py 와 같은 입력 글). 없으면 embedding 은 비워 둠
  (비어 있으면 키워드 검색으로만 찾히고 벡터 검색에는 안 나와요)
- DB 에만 있고 파일에 없는 조각은 건드리지 않음
"""
import json
import os
import sys
from pathlib import Path

import psycopg

HERE = Path(__file__).parent
REG = HERE / "data/regs"
MODEL = "BAAI/bge-m3"


def doc_text(c):   # rag_embed.py 와 같게
    head = f"{c['doc_name']} {c['article']} {c['article_title']}".strip()
    return f"{head}\n{c['text']}"


def embed(chunks):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("sentence-transformers 가 없어 embedding 없이 넣어요")
        return {}
    model = SentenceTransformer(MODEL)
    vecs = model.encode([doc_text(c) for c in chunks], normalize_embeddings=True)
    return {c["chunk_id"]: "[" + ",".join(f"{x:.6f}" for x in v) + "]" for c, v in zip(chunks, vecs)}


def main():
    url = os.environ.get("HRDB_URL")
    if not url:
        sys.exit("HRDB_URL 을 정해 주세요 (예: postgresql://hr:hrpass@localhost:5432/hrdb)")
    dry = "--dry-run" in sys.argv
    chunks = [json.loads(l) for l in open(REG / "chunks.jsonl", encoding="utf-8")]
    docs = json.load(open(REG / "documents.json", encoding="utf-8"))
    for c in chunks:
        c.setdefault("doc_kind", "내부규정")

    with psycopg.connect(url, autocommit=False) as con:
        have_docs = {r[0] for r in con.execute("SELECT document_id FROM rag.documents")}
        have = dict(con.execute("SELECT chunk_id, text FROM rag.chunks").fetchall())
        new_docs = [d for d in docs if d["document_id"] not in have_docs]
        todo = [c for c in chunks if have.get(c["chunk_id"]) != c["text"]]
        print(f"새 문서 {len(new_docs)}건, 넣거나 고칠 조각 {len(todo)}개 "
              f"(새 {sum(c['chunk_id'] not in have for c in todo)}, 바뀜 {sum(c['chunk_id'] in have for c in todo)})")
        for c in todo[:10]:
            print(f"  {c['chunk_id']} {c['doc_name']} {c['article']}")
        if dry or not todo and not new_docs:
            return
        vec = embed([c for c in todo if c["searchable"]])
        for d in new_docs:
            con.execute(
                "INSERT INTO rag.documents (document_id, company_id, doc_name, tier, category, effective_date, source_file, "
                "file_kind, pages, chunks, searchable, chars, doc_kind) VALUES (%s,'nuri',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (d["document_id"], d["doc_name"], d.get("tier"), d.get("category"), d.get("effective_date"), d.get("source_file"),
                 d.get("file_kind"), d.get("pages"), d.get("chunks"), d.get("searchable"), d.get("chars"), d.get("doc_kind", "내부규정")))
        for c in todo:
            con.execute(
                "INSERT INTO rag.chunks (chunk_id, document_id, company_id, doc_kind, doc_name, article, article_title, part, "
                "chunk_type, categories, searchable, text, effective_date, page, source_file, embedding) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector) "
                "ON CONFLICT (chunk_id) DO UPDATE SET text = EXCLUDED.text, article = EXCLUDED.article, "
                "article_title = EXCLUDED.article_title, categories = EXCLUDED.categories, searchable = EXCLUDED.searchable, "
                "effective_date = EXCLUDED.effective_date, embedding = EXCLUDED.embedding",
                (c["chunk_id"], c["document_id"], c["company_id"], c["doc_kind"], c["doc_name"], c["article"], c["article_title"],
                 c["part"], c["chunk_type"], c["categories"], c["searchable"], c["text"], c["effective_date"], c["page"],
                 c["source_file"], vec.get(c["chunk_id"])))
        ids = [c["chunk_id"] for c in todo]
        con.execute("UPDATE rag.chunks SET tsv = to_tsvector('simple', coalesce(doc_name,'') || ' ' || coalesce(article_title,'') "
                    "|| ' ' || text) WHERE chunk_id = ANY(%s)", (ids,))
        con.execute("UPDATE rag.documents d SET chunks = s.n, searchable = s.m, chars = s.c FROM "
                    "(SELECT document_id, count(*) n, count(*) FILTER (WHERE searchable) m, sum(length(text)) c "
                    " FROM rag.chunks GROUP BY 1) s WHERE d.document_id = s.document_id")
        con.commit()
        print(f"완료: 조각 {len(todo)}개 (임베딩 {len(vec)}개)")


if __name__ == "__main__":
    main()
