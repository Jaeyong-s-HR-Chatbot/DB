"""조문·부칙 조각의 끊긴 낱말 줄바꿈 정리 ("직\\n원에게는" → "직원에게는").

실행: .venv\\Scripts\\python rag_unwrap.py [--dry-run] [--show N]
위치: rag_rechunk.py 다음, rag_appendix_links / rag_article_refs · 임베딩 · rag_load_hang 앞.
      (rechunk 전에 줄바꿈을 지우면 줄 맨 앞 ①②…로 항을 나누는 HANG 정규식이 못 찾으므로 반드시 rechunk 뒤)
입출력: data/hang/chunks.jsonl   — chunk_type 이 '조문'·'부칙' 인 조각의 text
        data/hang/articles.jsonl — 조문 원문 text (답변에 보여 주는 글)
        같은 파일을 제자리에서 고침. chunk_id·article_id·그 밖의 칸은 그대로 → 골든셋 정답 id 유지.
        몇 번 돌려도 결과가 같음 (이미 붙은 줄은 건드릴 줄바꿈이 없음).
        고치는 건 공백·줄바꿈뿐 (글자를 더하거나 빼지 않음).

안 건드리는 것: 전결항목(표에서 만든 조각, 칸 구분 줄바꿈과 섞임) · 서식안내 · 별표(마크다운 표·줄 구분이 의미 있음)

줄바꿈 하나하나를 보고 정함 (Kiwi space() 로 문장 전체를 교정하면 "제24 조", "가족 수당"처럼 과하게 띄움)
 1. 다음 줄이 ①~⑳ · "1. "·"1의2. " · 부칙의 "제8조 (…)"·"제9조 생략"·"부칙 <…>" · "<" · "[" · 제N장/절/관 제목으로 시작 → 줄바꿈 유지
 2. 앞 줄이 . : ; ) 」 > ] 로 끝남 (문장·항목 끝) → 줄바꿈 유지
 3. 다음 줄이 가. 나. 같은 목 번호 → 줄바꿈 유지
    "다."는 문장 끝("…한\\n다.")과 목 번호가 섞여 있어 따로 봄: 줄이 "다."만 있거나 "다. <개정…>"·"다. 다만,"이면 문장 끝,
    그 밖에 글이 이어지면 앞에 "나." 줄이 있거나 앞 낱말이 동사 어미(한·는·있…)가 아닐 때 목 번호
 4. 앞이 한글이고 다음 줄이 숫자로 시작 → 한 칸 띄워 붙임 ("<개정\\n2010.06.28.>" → "<개정 2010.06.28.>"). 단 "제\\n2장"은 "제2장"
 5. 앞이 숫자이고 다음 줄이 조·항·호·목·장·절·관으로 시작 → 붙임 ("제30\\n조를" → "제30조를")
 6. 나머지는 Kiwi 분석 점수로: 붙인 쪽(직원에게는)이 띄운 쪽(직 원에게는)보다 높으면 붙이고, 낮으면 띄움
 7. 점수가 같으면 두 쪽이 같은 형태소로 분석된 것이라 Kiwi로는 못 가림 → 같은 데이터 안에서 줄바꿈 없이 쓰인 낱말을 세어
    붙인 형태("요청하여야")가 띄운 형태("요청 하여야")보다 많이 나오면 붙이고, 적으면 띄움 ("각 호의")
 8. 그래도 근거가 없으면(두 형태 다 안 나옴): 숫자 + 단위("2\n개월")와 명사 + 하·되·시키("준수\n하여")는 붙이고,
    나머지는 띄움 ("120일의 유급휴가", "공고로 하여야")
"""
import argparse
import json
import re
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).parent
HANG_DIR = HERE / "data/hang"
TARGET_TYPES = {"조문", "부칙"}  # chunks.jsonl 에서 고칠 chunk_type

_kiwi = None


def kiwi():
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi  # 늦게 불러옴: 줄바꿈 규칙 시험에는 필요 없음
        _kiwi = Kiwi()
    return _kiwi


@lru_cache(maxsize=None)
def _score(s):
    return kiwi().analyze(s, top_n=1)[0][1]


# 줄 끝·줄 머리 공백은 스페이스·탭 말고 \xa0(NBSP)·전각 공백·\r 도 인정 (PDF·HWP 변환에서 섞여 들어옴)
BLANKS = " \t\xa0　\r"
# 다음 줄이 항 ①~⑳ · 호 "1. "·"1의2. " · 부칙 조문 머리("제8조 (…)"·"제9조 생략"·"부칙 <…>") · 개정표시 "<" · 링크·표 "[" · 장·절·관 제목이면 줄바꿈 유지
# (제N장은 "제2장의 규정은…" 같은 문장 속 인용과 구분하려고 뒤에 공백·줄끝이 오는 것만)
NEXT_KEEP = re.compile(
    r"[①-⑳]|\d+(?:의\d+)*\.(?:\s|$)|<|\[|제\s*\d+\s*[장절관](?!\S)"
    r"|제\s*\d+\s*조(?:의\s*\d+)?\s*(?:[(（]|생략)|부칙\s*(?:[(<（]|$)"   # 부칙 안의 "제8조 (다른 법률의 개정)"·"제9조 생략"·"부칙 <제…호>"
)
END = re.compile(r"[.:;)」>\]]$")
MOK = re.compile(r"[가-하]\.$")
HEADING_LINE = re.compile(r"^\s*제\s*\d+\s*[장절관][ \t\xa0]+[^\n.]{0,40}$")  # "제3장 복지후생" 한 줄
NA_LINE = re.compile(r"\s*나\.\s")                  # 목 "나." 로 시작하는 줄
VERB_END = re.compile(r"[한른된는있없니였했될할함]$")  # 문장을 끝내는 낱말의 끝 글자 ("…한\n다.")
UNIT = "조항호목장절관"                              # 숫자 뒤에 바로 붙는 법령 단위
COUNTER = re.compile(r"(?:개월|퍼센트|달러|[일월년주개명원시분초회세차점배건%])")  # 숫자 뒤에 붙여 쓰는 단위 (동점일 때만 씀)
HADA = re.compile(r"[하되]|시키")                    # 명사 + 하다·되다·시키다 동사로 이어지는 줄 머리
EPS = 1e-6


@lru_cache(maxsize=None)
def _noun_final(a):
    """a 의 마지막 형태소가 명사류(체언·어근)인지 (조사·어미로 끝나면 False)"""
    toks = kiwi().analyze(a, top_n=1)[0][0]
    return bool(toks) and toks[-1].tag in ("NNG", "NNP", "NNB", "XR", "SN", "XSN")


def build_vocab(texts):
    """줄 안쪽 낱말·이웃 낱말쌍 빈도. 줄 첫·끝 낱말은 줄바꿈에 잘렸을 수 있어 뺌 (점수 동점 가르기용)."""
    words, pairs = Counter(), Counter()
    for text in texts:
        for line in text.split("\n"):
            t = line.split()
            if len(t) >= 3:
                words.update(t[1:-1])
                pairs.update(zip(t[1:-2], t[2:-1]))
    return words, pairs


def _is_mok_da(a, head, na_before):
    """'다.' 로 시작하는 줄이 목 번호(가. 나. 다.)인지, 문장 끝("…한\\n다.")인지."""
    after = head[2:].strip()
    if not after or after[0] in "<[" or re.match(r"다만[,，\s]", after):
        return False                                   # "다." 만 있음 · 개정표시가 이어짐 · "다. 다만," → 문장 끝
    return na_before or not VERB_END.search(a)


def _glue(a, b, head="", na_before=False, vocab=None):
    """줄 끝 낱말 a 와 다음 줄 첫 낱말 b 사이를 어떻게 이을지: "\\n"(유지) · " "(띄움) · ""(붙임)"""
    if END.search(a):                                  # 문장·항목 끝 → 줄바꿈 유지
        return "\n"
    if b == "다." and _is_mok_da(a, head, na_before):  # 목 번호 다.
        return "\n"
    if MOK.match(b) and b != "다.":                    # 가. 나. … 목 번호
        return "\n"
    if a == "제" and re.match(r"\d", b):               # 제\n2장 → 제2장
        return ""
    if re.match(r"\d", b) and re.search(r"[가-힣]$", a):  # <개정\n2010… → 한 칸 띄움
        return " "
    if re.search(r"\d$", a) and b[0] in UNIT:          # 제30\n조를 → 제30조를
        return ""
    if re.match(r"다[)）,，]", b):                      # …한\n다)지급에 → …한다)지급에 ("다"로 시작하는 낱말은 없음)
        return ""
    sg, ss = _score(a + b), _score(a + " " + b)
    if abs(sg - ss) > EPS:
        return "" if sg > ss else " "
    g, sp = (vocab[0].get(a + b, 0), vocab[1].get((a, b), 0)) if vocab else (0, 0)
    if g != sp:                                        # 동점: 줄바꿈 없이 쓰인 형태가 더 많은 쪽
        return "" if g > sp else " "
    if re.search(r"\d$", a) and COUNTER.match(b):      # 근거가 없을 때: 2\n개월 → 2개월
        return ""
    if HADA.match(b) and _noun_final(a):               # 준수\n하여 → 준수하여 (공고로\n하여야 는 조사로 끝나 띄움)
        return ""
    return " "


def unwrap(text, vocab=None):
    """줄을 왼쪽에서 오른쪽으로 한 번씩만 보며 이음. 이은 결과를 다음 줄과 다시 비교하므로
    "자\\n녀는"처럼 앞 줄바꿈을 유지했어도 그 뒤 줄바꿈이 빠지지 않고, 한 낱말이 3줄에 걸쳐도 처리됨."""
    lines = text.split("\n")
    out = [lines[0]]
    na_before = bool(NA_LINE.match(lines[0]))
    for nxt in lines[1:]:
        cur, head = out[-1], nxt.lstrip(BLANKS)
        a = (cur.split() or [""])[-1]
        b = (head.split() or [""])[0]
        if not a or not b or NEXT_KEEP.match(head) or HEADING_LINE.match(cur):
            out.append(nxt)                            # 빈 줄 · 항/호/표/제목 앞 · 제목 줄 뒤
            na_before = na_before or bool(NA_LINE.match(nxt))
            continue
        g = _glue(a, b, head, na_before, vocab)
        if g == "\n":
            out.append(nxt)
            na_before = na_before or bool(NA_LINE.match(nxt))
        else:
            out[-1] = cur.rstrip(BLANKS) + g + head
    return "\n".join(out)


# 고친 뒤에도 남은 "한글 ↔ 한글" 줄바꿈 점검용. 규칙상 일부러 남기는 것(목 번호 가. 나. 다. · 장절 제목 줄)은 뺌.
# 그래도 나오면 규칙 빈틈이니 --show 로 보고 규칙을 보태기
def leftovers(text):
    out, lines, na_before = [], text.split("\n"), False
    for cur, nxt in zip(lines, lines[1:]):
        na_before = na_before or bool(NA_LINE.match(cur))
        head = nxt.lstrip(BLANKS)
        b = (head.split() or [""])[0]
        a = (cur.split() or [""])[-1]
        if (re.search(r"[가-힣]$", cur.rstrip(BLANKS)) and re.match(r"[가-힣]", head)
                and not NEXT_KEEP.match(head) and not HEADING_LINE.match(cur)
                and not (MOK.match(b) and b != "다.")
                and not (b == "다." and _is_mok_da(a, head, na_before))):
            out.append(f"{cur.rstrip()[-14:]}⏎{head[:14]}")
    return out


STRICT = re.compile(r"[가-힣]\n[가-힣]")  # 단순 확인 기준 (목 번호 "가."·제N장 제목처럼 일부러 남기는 것도 셈)


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def write_jsonl(path, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", type=Path, default=HANG_DIR, help="chunks.jsonl·articles.jsonl 이 있는 폴더 (기본 data/hang)")
    ap.add_argument("--dry-run", action="store_true", help="파일은 안 쓰고 결과만 출력")
    ap.add_argument("--show", type=int, default=0, help="고친 뒤에도 남은 끊김 예시를 N개 출력")
    args = ap.parse_args()

    chunks = read_jsonl(args.dir / "chunks.jsonl")
    arts_path = args.dir / "articles.jsonl"
    articles = read_jsonl(arts_path) if arts_path.exists() else []
    vocab = build_vocab([c["text"] for c in chunks] + [a["text"] for a in articles])  # 고치기 전 글 기준

    changed, left_chunks, samples = 0, 0, []
    broken_before = broken_after = 0  # Notion 확인 기준: [가-힣]\n[가-힣] 가 있는 조각 수
    for c in chunks:
        if c.get("chunk_type") not in TARGET_TYPES:
            continue
        broken_before += bool(STRICT.search(c["text"]))
        new = unwrap(c["text"], vocab)
        broken_after += bool(STRICT.search(new))
        if new != c["text"]:
            changed += 1
            c["text"] = new
        lo = leftovers(new)
        if lo:
            left_chunks += 1
            samples += [f"{c['chunk_id']}: {s}" for s in lo]
    a_changed = 0
    for a in articles:
        new = unwrap(a["text"], vocab)
        if new != a["text"]:
            a_changed += 1
            a["text"] = new

    print(f"조각 {changed}개, 조문 원문 {a_changed}건 고침 / 고친 뒤에도 끊김이 남은 조각 {left_chunks}개")
    print(f"확인 기준 [가-힣]\\n[가-힣] 가 있는 조문·부칙 조각: {broken_before} → {broken_after}개 (목표: 100개 아래)")
    print("  ※ 목 번호·장절 제목·부칙의 '제N조 (…)'·'부칙' 줄처럼 일부러 남긴 줄바꿈도 이 숫자에 들어 있음 → 낱말 중간 끊김은 위 '남은 조각'")
    for s in samples[:args.show]:
        print("  남음:", s)
    if args.dry_run:
        print("(--dry-run: 파일은 바꾸지 않음)")
        return
    write_jsonl(args.dir / "chunks.jsonl", chunks)
    if articles:
        write_jsonl(arts_path, articles)
    print(f"저장: {args.dir}")


if __name__ == "__main__":
    sys.exit(main())
