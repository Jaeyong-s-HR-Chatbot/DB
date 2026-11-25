"""7단계-2b 서식 안내 조각: [별지 서식] 원문 조각(searchable=false)마다 검색용 '서식안내' 조각을 하나씩 만듦.

실행: .venv/bin/python rag_forms.py   (rag_build.py 가 끝에서 자동으로 부름. 따로 실행하면 data/regs/chunks.jsonl 을 그 자리에서 고침)

왜: 서식 원문은 칸 이름 나열이라 검색에 넣으면 잡음이지만, "휴직하려면 무슨 서류 내요?" 같은 질문에는
    서식 이름·관련 조항·주요 기재 항목만 담은 짧은 안내 조각이 있어야 찾아 줄 수 있음.

안내 조각
- chunk_id  : {document_id}-F{별지번호 2자리}  (예: r14-F32) — 기존 조각 번호를 건드리지 않음
- chunk_type: "서식안내", article: "별지 N", searchable: true
- text      : 서식 이름 / 소속 규정 / 관련 조항(서식 머리의 "(제N조 관련)" + 같은 규정 조문 중 "별지 제N호서식"을 언급한 조) / 주요 기재 항목
- 원문 서식 조각은 그대로 두고(searchable=false) 안내 조각만 추가. 여러 번 실행해도 결과가 같음
"""
import json
import re
from collections import OrderedDict
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "data/regs"

FORM_NOUN = re.compile(r"(신청서|청구서|요청서|계획서|보고서|확인서|서약서|각서|신고서|통지서|통보서|사유서|의결서|설명서|요구서|추천서?|"
                       r"명부|대장|일지|카드|조사표|점검표|평정표|평정서|체크리스트|증명서|증서|계약서|기술서|소견서|검사서|"
                       r"근무서|상황부|추진실적|이름표|발령서|결과보고서|휴직원|복직원|사직원|퇴직원|표창장|상장|감사장|신청|기안문|서)$")
REF_ART = re.compile(r"제\s*\d+\s*조(?:\s*의\s*\d+)?(?:\s*제?\s*\d+\s*항)?(?:\s*제?\s*\d+\s*호)?")
MENTION = re.compile(r"별\s*지\s*(?:제\s*)?(\d+(?:\s*의\s*\d+)?)\s*호\s*서\s*식")
NOISE = re.compile(r"^[\s\[\]【】<>()（）■□❑※○·ㆍ.,:\d-]*$|년\s+월\s+일|^\(?(앞|뒤)쪽\)?$|개정|신설|\d+mm")


def norm(s):
    """'근 무 상 황 부' 처럼 글자마다 띄운 제목을 붙이고, 앞뒤 기호를 뗌"""
    s = re.sub(r"[\[【<(（]?\s*별\s*지\s*(?:제\s*)?\d+(?:\s*의\s*\d+)?\s*호\s*서식\s*[\]】>)）]?", "", s)
    s = re.sub(r"\[\s*별\s*지\s*서\s*식\s*\]", "", s)
    s = re.sub(r"[(（][^)）]*관련[^)）]*[)）]|[(（]\s*[)）]", "", s)
    s = re.sub(r"^\s*(?:\d+\s*\.|[①-⑳])\s*", "", s)
    s = s.strip(" <>■□❑※·-[]【】:")
    toks = s.split()
    if len(toks) >= 3 and sum(len(t) == 1 for t in toks) / len(toks) >= 0.6:
        s = "".join(toks)
    return re.sub(r"\s+", " ", s).strip()


def form_title(lines, fallback):
    for ln in lines[:8]:
        t = norm(ln)
        if 3 <= len(t) <= 40 and not NOISE.search(t) and FORM_NOUN.search(t.replace(" ", "")):
            return t
    t = norm(fallback)
    return t if t and not NOISE.search(t) else ""


def art_key(s):
    """'제19조의2제2항' · '제19의2조(…)' → '19의2' (같은 조인지 비교용)"""
    m = re.match(r"(?:부칙\s*)?제\s*(\d+)\s*(?:조\s*의\s*(\d+)|의\s*(\d+)\s*조|조)", s)
    return (m.group(1) + (f"의{m.group(2) or m.group(3)}" if (m.group(2) or m.group(3)) else "")) if m else s


def is_reference(title):
    """'별지 제2호서식의 해제 신청서에 따라 …' 처럼 본문 문장이 서식 머리로 잘못 잘린 경우"""
    return bool(re.match(r"^\s*별\s*지\s*(?:제\s*)?\d+\s*호\s*서식\s*(?:의|에|을|를|으로|및|과|와)", title or ""))


def form_guides(chunks):
    """chunks(규정 조각 목록)에서 서식 원문 조각을 모아 안내 조각 목록을 돌려줌"""
    forms = OrderedDict()   # (doc, 번호) → 원문 조각들
    mentions = {}           # (doc, 번호) → 언급한 조 번호 목록
    for c in chunks:
        if c["chunk_type"] == "서식" and not is_reference(c["article_title"]):
            no = c["article"].replace("별지", "").strip()
            forms.setdefault((c["document_id"], no), []).append(c)
        elif c["chunk_type"] in ("조문", "부칙") and c["article"].startswith(("제", "부칙")):
            for m in MENTION.finditer(c["text"]):
                key = (c["document_id"], re.sub(r"\s", "", m.group(1)))
                lst = mentions.setdefault(key, [])
                label = f"{c['article']}({c['article_title']})" if c["article_title"] else c["article"]
                if label not in lst:
                    lst.append(label)

    out = []
    for (doc, no), parts in forms.items():
        first = parts[0]
        lines = [l.strip() for p in parts for l in p["text"].split("\n") if l.strip()]
        form_label = f"별지 제{no}호 서식" if no else "별지 서식"
        title = (form_title(lines, first["article_title"]) if no else norm(first["article_title"])) or form_label
        head = " ".join(lines[:4])
        rel = []
        for m in re.finditer(r"[(（]([^)）]*?)\s*관련\s*[)）]|[(（](제\s*\d+\s*조[^)）]*)[)）]", head):
            rel += [re.sub(r"\s+", "", x) for x in REF_ART.findall(m.group(1) or m.group(2))]
        cited = mentions.get((doc, no), [])
        cited_base = {art_key(x) for x in cited}
        refs = list(dict.fromkeys(cited + [r for r in rel if art_key(r) not in cited_base]))
        items = []
        for ln in lines[1:]:
            for t in re.split(r"\s{2,}|■", ln):
                t = norm(re.sub(r"[:：]\s*$", "", t.strip()))
                t = re.sub(r"^[①-⑳\d.\s]+", "", t)
                if (2 <= len(t) <= 15 and not NOISE.search(t) and t != title and t.replace(" ", "") not in items
                        and not re.search(r"(다|니다|요|오니|며|고)\.?$", t)):
                    items.append(t.replace(" ", "") if len(t) <= 6 else t)
            if len(items) >= 12:
                break
        body = [f"[{form_label}] {title}",
                f"소속 규정: {first['doc_name']}"]
        if refs:
            body.append("관련 조항: " + ", ".join(refs))
        if items:
            body.append("주요 기재 항목: " + ", ".join(items))
        body.append(f"{title} 양식(제출 서류)은 「{first['doc_name']}」 {form_label}을 씁니다.")
        num = re.sub(r"\D", "", no.split("의")[0]) or "0"
        sub = f"-{no.split('의')[1]}" if "의" in no else ""
        out.append(dict(
            chunk_id=f"{doc}-F{int(num):02d}{sub}", document_id=doc, company_id=first["company_id"], doc_kind=first["doc_kind"],
            doc_name=first["doc_name"], article=f"별지 {no}" if no else "별지", article_title=title, part=1, text="\n".join(body),
            effective_date=first["effective_date"], page=first["page"], source_file=first["source_file"],
            chunk_type="서식안내", categories=first["categories"], searchable=True, tier=first["tier"]))
    return out


def with_guides(chunks):
    """기존 안내 조각을 지우고 새로 만들어, 각 규정의 마지막 조각 뒤에 붙인 목록을 돌려줌"""
    base = [c for c in chunks if c["chunk_type"] != "서식안내"]
    guides = form_guides(base)
    by_doc = {}
    for g in guides:
        by_doc.setdefault(g["document_id"], []).append(g)
    out, order = [], list(dict.fromkeys(c["document_id"] for c in base))
    for d in order:
        out += [c for c in base if c["document_id"] == d] + by_doc.get(d, [])
    return out


def main():
    path = OUT / "chunks.jsonl"
    chunks = [json.loads(l) for l in open(path, encoding="utf-8")]
    new = with_guides(chunks)
    with open(path, "w", encoding="utf-8") as f:
        for c in new:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    docs = json.load(open(OUT / "documents.json", encoding="utf-8"))
    for d in docs:
        mine = [c for c in new if c["document_id"] == d["document_id"]]
        d["chunks"], d["searchable"], d["chars"] = len(mine), sum(c["searchable"] for c in mine), sum(len(c["text"]) for c in mine)
    json.dump(docs, open(OUT / "documents.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    rep = json.load(open(OUT / "report.json", encoding="utf-8"))
    rep["chunks"], rep["searchable"] = len(new), sum(c["searchable"] for c in new)
    rep["by_type"] = {}
    for c in new:
        rep["by_type"][c["chunk_type"]] = rep["by_type"].get(c["chunk_type"], 0) + 1
    json.dump(rep, open(OUT / "report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    g = [c for c in new if c["chunk_type"] == "서식안내"]
    print(f"서식안내 조각 {len(g)}개 추가 → 전체 {len(new)}개, 검색 대상 {rep['searchable']}개")
    print("임베딩을 다시 만들어야 의미 검색에도 잡힘: python rag_embed.py → rag_load.py")


if __name__ == "__main__":
    main()
