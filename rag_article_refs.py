"""조 ↔ 조 인용 연결표 만들기 → data/hang/article_refs.json + deploy/initdb/10_article_refs.sql (rag.article_refs)

조 본문의 "「취업규칙」 제23조에 따르고", "제12조를 준용한다", "제5조에도 불구하고" 같은 인용을 찾아
DB 안에 있는 조끼리 이어요. 검색할 때는 이 표만 조회해요 (글을 다시 파싱하지 않음).

인용 대상 문서 정하기
- 「문서 이름」 제N조 → 그 문서 (DB에 없는 문서면 버림)
- 앞말: 법령은 '법'·'이 법'(법률 자신, 시행령·시행규칙에서는 상위 법), '영'·'이 영'(시행령), '규칙'·'이 규칙'(시행규칙)
        내부규정은 '규정'(시행세칙에서는 상위 규정, 규정에서는 자신), '이 규정'·'세칙'·'내규'(자신)
        '같은 법'·'동법' → 같은 조에서 바로 앞에 이름이 나온 문서
- 앞말 없음: "제60조 및 제61조"처럼 앞 인용과 및·,·또는·부터 등으로 이어지면 앞 인용과 같은 문서, 아니면 자기 문서
- '같은 조 제N항', 자기 자신 인용은 뺌

kind (인용 묶음 바로 뒤 말로 정함)
- 준용: "…을 준용한다"           → 검색: 인용된 조를 후보에 더함
- 따른다: "…에 따른다/따라/의한다/정하는"  → 검색: 인용된 조를 후보에 더함
- 예외: "…에도 불구하고"          → 검색: 반대 방향. to_article(기본 조)이 뽑히면 from_article(예외 조)을 더함
- 기타: 그 밖의 언급              → 검색에는 안 씀 (기록만)

실행: python rag_article_refs.py      (data/hang/articles.jsonl · chunks.jsonl 사용)
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
HANG = HERE / "data/hang"
OUT = HANG / "article_refs.json"
SQL = HERE / "deploy/initdb/10_article_refs.sql"


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def squash(s):
    return re.sub(r"\s+", "", s or "")


ARTICLES = jl(HANG / "articles.jsonl")
_CH = jl(HANG / "chunks.jsonl")
DOC_NAME = {c["document_id"]: c["doc_name"] for c in _CH}
DOC_KIND = {c["document_id"]: c["doc_kind"] for c in _CH}
DOC_BY_NAME = {squash(n): d for d, n in DOC_NAME.items()}
NAMES_LONGEST = sorted(DOC_BY_NAME, key=len, reverse=True)   # 「」 없이 쓴 이름 찾기용 (긴 이름 먼저)
ARTICLE_IDS = {a["article_id"] for a in ARTICLES}

HEAD = re.compile(r"^\s*(?:부칙\s*)?제\s*\d+\s*조(?:\s*의\s*\d+)?\s*[\(（][^)）\n]*[\)）]\s*")
REF = re.compile(
    r"(?:「(?P<named>[^」\n]{2,40})」\s*|(?P<pre>(?<![가-힣])(?:이\s*법|이\s*영|이\s*규칙|이\s*규정|이\s*세칙|같은\s*법|동\s*법|동\s*규정"
    r"|법|영|규칙|규정|세칙|내규))\s*)?"
    r"(?P<same>같은\s*조\s*)?제\s*(?P<n>\d+)\s*조(?:\s*의\s*(?P<s>\d+))?(?:\s*제\s*\d+\s*항)?(?:\s*제\s*\d+\s*호)?(?:\s*[가-하]\s*목)?")
CHAIN = re.compile(r"^\s*(?:\([^)]{0,30}\)\s*)?(?:까지\s*)?(?:및|,|·|ㆍ|또는|와|과|부터|내지|~|∼|에서|이나|나)\s*$")
UNKNOWN_DOC = re.compile(r"[가-힣」](?:법|령|규칙|규정|세칙|내규|지침|강령)$")   # 앞말이 문서 이름처럼 끝나는데 DB에 없음
HISTORY = re.compile(r"\[[^\]\n]{0,80}(?:종전|이동|신설|삭제|개정)[^\]\n]{0,80}\]|<[^>\n]{0,120}>")


def family(doc):
    """문서 이름 → (밑이름, 종류). 예: '고용보험법 시행령' → ('고용보험법', '시행령')"""
    n = squash(DOC_NAME.get(doc, ""))
    for suf in ("시행세칙", "시행령", "시행규칙"):
        if n.endswith(suf):
            return n[: -len(suf)], suf
    return n, ""


def by_prefix(doc, pre):
    """앞말 → 인용 대상 문서 (없으면 None). '같은 법'은 호출하는 쪽에서 처리"""
    p = squash(pre)
    base, kind = family(doc)
    if DOC_KIND.get(doc) != "법령" and p in ("이법", "법", "이영", "영", "이규칙", "규칙"):
        return None                                             # 내부규정의 '법 제N조'는 어느 법인지 모름
    sibling = lambda suf: DOC_BY_NAME.get(base + suf)
    if p in ("이법", "법"):
        return doc if kind == "" else (DOC_BY_NAME.get(base) if p == "법" else None)
    if p in ("이영", "영"):
        return doc if kind == "시행령" else sibling("시행령")
    if p in ("이규칙", "규칙"):
        return doc if kind == "시행규칙" else sibling("시행규칙")
    if p == "규정":
        return DOC_BY_NAME.get(base) if kind == "시행세칙" else doc
    if p in ("이규정", "이세칙", "세칙", "내규", "동규정"):
        return doc
    return None


def bare_name(before):
    """인용 바로 앞이 DB 문서 이름으로 끝나면 그 문서 ('취업규칙 제23조', '인사규정시행세칙 제5조')"""
    s = squash(before)
    return next((DOC_BY_NAME[n] for n in NAMES_LONGEST if s.endswith(n)), None)


def article_id(doc, n, m=None):
    cands = [f"{doc}:제{n}조"] if not m else [f"{doc}:제{n}의{m}조", f"{doc}:제{n}조의{m}"]
    return next((c for c in cands if c in ARTICLE_IDS), None)


def kind_of(tail):
    t = squash(tail)
    # "(퇴직금 중간정산)에", " 및 제4항에", "ㆍ제3호에", "제2호까지에" 같은 앞부분은 건너뜀
    t = re.sub(r"^(?:\([^)]{0,30}\)|(?:및|,|ㆍ|·|또는|부터)?제\d+(?:항|호|목)(?:까지)?|[가-하]목|까지)+", "", t)
    if re.match(r"^(?:의)?(?:규정)?(?:을|를)?(?:각각)?준용", t):
        return "준용"
    if re.match(r"^(?:의)?(?:규정)?(?:에도|에도불구|에불구)불?구?하고|^에도불구하고", t):
        return "예외"
    if re.match(r"^(?:의)?(?:규정)?(?:에|에서)?(?:따른|따라|따르|의한|의하|의거|정하는|정한|정해진|규정한|규정된|규정하는)", t):
        return "따른다"
    return "기타"


def refs_of(a):
    """조 하나 → [(대상 조, kind)]"""
    doc = a["document_id"]
    body = HEAD.sub("", a["text"], count=1)
    body = HISTORY.sub(" ", body)                               # "[종전 제47조에서 이동 …]" 같은 개정 이력은 인용이 아님
    ms = list(REF.finditer(body))
    out, prev_end, prev_doc, last_named = [], None, None, None
    groups, cur = [], []                                        # 및·, 로 이어진 인용 묶음
    for m in ms:
        if m["named"]:
            target = DOC_BY_NAME.get(squash(m["named"]))
            last_named = target
        elif m["pre"]:
            p = squash(m["pre"])
            target = last_named if p in ("같은법", "동법") else by_prefix(doc, p)
        elif cur and CHAIN.match(body[prev_end:m.start()]):
            target = prev_doc
        elif (bare := bare_name(body[max(0, m.start() - 40):m.start()])) is not None:
            target = bare                                       # "취업규칙 제23조" (「」 없이 쓴 이름)
        elif UNKNOWN_DOC.search(squash(body[max(0, m.start() - 20):m.start()])):
            target = None                                       # "동법 시행규칙 제34조"처럼 DB에 없는 문서
        else:
            target = doc
        if cur and not CHAIN.match(body[prev_end:m.start()]):
            groups.append(cur); cur = []
        cur.append((m, target))
        prev_end, prev_doc = m.end(), target
    if cur:
        groups.append(cur)
    for g in groups:
        kind = kind_of(body[g[-1][0].end():g[-1][0].end() + 50])
        for m, target in g:
            if m["same"] or not target:
                continue
            t = article_id(target, m["n"], m["s"])
            if t and t != a["article_id"]:
                out.append((t, kind))
    return out


def write_sql(rows):
    q = lambda s: "'" + s.replace("'", "''") + "'"
    sql = [
        "-- 조 ↔ 조 인용 연결표. rag_article_refs.py 가 만듦 (손으로 고치지 말 것)",
        "-- 검색: 1차로 찾은 조의 kind 준용·따른다 → to_article 을 후보 조로 더함 (한 단계만)",
        "--       kind 예외 → 반대 방향: to_article(기본 조)이 뽑히면 from_article(예외 조)을 더함",
        "SET client_encoding = 'UTF8';   -- Windows psql 기본(CP949)으로 읽어도 깨지지 않게",
        "CREATE TABLE IF NOT EXISTS rag.article_refs (",
        "    from_article text NOT NULL,",
        "    to_article   text NOT NULL,",
        "    kind         text NOT NULL,",
        "    PRIMARY KEY (from_article, to_article, kind));",
        "COMMENT ON TABLE rag.article_refs IS '조 ↔ 조 인용. from_article 본문이 to_article 을 인용 (둘 다 rag.articles.article_id)';",
        "COMMENT ON COLUMN rag.article_refs.kind IS '준용: …을 준용한다 / 따른다: …에 따른다·따라·의한다·정하는 / 예외: …에도 불구하고 (from 이 to 의 예외) / 기타: 그 밖의 언급';",
        "CREATE INDEX IF NOT EXISTS article_refs_to_idx ON rag.article_refs (to_article);",
        "BEGIN;",
        "DELETE FROM rag.article_refs;",
        "INSERT INTO rag.article_refs (from_article, to_article, kind) VALUES",
        ",\n".join(f"({q(f)}, {q(t)}, {q(k)})" for f, t, k in rows) + ";",
        "COMMIT;",
    ]
    SQL.write_text("\n".join(sql) + "\n", encoding="utf-8")


def main():
    rows = sorted({(a["article_id"], t, k) for a in ARTICLES for t, k in refs_of(a)})
    by_kind = Counter(k for _, _, k in rows)
    cross = Counter(k for f, t, k in rows if f.split(":")[0] != t.split(":")[0])
    fan = Counter(f for f, _, k in rows if k in ("준용", "따른다"))
    data = {
        "how": "조 본문의 '「이름」·법·영·규정… 제N조' 인용, 뒤 말로 kind (준용/따른다/예외/기타)",
        "refs": [{"from": f, "to": t, "kind": k} for f, t, k in rows],
        "count": {"rows": len(rows), "by_kind": dict(by_kind), "cross_document": dict(cross),
                  "articles_with_follow": len(fan), "max_follow_per_article": max(fan.values(), default=0)},
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    write_sql(rows)
    print(f"인용 {len(rows)}행 {dict(by_kind)} · 다른 문서 {dict(cross)} · 따라갈 인용이 있는 조 {len(fan)}"
          f" (최대 {data['count']['max_follow_per_article']}) → {OUT}, {SQL}")


if __name__ == "__main__":
    main()
