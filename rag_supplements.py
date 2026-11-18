"""팀 가정 기준 조각: 원문 규정에 없지만 팀이 정한 기준을 검색용 조각으로 추가.

- 원문(ALIO 규정)에서 확인되지 않은 내용이라, 원문 조각과 섞지 않고 별도 문서 `S01 팀 가정 기준`으로 넣어요.
  인용은 "팀 가정 기준 <항목>"으로 나와서 원문 조문과 구분돼요.
- 원문을 확보하면 해당 항목을 지우고 원문 조각으로 바꿔요.
- rag_build.py 가 끝에 자동으로 붙여요. 이미 만든 조각 파일에만 붙이려면:
  .venv/bin/python rag_supplements.py   (그 뒤 rag_embed.py → rag_load.py 다시 실행)
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "data/regs"

DOC_ID = "S01"
DOC_NAME = "팀 가정 기준"

# 항목 하나 = 조각 하나. decided: 팀 결정일, basis: 확인된 근거와 가정의 경계
SUPPLEMENTS = [
    {
        "article": "결혼축하금",
        "article_title": "결혼축하금 지급 횟수",
        "categories": ["생애이벤트-결혼", "기타 복리후생"],
        "decided": "2026-11-18",
        "text": (
            "결혼축하금(본인 결혼)은 재직 기간 중 생애 1회만 지급한다. "
            "이미 결혼축하금을 받은 직원이 재혼하는 경우에는 다시 지급하지 않는다. "
            "본인 결혼 축의금은 50만원이다(2025년 ALIO 공시, 사내근로복지기금 운영규정 제5조). "
            "※ 생애 1회 한정은 팀 가정 기준(2026-11-18 결정)이며, 사내근로복지기금 운영규정 원문 확인 전까지 사용한다."
        ),
    },
]


def supplement_chunks() -> list[dict]:
    out = []
    for i, s in enumerate(SUPPLEMENTS, 1):
        out.append(dict(
            chunk_id=f"{DOC_ID}-{i:04d}", document_id=DOC_ID, company_id="nuri", doc_kind="내부규정",
            doc_name=DOC_NAME, article=s["article"], article_title=s["article_title"], part=1,
            text=s["text"], effective_date=s["decided"], page=None, source_file="rag_supplements.py",
            chunk_type="조문", categories=s["categories"], searchable=True, tier="가정",
        ))
    return out


def supplement_doc(chunks: list[dict]) -> dict:
    return dict(document_id=DOC_ID, doc_name=DOC_NAME, doc_kind="내부규정", tier="가정", category="기타 복리후생",
                file_kind="code", pages=None, chunks=len(chunks), searchable=sum(c["searchable"] for c in chunks),
                chars=sum(len(c["text"]) for c in chunks), effective_date=max(c["effective_date"] for c in chunks),
                source_file="rag_supplements.py")


def with_supplements(chunks: list[dict], docs: list[dict]) -> tuple[list[dict], list[dict]]:
    """기존 팀 가정 조각·문서를 지우고 새로 붙인 목록을 돌려줌 (여러 번 실행해도 같은 결과)"""
    sup = supplement_chunks()
    chunks = [c for c in chunks if c["document_id"] != DOC_ID] + sup
    docs = [d for d in docs if d["document_id"] != DOC_ID] + [supplement_doc(sup)]
    return chunks, docs


def main():
    path = OUT / "chunks.jsonl"
    chunks = [json.loads(l) for l in open(path, encoding="utf-8")]
    docs = json.load(open(OUT / "documents.json", encoding="utf-8"))
    chunks, docs = with_supplements(chunks, docs)
    with open(path, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    json.dump(docs, open(OUT / "documents.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"팀 가정 조각 {len(SUPPLEMENTS)}개 반영 → {path} (임베딩·DB 적재는 rag_embed.py → rag_load.py)")


if __name__ == "__main__":
    main()
