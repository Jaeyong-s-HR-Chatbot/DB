"""7단계 확장 — 법령 조각 만들기: law_fetch_api.py 가 받아 둔 법제처 Open API 응답(data/laws/api/*.json, 기준일 11/11 현행판)을
조문 단위 조각으로 잘라 data/laws/chunks.jsonl · documents.json 저장. 규정(data/regs)과 같은 칸 구성이라 rag_load.py 가 한꺼번에 적재함.

실행: .venv/bin/python law_build.py   (먼저 law_fetch_api.py)
- 조(제N조, 제N조의2) 1개 = 조각 1개. 1,500자 넘으면 항(①②…) 단위로 나눠 part 1,2,…
- 삭제 조문·부칙은 검색 대상에서 뺌(searchable=false), 조각은 남김
- 별표는 같은 API 응답의 별표 텍스트(data/laws/attach_api)로 조각을 만듦 (chunk_type='별표', article='별표 4'). 서식(신청서 등)은 제외
- document_id = L01~, chunk_id = L01-0001~, doc_kind = '법령', status = '현행' (시행 예정판은 넣지 않음)
"""
import json
import re
from pathlib import Path

from categories import categories_of, head_text

HERE = Path(__file__).parent
RAW = HERE / "data/laws/raw"
OUT = HERE / "data/laws"
MAXLEN = 1500

# 법령명 → 팀 카테고리 (문서 기본값. 조각마다 조문 제목 키워드로 더 붙임 — categories.py)
CATEGORY = {
    "근로기준법": "공통",
    "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률": "생애이벤트-출산",
    "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 시행령": "생애이벤트-출산",
    "고용보험법": "생애이벤트-휴직·복직·퇴직",
    "고용보험법 시행령": "생애이벤트-휴직·복직·퇴직",
    "근로자퇴직급여 보장법 시행령": "생애이벤트-휴직·복직·퇴직",
    "고용상 연령차별금지 및 고령자고용촉진에 관한 법률": "생애이벤트-휴직·복직·퇴직",
    "산업안전보건법 시행규칙": "교육",
    "철도안전법 시행규칙": "교육",
    "민방위기본법": "근태관리",
    "성매매방지 및 피해자보호 등에 관한 법률 시행령": "교육",
    "성폭력방지 및 피해자보호 등에 관한 법률 시행령": "교육",
    "가정폭력방지 및 피해자보호 등에 관한 법률 시행령": "교육",
}
HANG = re.compile(r"^\*\*[①-⑳㉑-㉟]\*\*")
ART = re.compile(r"^##### (제\d+조(?:의\d+)?)\s*(?:\((.*)\))?\s*$")


def clean(s):
    s = re.sub(r"\*\*", "", s)
    s = re.sub(r"\\([.\-()\[\]~*_<>])", r"\1", s)
    return re.sub(r"[ \t]+\n", "\n", s).strip()


def front(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    fm = m.group(1)
    g = lambda k: (re.search(rf"^{k}: (.*)$", fm, re.M) or [None, ""])[1].strip().strip("'")
    return {"title": g("제목"), "kind": g("법령구분"), "promulgated": g("공포일자"), "effective": g("시행일자"),
            "dept": (re.search(r"소관부처:\n- (.*)", fm) or [None, ""])[1].strip(), "url": g("출처"),
            "attachments": len(re.findall(r"별표번호:", fm))}, text[m.end():]


def split_long(body):
    """1,500자 넘는 조문은 항 단위로 묶어 나눔"""
    if len(body) <= MAXLEN:
        return [body]
    parts, cur = [], []
    blocks = []
    for b in re.split(r"\n(?=\*\*[①-⑳㉑-㉟]\*\*)", body):
        # 항 표시가 없거나 한 항이 너무 길면 줄 단위로 더 쪼갬 (부칙·긴 표 조문)
        blocks.extend(b.split("\n") if len(b) > MAXLEN else [b])
    for block in blocks:
        if cur and len("\n".join(cur)) + len(block) > MAXLEN:
            parts.append("\n".join(cur))
            cur = []
        cur.append(block)
    if cur:
        parts.append("\n".join(cur))
    return parts


BORDER = re.compile(r"^[\s┌┐└┘├┤┬┴┼─│]*$")


def clean_table(txt):
    """API 별표 텍스트의 표 테두리(┌─┬ 등)를 지우고 칸 구분(│)은 ' | '로 바꿈"""
    out = []
    for line in txt.split("\n"):
        if BORDER.match(line) and "│" not in line.replace("│", "", 0).strip("│ ") and not re.search(r"[^\s┌┐└┘├┤┬┴┼─│]", line):
            continue
        line = re.sub(r"[┌┐└┘├┤┬┴┼─]+", " ", line).replace("│", " | ")
        line = re.sub(r"( \| )+", " | ", line)
        line = re.sub(r"[ \t]{2,}", " ", line).strip(" |")
        if line.strip():
            out.append(line.strip())
    return "\n".join(out)


def attach_rows():
    """별표: 우선 Open API 결과(law_attach_api.py, 띄어쓰기·표 구조 보존), 없으면 PDF 결과(law_attach.py). 법령명 → [(별표 이름, 제목, 글자)]"""
    res = {}
    fa = OUT / "attach_api_timing.json"
    if fa.exists():
        for L in json.load(open(fa, encoding="utf-8"))["laws"]:
            for it in L.get("items", []):
                txt = clean_table((OUT / "attach_api" / it["file"]).read_text(encoding="utf-8"))
                no = str(int(it["no"])) + (f"의{int(it['sub'])}" if it["sub"] not in ("", "00") else "")
                res.setdefault(L["law"], []).append((f"별표 {no}", it["title"], txt))
        return res
    f = OUT / "attach_timing.json"
    if not f.exists():
        return res
    for it in json.load(open(f, encoding="utf-8"))["items"]:
        txt = (OUT / "attach" / f"{it['key']}.txt").read_text(encoding="utf-8")
        txt = txt.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        no = str(int(it["no"])) + (f"의{int(it['sub'])}" if it["sub"] not in ("", "00") else "")
        res.setdefault(it["law"], []).append((f"별표 {no}", it["title"].replace("&lt;", "<").replace("&gt;", ">"), clean(txt)))
    return res


def hang_lines(h):
    """항 1개의 본문 줄들 (항 → 호 → 목)"""
    out = [h.get("항내용", "")]
    hos = h.get("호", [])
    for ho in hos if isinstance(hos, list) else [hos]:
        out.append(flat_txt(ho.get("호내용", "")))
        moks = ho.get("목", [])
        for mk in moks if isinstance(moks, list) else [moks]:
            out.append("  " + flat_txt(mk.get("목내용", "")))
    return [x for x in out if x and x.strip()]


def flat_txt(x):
    return "\n".join(flat_txt(i) for i in x) if isinstance(x, list) else str(x)


def article_text(a):
    """API 조문단위 → (조 번호, 제목, 본문)"""
    no = f"제{a['조문번호']}조" + (f"의{a['조문가지번호']}" if a.get("조문가지번호") else "")
    title = a.get("조문제목", "") or ""
    if a.get("항"):
        hs = a["항"] if isinstance(a["항"], list) else [a["항"]]
        lines = []
        for h in hs:
            lines += hang_lines(h)
        body = "\n".join(lines)
    else:  # 항이 없는 조: 조문내용 이 '제1조(목적) 본문…' 형태
        body = re.sub(r"^제\d+조(?:의\d+)?\s*(?:\([^)]*\))?\s*", "", flat_txt(a.get("조문내용", "")).strip())
    return no, title, body.strip()


def build():
    docs, chunks = [], []
    att = attach_rows()
    index = json.load(open(OUT / "api/index.json", encoding="utf-8"))
    for n, meta in enumerate(index, 1):
        did = f"L{n:02d}"
        cat = CATEGORY[meta["title"]]
        b = json.load(open(OUT / "api" / f"{meta['mst']}.json", encoding="utf-8"))["법령"]
        out = []  # (article, title, text, part, type)
        for a in b["조문"]["조문단위"]:
            if a.get("조문여부") != "조문":
                continue
            art, title, txt = article_text(a)
            deleted = title == "삭제" or txt.startswith("삭제") and len(txt) < 40
            if not txt and not title:
                continue
            for k, part in enumerate(split_long(clean(txt) or title), 1):
                out.append((art, title, part, k, "삭제" if deleted else "조문"))
        for art, title, txt in att.get(meta["title"], []):
            deleted = title.startswith("삭제") or len(txt) < 60
            for k, part in enumerate(split_long(txt), 1):
                out.append((art, title, part, k, "삭제" if deleted else "별표"))
        bu = (b.get("부칙") or {}).get("부칙단위", [])
        bu = bu if isinstance(bu, list) else [bu]
        bt = clean("\n".join(flat_txt(u.get("부칙내용", "")) for u in bu))
        if bt:
            for k, part in enumerate(split_long(bt), 1):
                out.append(("부칙", "부칙", part, k, "부칙"))
        eff = f"{meta['effective'][:4]}-{meta['effective'][4:6]}-{meta['effective'][6:]}"
        pub = f"{meta['promulgated'][:4]}-{meta['promulgated'][4:6]}-{meta['promulgated'][6:]}"
        for i, (art, title, txt, part, typ) in enumerate(out, 1):
            if not txt:
                continue
            chunks.append({"chunk_id": f"{did}-{i:04d}", "document_id": did, "company_id": "nuri", "doc_kind": "법령",
                           "doc_name": meta["title"], "article": art, "article_title": title, "part": part,
                           "text": txt, "effective_date": eff, "page": None,
                           "source_file": f"법제처 Open API MST {meta['mst']}", "chunk_type": typ,
                           "categories": categories_of(cat, (title or "") + (" " + head_text(txt) if typ == "별표" else "")),
                           "searchable": typ in ("조문", "별표"), "tier": "법령"})
        mine = [c for c in chunks if c["document_id"] == did]
        docs.append({"document_id": did, "doc_name": meta["title"], "doc_kind": "법령", "tier": "법령", "category": cat,
                     "effective_date": eff, "promulgated": pub, "law_type": meta["kind"], "dept": meta["dept"],
                     "source_url": meta["url"], "source_file": f"법제처 Open API MST {meta['mst']}", "file_kind": "api",
                     "pages": None, "chunks": len(mine), "searchable": sum(c["searchable"] for c in mine),
                     "chars": sum(len(c["text"]) for c in mine), "attachments": meta["byulpyo"],
                     "law_mst": meta["mst"], "status": "현행", "base_date": "2026-11-11"})
    with open(OUT / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    json.dump(docs, open(OUT / "documents.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for d in docs:
        print(f"{d['document_id']} {d['doc_name'][:34]:36} MST {d['law_mst']} 시행 {d['effective_date']} 조각 {d['chunks']:4d} 검색 {d['searchable']:4d} 별표 {d['attachments']}")
    print(f"합계 문서 {len(docs)}건, 조각 {len(chunks)}개 (검색 대상 {sum(c['searchable'] for c in chunks)}), {sum(len(c['text']) for c in chunks):,}자")


if __name__ == "__main__":
    build()
