"""스캔 쪽(이미지) 규정의 본문 조각을 추가: data/regs/scan_chunks.jsonl → data/regs/chunks.jsonl

왜: 겸직허가 운영 내규(r06)는 조문 쪽이 이미지라 rag_build.py 가 글자를 못 뽑아, 검색에 별표와 서식 안내만 남았음.
무엇을: OCR 한 뒤 사람이 읽을 수 있게 교정한 조문·부칙 조각을 r06-0101 번부터 추가 (기존 조각 ID는 그대로).
순서: rag_build.py → rag_scans.py → rag_tables.py → rag_rechunk.py → rag_appendix_links.py
실행: python rag_scans.py   (여러 번 실행해도 같은 결과, 원본 파일 필요 없음)
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
REGS = HERE / "data/regs/chunks.jsonl"
DOCS = HERE / "data/regs/documents.json"
SCANS = HERE / "data/regs/scan_chunks.jsonl"


def jl(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").split("\n") if l.strip()]


def with_scans(chunks, docs, scans):
    """같은 ID의 스캔 조각을 지우고 문서의 첫 조각 앞에 다시 넣음. 조각 수·글자 수도 갱신"""
    ids = {c["chunk_id"] for c in scans}
    out = [c for c in chunks if c["chunk_id"] not in ids]
    for doc in dict.fromkeys(c["document_id"] for c in scans):
        add = [c for c in scans if c["document_id"] == doc]
        at = next(i for i, c in enumerate(out) if c["document_id"] == doc)
        out[at:at] = add
        mine = [c for c in out if c["document_id"] == doc]
        for d in docs:
            if d["document_id"] == doc:
                d.update(chunks=len(mine), searchable=sum(c["searchable"] for c in mine), chars=sum(len(c["text"]) for c in mine))
    return out, docs


def main():
    scans = jl(SCANS)
    chunks, docs = with_scans(jl(REGS), json.loads(DOCS.read_text(encoding="utf-8")), scans)
    REGS.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in chunks), encoding="utf-8")
    DOCS.write_text(json.dumps(docs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"스캔 조각 {len(scans)}개 반영 → {REGS.relative_to(HERE)}")


if __name__ == "__main__":
    main()
