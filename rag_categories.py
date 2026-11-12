"""조각 카테고리 다시 붙이기: 이미 만든 조각 파일(data/regs, data/laws chunks.jsonl)의 category(1개)를 categories(여러 개)로 바꿈.

실행: .venv/bin/python rag_categories.py
- 원문(data/regs/raw, data/laws/api)이 없어도 됨. 조각 파일의 조문 제목·본문 앞줄만 보고 categories.py 규칙으로 다시 붙임
- 결과
    data/regs/chunks.jsonl, data/laws/chunks.jsonl   category → categories
    data/regs/report.json                            by_category 를 새 기준(라벨마다 셈)으로
    deploy/initdb/03_categories.sql                  이미 띄운 DB / 덤프로 만든 DB 의 rag.chunks 를 같은 값으로 바꾸는 SQL
- 처음 맞는 것 하나만 고르던 예전 규칙으로 다시 계산해 기존 category 와 같은지 먼저 확인함 (제목을 제대로 읽었는지 검사)
"""
import json
from collections import Counter
from pathlib import Path

from categories import ALL, COMMON, RULES, categories_of, head_text

HERE = Path(__file__).parent
SQL = HERE / "deploy/initdb/03_categories.sql"


def old_category(base, text):
    for r in RULES:
        if any(k in text for k in r["keywords"]):
            return r["category"]
    return base


def label_text(c, block_head):
    """rag_build / law_build 가 카테고리를 정할 때 본 글자"""
    if c["chunk_type"] == "전문":
        return ""
    if c["chunk_type"] in ("별표", "서식"):
        if c["doc_kind"] == "법령":
            return (c["article_title"] or "") + " " + block_head
        return block_head
    return c["article_title"] or ""


def relabel(folder, kind):
    path = HERE / folder / "chunks.jsonl"
    chunks = [json.loads(l) for l in open(path, encoding="utf-8")]
    base = {d["document_id"]: d["category"] for d in json.load(open(HERE / folder / "documents.json", encoding="utf-8"))}
    out, bad, head = [], [], ""
    for c in chunks:
        c.setdefault("doc_kind", kind)
        if c["part"] == 1:
            head = head_text(c["text"])
        text = label_text(c, head)
        b = base[c["document_id"]]
        if "category" in c:
            # 예전 규칙: 규정은 제목 키워드로 하나, 법령은 문서 기본값 그대로
            was = (b if c["chunk_type"] == "전문" else old_category(b, text)) if kind == "내부규정" else b
            if was != c["category"]:
                bad.append((c["chunk_id"], c["category"], was))
        cats = categories_of(b, text)
        out.append({(("categories") if k == "category" else k): (cats if k == "category" else v) for k, v in c.items()}
                   if "category" in c else {**c, "categories": cats})
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for c in out:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return out, bad


def report(name, chunks):
    s = [c for c in chunks if c["searchable"]]
    n = Counter(len(c["categories"]) for c in s)
    by = Counter(k for c in s for k in c["categories"])
    print(f"\n[{name}] 검색 대상 {len(s)}개 — 조각당 카테고리 수 {dict(sorted(n.items()))}, 평균 {sum(len(c['categories']) for c in s) / len(s):.2f}")
    for k in ALL:
        print(f"  {k:<14}{by.get(k, 0):>5}")
    return by


def write_sql(chunks):
    rows = ",\n".join("('{}', ARRAY[{}]::text[])".format(c["chunk_id"], ",".join(f"'{k}'" for k in c["categories"]))
                      for c in chunks)
    SQL.write_text(
        "-- 4) rag.chunks.category(1개) → categories(여러 개). rag_categories.py 가 만듦 — 직접 고치지 말 것\n"
        "-- 덤프(01) 다음에 자동 실행됨. 이미 띄운 DB 에는: psql -d hrdb -f deploy/initdb/03_categories.sql\n"
        "-- 검색: WHERE searchable AND categories && ARRAY['근태관리','공통']  (하나라도 겹치면 통과)\n"
        "BEGIN;\n"
        "ALTER TABLE rag.chunks ADD COLUMN IF NOT EXISTS categories text[];\n"
        "UPDATE rag.chunks c SET categories = v.cats FROM (VALUES\n" + rows + "\n) AS v(chunk_id, cats) WHERE c.chunk_id = v.chunk_id;\n"
        "DO $$ BEGIN\n"
        "  IF EXISTS (SELECT 1 FROM rag.chunks WHERE categories IS NULL) THEN RAISE EXCEPTION 'categories 가 비어 있는 조각이 있음'; END IF;\n"
        "END $$;\n"
        "ALTER TABLE rag.chunks ALTER COLUMN categories SET NOT NULL;\n"
        "DROP INDEX IF EXISTS rag.chunks_company_id_category_idx;\n"
        "ALTER TABLE rag.chunks DROP COLUMN IF EXISTS category;\n"
        "CREATE INDEX IF NOT EXISTS chunks_categories_idx ON rag.chunks USING gin (categories);\n"
        "CREATE INDEX IF NOT EXISTS chunks_company_id_idx ON rag.chunks (company_id);\n"
        "COMMENT ON COLUMN rag.chunks.categories IS '팀 업무 카테고리 목록 (조문 제목 키워드 전부 + 문서 기본 카테고리, 없으면 공통). categories.py';\n"
        "COMMIT;\n", encoding="utf-8", newline="\n")


def main():
    regs, bad_r = relabel("data/regs", "내부규정")
    laws, bad_l = relabel("data/laws", "법령")
    for name, bad in [("규정", bad_r), ("법령", bad_l)]:
        print(f"예전 규칙 재현 ({name}): {'모두 같음' if not bad else f'{len(bad)}개 다름 — 예: {bad[:5]}'}")
    by = report("규정", regs)
    report("법령", laws)
    rp = HERE / "data/regs/report.json"
    rep = json.load(open(rp, encoding="utf-8"))
    rep["by_category"] = {k: by.get(k, 0) for k in ALL}
    json.dump(rep, open(rp, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=1)
    write_sql(regs + laws)
    print(f"\n{SQL.relative_to(HERE)} 저장 ({len(regs) + len(laws)}개 조각)")


if __name__ == "__main__":
    main()
