"""별표(규정 뒤 기준표) 조각의 표를 원본에서 다시 읽어 마크다운 표로 바꾼다.

왜: rag_build.py는 PDF·HWP에서 글자만 뽑아서 표의 행·열이 섞인다
    (예: 국내여비 정액표에서 "실비 실비 30,000 …"처럼 어느 칸 값인지 알 수 없음).
무엇을: TABLE_IDS에 적은 별표 조각만, 조각 ID·조각 수·다른 칸은 그대로 두고 text만 바꾼다.
        표 밖 줄(별표 머리, 제목, (제N조 관련), <비고>)은 원래 조각의 줄을 그대로 쓴다.
        길어져도 조각을 새로 나누지 않는다 (나누면 조각 ID가 밀려 골든셋을 다시 고쳐야 함).

순서: rag_build.py · law_build.py → rag_scans.py → rag_tables.py → rag_rechunk.py → rag_appendix_links.py
실행:
  python rag_tables.py            data/regs/table_markdown.json · table_markdown_ported.json 의 표를
                                  data/regs · data/laws · data/hang 의 chunks.jsonl 에 넣음 (원본 파일 필요 없음)
  python rag_tables.py --extract  data/regs/raw 원본에서 표를 다시 읽어 table_markdown.json 을 새로 만듦
                                  (pdfplumber, hwp5html(pyhwp), beautifulsoup4, lxml 필요)
"""
import json, re, sys, subprocess, tempfile, collections, hashlib
from pathlib import Path

HERE = Path(__file__).parent
RAW = HERE / "data/regs/raw"
REGS = HERE / "data/regs/chunks.jsonl"
HANG = HERE / "data/hang/chunks.jsonl"
OUT = HERE / "data/regs/table_markdown.json"
# 원본 자동 추출(--extract)로 만들 수 없어 따로 옮겨 적은 표 (병합 칸·위임전결 ㅇ 위치·조직도 등).
# 별표 말고도 위임전결 본사 전결사항(조각 종류는 '부칙'으로 되어 있음)이 들어 있음. --extract 는 이 파일을 건드리지 않음
PORTED = HERE / "data/regs/table_markdown_ported.json"
LAWS = HERE / "data/laws/chunks.jsonl"

# 표가 깨진 별표 중 골든셋 정답·human check 근거에 쓰인 것부터. 제외: r06-0001(절차 그림), r26-0039~0042(4조각짜리 긴 자격증 표),
# r31-0037(직제 분장업무 12번째 조각) — 자동 추출로 조각 경계를 지키기 어려워 따로 손봐야 함
TABLE_IDS = ["r02-0029", "r04-0038", "r04-0039", "r05-0027", "r05-0031", "r05-0032", "r07-0053", "r08-0048",
             "r08-0054", "r08-0069", "r12-0039", "r15-0017", "r15-0018", "r15-0019", "r15-0020", "r21-0043", "r24-0014"]

import pdfplumber
from bs4 import BeautifulSoup

sq = lambda s: re.sub(r"\s+", "", s or "")
PAGE_NO = re.compile(r"^\s*[-–]\s*\d+\s*[-–]\s*$|^\s*\d+\s*/\s*\d+\s*$")


def cell_text(s):
    s = (s or "").replace("|", "\\|")
    return re.sub(r"\s*\n\s*", " ", s).strip()


# ---------------------------------------------------------------- 단위: ("line", 글) 또는 ("row", 칸 목록, 표 번호, 머리행 여부)
def grid_from_pdf_table(page, t):
    cells = [c for c in t.cells]
    xs = sorted({round(c[0], 1) for c in cells} | {round(c[2], 1) for c in cells})
    ys = sorted({round(c[1], 1) for c in cells} | {round(c[3], 1) for c in cells})
    def span(a, b, axis):
        return [i for i in range(len(axis) - 1) if axis[i] >= round(a, 1) - 0.5 and axis[i + 1] <= round(b, 1) + 0.5]
    grid = [[None] * (len(xs) - 1) for _ in range(len(ys) - 1)]
    for c in cells:
        txt = page.crop(c).extract_text() or ""
        cols = span(c[0], c[2], xs)
        for r in span(c[1], c[3], ys):
            for j, k in enumerate(cols):
                grid[r][k] = txt if j == 0 else ""
    # 빈 행·빈 열(선만 있는 칸) 제거
    grid = [r for r in grid if any((x or "").strip() for x in r)]
    keep = [k for k in range(len(grid[0])) if any((r[k] or "").strip() for r in grid)] if grid else []
    grid = [[r[k] for k in keep] for r in grid]
    # 가로로 합쳐진 칸 때문에 생긴 같은 열 중복 제거 (모든 행에서 옆 칸과 같으면 하나로)
    k = 1
    while grid and k < len(grid[0]):
        if all(r[k] == r[k - 1] for r in grid):
            for r in grid: del r[k]
        else:
            k += 1
    return grid


def merge_header(grid):
    """맨 위 머리 행이 여러 줄(세로로 합쳐진 칸)이면 한 행으로 합친다."""
    if len(grid) < 2: return grid
    h = 1
    while h < len(grid) and not any(re.search(r"\d", x or "") for x in grid[h]) \
            and any((grid[h][k] or "") == (grid[h - 1][k] or "") and (grid[h][k] or "") for k in range(len(grid[h]))) \
            and not any(re.search(r"\d", x or "") for x in grid[0]):
        h += 1
    if h == 1: return grid
    head = []
    for k in range(len(grid[0])):
        seen = []
        for r in range(h):
            v = (grid[r][k] or "").strip()
            if v and v not in seen: seen.append(v)
        head.append(" ".join(seen))
    return [head] + grid[h:]


def expand_stacked(grid):
    """선 없이 한 칸에 위아래로 쌓인 값(가/나/다/라 ↔ 50/50/50/50)을 행으로 펼친다."""
    out = []
    for ri, row in enumerate(grid):
        lines = [(x or "").split("\n") for x in row]
        counts = [len(l) for l in lines if len(l) > 1]
        n = max(set(counts), key=counts.count) if counts else 1
        same = sum(1 for l in lines if len(l) == n)
        short = [l for l in lines if len(l) == n and all(len(x.strip()) <= 6 for x in l)]
        numeric = [l for l in short if all(re.fullmatch(r"[\d,.\s%]+", x.strip() or "0") for x in l)]
        if ri > 0 and n >= 2 and len(short) >= 2 and numeric:
            for j in range(n):
                out.append([l[j] if len(l) == n else (x or "") for l, x in zip(lines, row)])
        else:
            out.append(row)
    return out


def dotted_lines(page):
    """점선(짧은 선 조각 여러 개)으로 그린 칸 선을 한 줄로 이어 붙인다."""
    H, V = [], []
    gh, gv = collections.defaultdict(list), collections.defaultdict(list)
    for l in page.lines:
        if abs(l["top"] - l["bottom"]) < 1 and (l["x1"] - l["x0"]) < 6: gh[round(l["top"])].append(l)
        if abs(l["x0"] - l["x1"]) < 1 and (l["bottom"] - l["top"]) < 6: gv[round(l["x0"])].append(l)
    for y, ls in gh.items():
        x0 = min(l["x0"] for l in ls); x1 = max(l["x1"] for l in ls)
        if x1 - x0 >= 40 and sum(l["x1"] - l["x0"] for l in ls) / (x1 - x0) > 0.2:
            H.append(dict(x0=x0, x1=x1, top=y, bottom=y, width=x1 - x0, height=0, object_type="line"))
    for x, ls in gv.items():
        t = min(l["top"] for l in ls); b = max(l["bottom"] for l in ls)
        if b - t >= 10 and sum(l["bottom"] - l["top"] for l in ls) / (b - t) > 0.2:
            V.append(dict(x0=x, x1=x, top=t, bottom=b, width=0, height=b - t, object_type="line"))
    return {"explicit_horizontal_lines": H, "explicit_vertical_lines": V} if (H or V) else {}


def pdf_units(path, pages):
    units, tno = [], 0
    with pdfplumber.open(path) as pdf:
        for pno in pages:
            if pno > len(pdf.pages): break
            page = pdf.pages[pno - 1]
            tables = [t for t in page.find_tables(dotted_lines(page)) if len(t.rows) >= 2]
            items = []
            for t in tables:
                tno += 1
                grid = grid_from_pdf_table(page, t)
                grid = expand_stacked(merge_header(grid))
                for i, row in enumerate(grid):
                    items.append((t.bbox[1] + i * 0.01, ("row", [cell_text(x) for x in row], tno, i == 0)))
            rest = page
            for t in tables:
                rest = rest.outside_bbox(t.bbox)
            for ln in rest.extract_text_lines():
                if not PAGE_NO.match(ln["text"]):
                    items.append((ln["top"], ("line", ln["text"])))
            items.sort(key=lambda x: x[0])
            units += [u for _, u in items]
    return units


def hwp_units(path):
    d = Path(tempfile.mkdtemp())
    subprocess.run(["hwp5html", "--output", str(d), str(path)], check=True, capture_output=True)
    soup = BeautifulSoup((d / "index.xhtml").read_text(encoding="utf-8"), "xml")
    units, tno = [], 0
    body = soup.body
    def walk(node):
        nonlocal tno
        for el in node.find_all(["table", "p"], recursive=True):
            if el.name == "table":
                if el.find_parent("table"):
                    continue
                tno += 1
                rows = el.find_all("tr")
                # rowspan/colspan 펼치기
                grid, pending = [], {}
                for ri, tr in enumerate(rows):
                    out, ci = [], 0
                    tds = [td for td in tr.find_all(["td", "th"]) if td.find_parent("tr") is tr]
                    it = iter(tds)
                    while True:
                        while (ri, ci) in pending:
                            out.append(pending.pop((ri, ci))); ci += 1
                        td = next(it, None)
                        if td is None: break
                        txt = "\n".join(p.get_text(" ", strip=True) for p in td.find_all("p")) or td.get_text(" ", strip=True)
                        rs, cs = int(td.get("rowspan", 1)), int(td.get("colspan", 1))
                        for dc in range(cs):
                            v = txt if dc == 0 else ""
                            out.append(v)
                            for dr in range(1, rs):
                                pending[(ri + dr, ci)] = v
                            ci += 1
                    while (ri, ci) in pending:
                        out.append(pending.pop((ri, ci))); ci += 1
                    grid.append(out)
                w = max(map(len, grid)) if grid else 0
                grid = merge_header([r + [""] * (w - len(r)) for r in grid])
                keep = [k for k in range(w) if any((r[k] or "").strip() for r in grid)]
                grid = [[r[k] for k in keep] for r in grid]
                w = len(keep)
                k = 1
                while grid and k < w:
                    if all(r[k] == r[k - 1] for r in grid):
                        for r in grid: del r[k]
                        w -= 1
                    else:
                        k += 1
                for i, r in enumerate(grid):
                    units.append(("row", [cell_text(x) for x in r], tno, i == 0))
            elif not el.find_parent("table"):
                if el.find("table"):
                    el = BeautifulSoup(str(el), "xml")
                    for tb in el.find_all("table"): tb.decompose()
                t = el.get_text(" ", strip=True)
                if t: units.append(("line", t))
    walk(body)
    return units


def fix_name(u):
    if u[0] == "line": return ("line", u[1].replace("한국철도공사", "누리철도㈜"))
    return ("row", [x.replace("한국철도공사", "누리철도㈜") for x in u[1]], u[2], u[3])


def unit_sq(u):
    return sq(u[1]) if u[0] == "line" else sq("".join(u[1]))


def unit_hit(u, target):
    """조각 글(target, 공백 제거)에 이 단위가 얼마나 들어 있는지 0~1."""
    if u[0] == "line":
        s = sq(u[1])
        return 1.0 if s and s in target else 0.0
    toks = [t for x in u[1] for t in re.findall(r"[^\s|]{2,}", x)]
    if not toks: return 0.0
    return sum(sq(t) in target for t in toks) / len(toks)


def render(units):
    out, cur_t, header = [], None, None
    for u in units:
        if u[0] == "line":
            cur_t = None
            out.append(u[1].replace("한국철도공사", "누리철도㈜"))
            continue
        cells, tno, is_head = u[1], u[2], u[3]
        if len(cells) == 1 or sum(1 for c in cells if c.strip()) == 0:
            if cells and cells[0].strip():
                out.append(cells[0].replace("한국철도공사", "누리철도㈜"))
            cur_t = None
            continue
        if tno != cur_t:
            cur_t = tno
            if out and out[-1].startswith("|"):
                out.append("")  # 표가 바로 이어지면 빈 줄로 나눠야 서로 다른 표로 읽힘
            if is_head:
                header = cells
                out.append("| " + " | ".join(cells) + " |")
                out.append("|" + "---|" * len(cells))
                continue
            hdr = header if header and len(header) == len(cells) else [""] * len(cells)
            out.append("| " + " | ".join(hdr) + " |")
            out.append("|" + "---|" * len(cells))
        out.append("| " + " | ".join(c.replace("한국철도공사", "누리철도㈜") for c in cells) + " |")
    return "\n".join(out)




# 분수(위·아래로 쌓인 숫자)는 자동 추출로 표현이 안 돼서 원문을 보고 직접 적음
OVERRIDE = {"r12-0039": """[별표]
경비 반납의 산정(算定) 기준(제15조 관련)
| 기준 구분 | 반납액 |
|---|---|
| 1. 제15조제1호 · 제4호 · 제5호에 해당하는 직원 | 소요경비 전액 |
| 2. 제15조제2호에 해당하는 직원 | 소요경비 × 1/2 |
| 3. 제15조제3호에 해당하는 직원 | 소요경비 × (의무복무개월수 - 근무개월수) / 의무복무개월수 |
<비고>
가. 의무복무개월수 및 근무개월수를 계산할 때 15일 이상은 1개월로 계산한다.
나. 제2호의 교육기간 중 휴학하는 경우에는 교육계획부서의 장에게 사전 승인을 받아야 하며, 휴학 이전에 지원받은 교육기간에 대해서는 교육비를 중복하여 지원하지 않는다."""}


def extract():
    CH = {}
    for l in open(REGS, encoding="utf-8"):
        x = json.loads(l)
        if x["chunk_id"] in TABLE_IDS: CH[x["chunk_id"]] = x
    groups = {}
    for cid, c in CH.items():
        groups.setdefault((c["document_id"], c["article"]), []).append(c)

    result = {}
    for (doc, art), parts in groups.items():
        parts.sort(key=lambda c: c["chunk_id"])
        src = RAW / (doc + (".pdf" if parts[0]["source_file"].endswith(".pdf") else ".hwp"))
        if src.suffix == ".pdf":
            p0 = parts[0]["page"]
            units = pdf_units(src, range(p0, p0 + 4 + len(parts)))
        else:
            units = hwp_units(src)
        units = [fix_name(u) for u in units]
        targets = [sq(c["text"]) for c in parts]
        # 첫 조각의 첫 머리 줄 위치에서 시작, 마지막 조각과 맞는 단위까지
        head = sq(parts[0]["text"].split("\n")[0])[:12]
        start = next((i for i, u in enumerate(units) if u[0] == "line" and sq(u[1]).startswith(head[:8])), None)
        if start is None:
            start = max(range(len(units)), key=lambda i: unit_hit(units[i], targets[0]))
        assign, best_prev = {}, 0
        misses = 0
        first_head = sq(parts[0]["text"].split("\n")[0])[:8]
        for i in range(start, len(units)):
            if i > start and units[i][0] == "line" and re.match(r"^\s*[\[【]\s*별\s*[표지]", units[i][1]) \
                    and not sq(units[i][1]).startswith(first_head):
                break
            scores = [unit_hit(units[i], t) for t in targets]
            b = max(range(len(parts)), key=lambda k: (scores[k], -abs(k - best_prev)))
            if scores[b] < 0.5:
                misses += 1
                if misses >= 6 and i > start + 2:
                    break
                continue
            misses = 0
            b = max(b, best_prev); best_prev = b
            assign.setdefault(b, []).append(i)
        for k, c in enumerate(parts):
            idx = assign.get(k, [])
            sel = [units[i] for i in idx]
            # 이어지는 조각: 원래 조각처럼 별표 머리 줄을 앞에 다시 붙임
            if k > 0:
                head_lines = c["text"].split("\n")[:3]
                pre = [l for l in head_lines if not any(u[0] == "line" and sq(u[1]) == sq(l) for u in sel)
                       and sq(l) in sq(parts[0]["text"][:300])]
                sel = [("line", l) for l in pre] + sel
            new = render(sel)
            # 표 밖 줄은 원래 조각의 같은 줄(띄어쓰기 포함)을 그대로 씀
            old_by_sq = {}
            for l in c["text"].split("\n"):
                old_by_sq.setdefault(sq(l), l)
            new = "\n".join(l if l.startswith("|") else old_by_sq.get(sq(l), l) for l in new.split("\n"))
            cov_old = sq(c["text"]); cov_new = sq(new)
            # 원래 글자 중 새 글에 없는 글자 비율 (빠진 내용 점검)
            lost = sum(1 for w in set(re.findall(r"[가-힣A-Za-z0-9]{2,}", c["text"])) if sq(w) not in cov_new)
            words = len(set(re.findall(r"[가-힣A-Za-z0-9]{2,}", c["text"])))
            result[c["chunk_id"]] = dict(old=c["text"], new=new, units=len(sel), tables=sum(u[0] == "row" for u in sel),
                                         lost_words=lost, words=words)
            print(f"{c['chunk_id']} {art} part{k+1}: 단위 {len(sel)} 표행 {result[c['chunk_id']]['tables']} "
                  f"빠진 단어 {lost}/{words} 길이 {len(c['text'])}→{len(new)}")
    for k, v in OVERRIDE.items():
        if k in result: result[k]["new"] = v; result[k]["override"] = True

    out = {k: {"old_sha1": hashlib.sha1(result[k]["old"].encode()).hexdigest(), "text": result[k]["new"]}
           for k in TABLE_IDS if k in result}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("→", OUT, len(out))


def fixes() -> dict:
    out = json.loads(OUT.read_text(encoding="utf-8"))
    ported = json.loads(PORTED.read_text(encoding="utf-8"))
    assert not set(out) & set(ported), "두 표 파일에 같은 조각이 있음"
    return {**out, **ported}


def apply():
    fix = fixes()
    for p in (REGS, LAWS, HANG):
        if not p.exists(): continue
        lines = p.read_text(encoding="utf-8").split("\n")
        n = 0
        for i, l in enumerate(lines):
            if not l.strip(): continue
            x = json.loads(l)
            f = fix.get(x["chunk_id"])
            if not f or x["text"] == f["text"]: continue
            if hashlib.sha1(x["text"].encode()).hexdigest() != f["old_sha1"]:
                print(f"건너뜀 {x['chunk_id']}: 원래 글이 바뀜 (표를 다시 만들 것)"); continue
            x["text"] = f["text"]; lines[i] = json.dumps(x, ensure_ascii=False); n += 1
        p.write_text("\n".join(lines), encoding="utf-8")
        print(p.relative_to(HERE), "표 교체", n)
    fold_form_articles()
    hide_broken_delegation(fix)


def fold_form_articles():
    """서식 안의 "제N조" 가 조문으로 잘린 조각 → 앞 서식의 이어지는 조각으로 (rag_build.py 규칙과 같음).
    예: 전문직 직원 운영 세칙 별지 1 근로계약서의 제1조(당사자)~제10조(기타). 원문을 다시 읽지 않고 data/regs 에 반영"""
    if not REGS.exists(): return
    lines = REGS.read_text(encoding="utf-8").split("\n")
    form, n, changed = {}, 0, collections.Counter()   # 문서 → 지금 이어지는 서식 조각
    for i, l in enumerate(lines):
        if not l.strip(): continue
        x = json.loads(l)
        d = x["document_id"]
        if x["chunk_type"] == "서식":
            form[d] = x
        elif x["chunk_type"] == "조문" and d in form:
            f = form[d]
            x.update(chunk_type="서식", article=f["article"], article_title=f["article_title"],
                     categories=f["categories"], searchable=False)
            lines[i] = json.dumps(x, ensure_ascii=False); n += 1; changed[d] += 1
        else:
            form.pop(d, None)
    REGS.write_text("\n".join(lines), encoding="utf-8")
    docs_p = REGS.parent / "documents.json"
    if changed and docs_p.exists():
        docs = json.loads(docs_p.read_text(encoding="utf-8"))
        for doc in docs:
            if doc["document_id"] in changed:
                doc["searchable"] = sum(1 for l in lines if l.strip() and (y := json.loads(l))["document_id"] == doc["document_id"] and y["searchable"])
        docs_p.write_text(json.dumps(docs, ensure_ascii=False, indent=1), encoding="utf-8")
    print("서식 안의 조 → 서식 조각", n, dict(changed))


DELEGATION = dict(chunk_type="별표", article="별표 1", article_title="본사 전결사항")


def hide_broken_delegation(fix):
    """위임전결 별표 1(본사 전결사항)은 부칙 뒤에 붙어 '부칙' 조각으로 잘렸고, 결재권자 열이 사라져 'ㅇ'만 남음.
    - 진짜 부칙(글이 '부칙'으로 시작, r32-0013)을 뺀 나머지는 '별표 1' 조각으로 → 제8조 "별표 1과 같다"와 연결됨
    - 표로 옮겨 적은 조각(PORTED)만 검색 대상 (#23 이후 r32-0014~0037 전부 옮겨 적어 숨길 조각 없음). 나머지는 답할 근거가 안 되고
      출장·채용·보수 같은 낱말로 다른 질문에 끼어들어서 뺌 (2026-11-27 골든셋 6문항에서 확인)"""
    hidden = set()
    for p in (REGS, HANG):
        if not p.exists(): continue
        lines = p.read_text(encoding="utf-8").split("\n")
        for i, l in enumerate(lines):
            if not l.strip(): continue
            x = json.loads(l)
            if x["document_id"] != "r32" or x["chunk_type"] == "전결항목": continue   # 업무 묶음 조각(rag_delegation.py)은 그대로
            broken = x["chunk_type"] == "부칙" and not x["text"].lstrip().startswith("부칙")
            if not (broken or x["article"] == DELEGATION["article"]): continue
            want = dict(DELEGATION, searchable=x["chunk_id"] in fix)
            if "article_id" in x:
                want.update(article_id=f"r32:{DELEGATION['article']}", hang="", granularity="그대로")
            if not want["searchable"]:
                hidden.add(x["chunk_id"])
            if any(x.get(k) != v for k, v in want.items()):
                x.update(want); lines[i] = json.dumps(x, ensure_ascii=False)
        p.write_text("\n".join(lines), encoding="utf-8")
        docs_p = p.parent / "documents.json"
        if docs_p.exists():
            docs = json.loads(docs_p.read_text(encoding="utf-8"))
            n = sum(1 for l in lines if l.strip() and (x := json.loads(l))["document_id"] == "r32" and x["searchable"])
            for d in docs:
                if d["document_id"] == "r32": d["searchable"] = n
            docs_p.write_text(json.dumps(docs, ensure_ascii=False, indent=1), encoding="utf-8")
    print("위임전결 별표 1로 바꿈, 그중 검색 제외", len(hidden), sorted(hidden))


if __name__ == "__main__":
    extract() if "--extract" in sys.argv else apply()
