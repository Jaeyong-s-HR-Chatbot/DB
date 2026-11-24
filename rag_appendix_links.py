"""조문 ↔ 별표 연결표 만들기 → data/hang/appendix_links.json

데이터에는 별표가 어느 조 소속인지 적는 칸이 없어서, 글 안의 두 가지 표시로 이어요.
  ① 조 → 별표: 조 본문의 "별표 3과 같다", "규정 별표 7에 의한" (다른 문서: 시행세칙의 '규정' = 상위 규정,
     시행령·시행규칙의 '법' = 상위 법, 「문서 이름」 별표 = 그 문서)
  ② 별표 → 조: 별표 머리의 "(제24조 관련)", "(제94조 제1항 및 제3항 관련)", "(규정 제31조 관련)"
둘 중 하나라도 있으면 연결. 결과에 연결 근거(조→별표 / 별표→조)를 같이 남겨요.

실행: python rag_appendix_links.py      (data/hang/articles.jsonl · chunks.jsonl 사용)
"""
import json
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
HANG = HERE / "data/hang"
OUT = HANG / "appendix_links.json"


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def squash(s):
    return re.sub(r"\s+", "", s)


ARTICLES = jl(HANG / "articles.jsonl")                         # 조 (별표·부칙 없음)
CHUNKS = jl(HANG / "chunks.jsonl")
DOC_NAME = {c["document_id"]: c["doc_name"] for c in CHUNKS}
DOC_BY_NAME = {squash(n): d for d, n in DOC_NAME.items()}
ARTICLE_IDS = {a["article_id"] for a in ARTICLES}

APPX = defaultdict(list)                                       # 별표 article_id → 조각 (순서대로)
for c in CHUNKS:
    if c["article"].startswith("별표") and c.get("searchable"):
        APPX[c["article_id"]].append(c)


def appx_id(doc, no):
    """'7', '6의2', '1의3' → 'r07:별표 7' (있을 때만)"""
    for cand in (f"{doc}:별표 {no}", f"{doc}:별표{no}"):
        if cand in APPX:
            return cand
    return None


def article_id(doc, n, m=None):
    """제N조(의M) → 실제 article_id (내부규정 '제26의2조' · 법령 '제74조의2' 둘 다)"""
    cands = [f"{doc}:제{n}조"] if not m else [f"{doc}:제{n}의{m}조", f"{doc}:제{n}조의{m}"]
    return next((c for c in cands if c in ARTICLE_IDS), None)


def parent_doc(doc, prefix):
    """'규정'(시행세칙에서) · '법'(시행령·시행규칙에서) → 상위 문서"""
    name = squash(DOC_NAME.get(doc, ""))
    for suffix, want in (("시행세칙", "규정"), ("시행령", "법"), ("시행규칙", "법")):
        if name.endswith(suffix) and prefix == want:
            base = name[: -len(suffix)]
            return DOC_BY_NAME.get(base)
    return None


# ① 조 → 별표
_FWD = re.compile(
    r"(?:「(?P<named>[^」]+)」\s*(?:제\s*\d+\s*조(?:의\s*\d+)?\s*(?:의\s*)?)?|(?P<prefix>규정|법)\s*(?:제\s*\d+\s*조(?:의\s*\d+)?\s*의\s*)?)?"
    r"별표\s*(?P<no>\d+)(?:\s*의\s*(?P<sub>\d+))?"
)


def forward_links():
    out = defaultdict(set)
    for a in ARTICLES:
        doc = a["document_id"]
        for m in _FWD.finditer(a["text"]):
            no = m["no"] + (f"의{m['sub']}" if m["sub"] else "")
            if m["named"]:
                target = DOC_BY_NAME.get(squash(m["named"]))
            elif m["prefix"]:
                target = parent_doc(doc, m["prefix"])
            else:
                target = doc
            if target and (aid := appx_id(target, no)):
                out[a["article_id"]].add(aid)
    return out


# ② 별표 → 조: 머리(앞 300자)의 "( … 관련)"
_REL = re.compile(r"\(([^()]{0,80}?)관련\s*\)")
_ART = re.compile(r"제\s*(\d+)\s*(?:조\s*의\s*(\d+)|의\s*(\d+)\s*조|조\s*(\d+)(?!\s*항)|조)")


def backward_links():
    out = defaultdict(set)
    for aid, parts in APPX.items():
        doc = parts[0]["document_id"]
        head = " ".join(p["text"] for p in parts)[:300]
        m = _REL.search(head)
        if not m:
            continue
        inside = m.group(1)
        target_doc = doc
        pm = re.match(r"\s*(규정|법)\s", inside)
        if pm and (pd := parent_doc(doc, pm.group(1))):
            target_doc = pd
        for am in _ART.finditer(inside):
            sub = am.group(2) or am.group(3) or am.group(4)
            # "제94조 제1항"의 '제1항'은 _ART에서 '조'가 없어 안 걸려요
            if (art := article_id(target_doc, am.group(1), sub)):
                out[aid].add(art)
    return out


def main():
    fwd, bwd = forward_links(), backward_links()
    links = defaultdict(dict)                                  # 조 → {별표: 근거}
    for art, apxs in fwd.items():
        for x in apxs:
            links[art][x] = "조→별표"
    for x, arts in bwd.items():
        for art in arts:
            links[art][x] = "양쪽" if links[art].get(x) == "조→별표" else "별표→조"
    by_appx = defaultdict(list)
    for art, d in links.items():
        for x in d:
            by_appx[x].append(art)
    unlinked = sorted(x for x in APPX if x not in by_appx)
    data = {
        "how": "조 본문의 '별표 N'(다른 문서: '규정'·'법'·「이름」) 또는 별표 머리의 '(제N조 관련)'으로 연결",
        "article_to_appendix": {a: sorted(d) for a, d in sorted(links.items())},
        "appendix_to_article": {x: sorted(v) for x, v in sorted(by_appx.items())},
        "evidence": {a: d for a, d in sorted(links.items())},
        "unlinked_appendix": unlinked,
        "count": {"appendix": len(APPX), "linked": len(by_appx), "unlinked": len(unlinked),
                  "article_with_appendix": len(links)},
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"별표 {len(APPX)} · 연결됨 {len(by_appx)} · 연결 안 됨 {len(unlinked)} · 별표가 붙는 조 {len(links)} → {OUT}")


if __name__ == "__main__":
    main()
