"""7단계-2 규정 → 조문 조각(JSONL): data/regs/raw 의 PDF·HWP를 글자로 바꾸고 조문 단위로 잘라 data/regs/chunks.jsonl 저장.

실행: .venv/bin/python rag_build.py   (rag_fetch.py 다음)

자르는 규칙
- 「제N조(제목)」마다 한 조각. 부칙 안의 조는 "부칙 제N조"로 따로 표시
- [별표 N]은 별도 조각 (표 → 검색 대상), [별지 서식]은 신청 양식이라 검색 대상에서 뺌 (searchable=false)
- "제N조 삭제" 조문, 목차에서 제목만 있는 줄은 검색 대상에서 뺌
- 1,500자가 넘는 조각은 항(①②…) 경계에서 나눔 (part 1, 2 …)
- 칸: 팀 "데이터 형식 정의"(chunk_id, document_id, company_id, article, text, effective_date, page, source_file)
       + doc_name, article_title, chunk_type, category(팀 카테고리), searchable
- 회사 이름: 원문의 "한국철도공사"를 가상 회사 "누리철도㈜"로 바꿈 (조문 구조·기준은 그대로)

공개 전 확인(data/regs/report.json): 글자가 거의 없는 쪽(이미지 → OCR 필요), 조문 번호 없는 조각, 표 깨짐 의심,
중복 조문 번호, 개인정보 형식(전화·이메일·주민번호) 검출
"""
import json
import re
import struct
import zlib
from collections import Counter, defaultdict
from pathlib import Path

import olefile
import pdfplumber
import yaml

HERE = Path(__file__).parent
RAW = HERE / "data/regs/raw"
OUT = HERE / "data/regs"
REGS = yaml.safe_load(open(HERE / "rules/regulations.yaml", encoding="utf-8"))
MANIFEST = {m["id"]: m for m in json.load(open(OUT / "manifest.json", encoding="utf-8"))}
COMPANY = "nuri"
MAX_CHARS = 1500

ART = re.compile(r"^\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*[\(（]([^)）\n]{1,40})[\)）]")
ART_DEL = re.compile(r"^\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*(?:[\(（][^)）]*[\)）])?\s*삭\s*제")
BYEOLPYO = re.compile(r"^\s*[\[【<]?\s*별\s*표\s*(\d+(?:\s*의\s*\d+)?)\s*[\]】>]?")
BYEOLJI = re.compile(r"^\s*[\[【<]?\s*별\s*지\s*(?:제\s*)?(\d+(?:\s*의\s*\d+)?)\s*호?")
BUCHIK = re.compile(r"^\s*부\s*칙\b|^\s*부\s*칙\s*[<(]")
PAGE_NO = re.compile(r"^\s*[-–]\s*\d+\s*[-–]\s*$|^\s*\d+\s*/\s*\d+\s*$")


# ------------------------------------------------------------------ 글자 뽑기
def pdf_pages(path):
    with pdfplumber.open(path) as pdf:
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(pdf.pages)]


def hwp_text(path):
    """HWP 5.x: BodyText 섹션의 문단 글자(레코드 67)만 읽음. 쪽 번호는 없음."""
    ole = olefile.OleFileIO(str(path))
    header = ole.openstream("FileHeader").read()
    compressed = bool(header[36] & 1)
    sections = sorted([s for s in ole.listdir() if s[0] == "BodyText"], key=lambda s: int(s[1].replace("Section", "")))
    out = []
    for sec in sections:
        data = ole.openstream(sec).read()
        if compressed:
            data = zlib.decompress(data, -15)
        i = 0
        while i < len(data):
            h = struct.unpack_from("<I", data, i)[0]
            tag, size = h & 0x3FF, (h >> 20) & 0xFFF
            i += 4
            if size == 0xFFF:
                size = struct.unpack_from("<I", data, i)[0]
                i += 4
            if tag == 67:
                out.append(para_text(data[i:i + size]))
            i += size
    return out


def para_text(b):
    chars, k = [], 0
    n = len(b) // 2
    while k < n:
        c = struct.unpack_from("<H", b, k * 2)[0]
        if c >= 32:
            chars.append(chr(c))
            k += 1
        elif c in (10, 13):
            chars.append("\n")
            k += 1
        elif c in (0, 24, 25, 26, 27, 28, 29, 30, 31):
            k += 1
        else:
            k += 8  # 표·그림 등 제어 문자(8칸)
    return "".join(chars)


def load_lines(reg):
    m = MANIFEST[reg["id"]]
    path = RAW / m["saved"]
    lines, sparse = [], []
    if m["kind"] == "pdf":
        for pno, txt in pdf_pages(path):
            if len(txt.strip()) < 80:
                sparse.append(pno)
            for ln in txt.split("\n"):
                if not PAGE_NO.match(ln):
                    lines.append((pno, ln))
        pages = pno
    else:
        for para in hwp_text(path):
            for ln in para.split("\n"):
                lines.append((None, ln))
        pages = None
    return lines, sparse, pages


# ------------------------------------------------------------------ 자르기
def category_of(reg, title):
    for rule in REGS["category_rules"]:
        if any(k in title for k in rule["keywords"]):
            return rule["category"]
    return reg["category"]


def split_long(text):
    if len(text) <= MAX_CHARS:
        return [text]
    parts, cur = [], ""
    for seg in re.split(r"(?=[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮])|(?<=\n)", text):
        if len(cur) + len(seg) > MAX_CHARS and cur:
            parts.append(cur)
            cur = ""
        while len(seg) > MAX_CHARS:
            parts.append(seg[:MAX_CHARS])
            seg = seg[MAX_CHARS:]
        cur += seg
    if cur.strip():
        parts.append(cur)
    return parts


def effective_date(m):
    d = re.search(r"(\d{4})\s*년(?:도)?\s*(\d{1,2})\s*월(?:\s*(\d{1,2})\s*일)?", m["file_name"])
    if d:
        return f"{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3) or 1):02d}"
    d = re.search(r"(20\d{2})(\d{2})(\d{2})", m["file_name"])
    if d:
        return f"{d.group(1)}-{d.group(2)}-{d.group(3)}"
    return m["alio_date"].replace(".", "-")


def chunk_reg(reg):
    m = MANIFEST[reg["id"]]
    lines, sparse, pages = load_lines(reg)
    blocks, cur, in_buchik = [], None, False

    def start(kind, label, title, page):
        nonlocal cur
        cur = dict(kind=kind, label=label, title=title, page=page, lines=[])
        blocks.append(cur)

    start("전문", "", "제목·목차", lines[0][0] if lines else None)
    for page, ln in lines:
        s = ln.strip()
        if not s:
            continue
        if BUCHIK.match(s) and len(s) < 40:
            in_buchik = True
            start("부칙", "부칙", s, page)
        elif (mm := ART_DEL.match(s)) and len(s) < 60:
            n = mm.group(1) + (f"의{mm.group(2)}" if mm.group(2) else "")
            start("삭제", ("부칙 " if in_buchik else "") + f"제{n}조", "삭제", page)
        elif mm := ART.match(s):
            n = mm.group(1) + (f"의{mm.group(2)}" if mm.group(2) else "")
            start("부칙" if in_buchik else "조문", ("부칙 " if in_buchik else "") + f"제{n}조", mm.group(3).strip(), page)
        elif (mm := BYEOLPYO.match(s)) and len(s) < 120 and s[mm.end():mm.end() + 1] not in "에와과를은는이가및":
            in_buchik = False
            start("별표", f"별표 {mm.group(1).replace(' ', '')}", s, page)
        elif (mm := BYEOLJI.match(s)) and len(s) < 120 and s[mm.end():mm.end() + 1] not in "에와과를은는이가및":
            in_buchik = False
            start("서식", f"별지 {mm.group(1).replace(' ', '')}", s, page)
        cur["lines"].append(s)

    chunks, seq = [], 0
    for b in blocks:
        text = "\n".join(b["lines"]).replace("한국철도공사", "누리철도㈜")
        if not text.strip():
            continue
        toc = b["kind"] == "조문" and len(text) < len(b["label"]) + len(b["title"]) + 8  # 목차 줄
        if b["kind"] in ("별표", "서식"):  # 제목 줄은 개정 이력인 경우가 많아 다음 줄에서 실제 제목을 찾음
            cand = [l for l in b["lines"][:5] if not re.match(r"^\s*[\[【<(]", l) and not re.search(r"개정|^[\d.,\s]+>?$|>$", l) and len(l) >= 4]
            b["title"] = (cand[0] if cand else b["title"])[:60]
            b["cat_text"] = " ".join(b["lines"][:4])
        searchable = b["kind"] in ("조문", "별표", "부칙") and not toc
        for pi, part in enumerate(split_long(text), 1):
            seq += 1
            chunks.append(dict(
                chunk_id=f"{reg['id']}-{seq:04d}", document_id=reg["id"], company_id=COMPANY,
                doc_name=reg["name"], article=b["label"], article_title=b["title"],
                part=pi, text=part, effective_date=effective_date(m), page=b["page"], source_file=m["file_name"],
                chunk_type="목차" if toc else b["kind"], category=category_of(reg, b.get("cat_text", b["title"])) if b["kind"] != "전문" else reg["category"],
                searchable=searchable, tier=reg["tier"]))
    return chunks, dict(sparse_pages=sparse, pages=pages, kind=m["kind"])


# ------------------------------------------------------------------ 공개 전 확인
PII = {"전화": re.compile(r"01[016789]-?\d{3,4}-?\d{4}"), "이메일": re.compile(r"[\w.]+@[\w.]+\.\w+"),
       "주민번호": re.compile(r"\d{6}-[1-4]\d{6}")}


def table_broken(text):
    ls = [l for l in text.split("\n") if l.strip()]
    return len(ls) >= 6 and sum(len(l.strip()) <= 3 for l in ls) / len(ls) >= 0.3


def main():
    all_chunks, docs, issues = [], [], defaultdict(list)
    for reg in REGS["regulations"]:
        ch, info = chunk_reg(reg)
        all_chunks += ch
        arts = Counter(c["article"] for c in ch if c["chunk_type"] == "조문" and c["part"] == 1)
        dup = [a for a, n in arts.items() if n > 1]
        if info["pages"] and len(info["sparse_pages"]) > 0:
            issues["글자 거의 없는 쪽 (OCR 필요)"].append(f"{reg['name']}: {len(info['sparse_pages'])}/{info['pages']}쪽")
        if dup:
            issues["같은 조문 번호 두 번 이상"].append(f"{reg['name']}: {', '.join(dup[:5])}")
        nos = sum(1 for c in ch if c["searchable"] and not c["article"])
        if nos:
            issues["조문 번호 없는 검색 조각"].append(f"{reg['name']}: {nos}개")
        for c in ch:
            if c["searchable"] and table_broken(c["text"]):
                issues["표 깨짐 의심"].append(f"{c['chunk_id']} {reg['name']} {c['article']}")
            for k, rx in PII.items():
                if rx.search(c["text"]):
                    issues[f"개인정보 형식 ({k})"].append(f"{c['chunk_id']} {reg['name']} {c['article']}")
        docs.append(dict(document_id=reg["id"], doc_name=reg["name"], tier=reg["tier"], category=reg["category"],
                         file_kind=info["kind"], pages=info["pages"], chunks=len(ch),
                         searchable=sum(c["searchable"] for c in ch), chars=sum(len(c["text"]) for c in ch),
                         effective_date=ch[0]["effective_date"] if ch else None, source_file=MANIFEST[reg["id"]]["file_name"]))
    with open(OUT / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    json.dump(docs, open(OUT / "documents.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    rep = dict(chunks=len(all_chunks), searchable=sum(c["searchable"] for c in all_chunks),
               by_type=Counter(c["chunk_type"] for c in all_chunks),
               by_category=Counter(c["category"] for c in all_chunks if c["searchable"]),
               issues={k: v for k, v in issues.items()})
    json.dump(rep, open(OUT / "report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"{'규정':<24}{'형식':>5}{'쪽':>5}{'조각':>6}{'검색':>6}{'글자':>8}")
    for d in docs:
        print(f"{d['doc_name']:<24}{d['file_kind']:>5}{str(d['pages'] or '-'):>5}{d['chunks']:>6}{d['searchable']:>6}{d['chars']:>8,}")
    print(f"\n조각 {rep['chunks']}개, 검색 대상 {rep['searchable']}개 | 종류 {dict(rep['by_type'])}")
    print("카테고리:", dict(rep["by_category"]))
    for k, v in rep["issues"].items():
        print(f"[확인] {k}: {len(v)}건 — 예: {v[:3]}")


if __name__ == "__main__":
    main()
