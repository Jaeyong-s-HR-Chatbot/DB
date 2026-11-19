"""조문 조각 → 항(①②…) 단위 조각으로 다시 자르기.

실행: .venv\\Scripts\\python rag_rechunk.py
입력: data/regs/chunks.jsonl, data/laws/chunks.jsonl (조문 단위, rag_build.py·law_build.py 결과)
출력: data/hang/chunks.jsonl  (항 단위 조각, rag.chunks 와 같은 칸 + article_id·hang·granularity)
      data/hang/articles.jsonl (조문 전체 원문 1건 = 1행, 검색은 항으로 하고 답할 때 조문 전체를 보여 주기용)
      data/hang/documents.json (규정+법령 문서 목록, 조각 수 갱신)
      data/hang/old_to_new.json (예전 chunk_id → article_id·새 chunk_id 목록. 골든셋 정답을 항 단위로 옮길 때)

자르는 규칙
- 검색 대상 '조문'만 다시 자름. 별표·부칙·서식안내·팀 가정 조각·검색 제외 조각은 그대로 (chunk_id도 그대로)
- 원래 1,500자에서 나뉜 조문(part 1, 2 …)은 먼저 하나로 붙인 뒤 다시 자름
- 항이 2개 이상이면 항마다 한 조각. 항 앞 머리말(항 번호 없는 본문)은 첫 항에 붙임
- 항이 없거나 1개뿐이고 MAX_CHARS 이하면 조문 하나 = 조각 하나 (원래 조각과 글자가 같으면 chunk_id·임베딩 재사용)
- 한 항(또는 항 없는 조문)이 MAX_CHARS 를 넘으면 호(1. 2. …) 경계에서 나누고, 이어지는 조각 앞에 항 첫 문장을 다시 붙임
- 모든 조각 맨 앞에 "제N조(제목)"을 붙임 (법령 원문은 조문 머리가 본문에 없음) → 항만 떼어도 어느 조인지 보임
- chunk_id: 바뀐 조각은 "원래 첫 조각 id-항번호"(예: r04-0008-02), article_id: "문서id:조문"(예: r04:제7조)
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
SRC = [(HERE / "data/regs", "내부규정"), (HERE / "data/laws", "법령")]
OUT = HERE / "data/hang"
MAX_CHARS = 900

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
# 항 번호: 줄 맨 앞, 또는 첫 줄의 "제N조(제목) " 바로 뒤
HANG = re.compile(rf"(?:(?<=\n)|(?<=^)|(?<=\) ))\s*([{CIRCLED}])")
HO = re.compile(r"(?m)^\s*\d+(?:의\d+)?\.\s")
HEAD = re.compile(r"^\s*(?:부칙\s*)?제\s*\d+\s*조(?:\s*의\s*\d+)?\s*[\(（][^)）\n]*[\)）]\s*")


def head_of(c):
    return f"{c['article']}({c['article_title']})" if c["article_title"] else c["article"]


def join_parts(parts):
    text = ""
    for p in parts:
        text += p if not text or text.endswith("\n") or p.startswith("\n") else "\n" + p
    return text


def split_hang(body):
    """머리말 없앤 조문 본문 → [(항번호, 글)]. 항이 없으면 [("", 본문)]."""
    marks = [m for m in HANG.finditer(body)]
    # 순서대로 ①, ②, ③ … 인 것만 항으로 인정 (본문 속 "제①항" 같은 인용 방지)
    seq, want = [], 0
    for m in marks:
        if CIRCLED.index(m.group(1)) == want:
            seq.append(m)
            want += 1
    if len(seq) < 2:
        return [("", body.strip())]
    out = []
    lead = body[:seq[0].start()].strip()
    for i, m in enumerate(seq):
        end = seq[i + 1].start() if i + 1 < len(seq) else len(body)
        seg = body[m.start():end].strip()
        if i == 0 and lead:
            seg = lead + "\n" + seg
        out.append((m.group(1), seg))
    return out


def split_ho(text):
    """MAX_CHARS 넘는 항 → 호 경계로 묶어 나눔. 이어지는 조각 앞에 항 첫 문장(호 앞부분)을 붙임."""
    if len(text) <= MAX_CHARS:
        return [text]
    starts = [m.start() for m in HO.finditer(text)]
    if not starts:
        pieces = [text[i:i + MAX_CHARS] for i in range(0, len(text), MAX_CHARS)]
        return pieces
    lead = text[:starts[0]].strip()
    items = [text[s:e].strip() for s, e in zip(starts, starts[1:] + [len(text)])]
    lead_ctx = (lead[:200] + "…") if len(lead) > 200 else lead
    parts, cur = [], lead
    for it in items:
        if cur and len(cur) + len(it) + 1 > MAX_CHARS and cur != lead_ctx:
            parts.append(cur)
            cur = lead_ctx
        cur = (cur + "\n" + it) if cur else it
    parts.append(cur)
    return parts


OLD2NEW = {}  # 예전 chunk_id → {article_id, new: [새 chunk_id …]}


def rechunk(chunks):
    out, articles, i, seen = [], [], 0, {}
    while i < len(chunks):
        c = chunks[i]
        aid = f"{c['document_id']}:{c['article'] or c['chunk_id']}"
        if not (c["searchable"] and c["chunk_type"] == "조문"):
            # 같은 조문이 여러 조각으로 나뉜 별표·부칙 등은 그대로 두되 article_id 로 묶음
            out.append(dict(c, article_id=aid, hang="", granularity="그대로"))
            OLD2NEW[c["chunk_id"]] = dict(article_id=aid, new=[c["chunk_id"]])
            i += 1
            continue
        group = [c]
        while i + len(group) < len(chunks):
            n = chunks[i + len(group)]
            if n["document_id"] == c["document_id"] and n["article"] == c["article"] and n["part"] == group[-1]["part"] + 1:
                group.append(n)
            else:
                break
        i += len(group)
        # 한 문서에 같은 조문 번호가 두 번 나오는 경우(report.json "같은 조문 번호 두 번 이상") → 뒤의 것에 #2, #3
        seen[aid] = seen.get(aid, 0) + 1
        if seen[aid] > 1:
            aid = f"{aid}#{seen[aid]}"
        full = join_parts([g["text"] for g in group])
        start = len(out)
        head = head_of(c)
        body = HEAD.sub("", full, count=1)
        articles.append(dict(article_id=aid, document_id=c["document_id"], doc_kind=c["doc_kind"], doc_name=c["doc_name"],
                             article=c["article"], article_title=c["article_title"], effective_date=c["effective_date"],
                             text=full if full.lstrip().startswith(c["article"].split()[-1]) else f"{head} {full}"))
        hangs = split_hang(body)
        if len(hangs) == 1 and len(group) == 1 and len(full) <= MAX_CHARS:
            out.append(dict(c, article_id=aid, hang="", granularity="조"))  # 그대로 (임베딩 재사용)
        else:
            n = 0
            for mark, seg in hangs:
                for pi, piece in enumerate(split_ho(seg), 1):
                    n += 1
                    out.append(dict(c, chunk_id=f"{c['chunk_id']}-{n:02d}", part=pi, text=f"{head} {piece}",
                                    article_id=aid, hang=mark, granularity="항" if mark else "조"))
        for g in group:  # 예전 조각(part 1, 2 …) → 새 조각 목록 (골든셋 정답 옮기기용)
            OLD2NEW[g["chunk_id"]] = dict(article_id=aid, new=[x["chunk_id"] for x in out[start:]])
    return out, articles


def main():
    OUT.mkdir(exist_ok=True)
    all_chunks, all_articles, docs = [], [], []
    for folder, kind in SRC:
        cs = [json.loads(l) for l in open(folder / "chunks.jsonl", encoding="utf-8")]
        for c in cs:
            c.setdefault("doc_kind", kind)
        before = sum(c["searchable"] for c in cs)
        ch, arts = rechunk(cs)
        all_chunks += ch
        all_articles += arts
        ds = json.load(open(folder / "documents.json", encoding="utf-8"))
        for d in ds:
            d.setdefault("doc_kind", kind)
            mine = [c for c in ch if c["document_id"] == d["document_id"]]
            d.update(chunks=len(mine), searchable=sum(c["searchable"] for c in mine), chars=sum(len(c["text"]) for c in mine))
        docs += ds
        s = [c for c in ch if c["searchable"]]
        print(f"{kind}: 검색 조각 {before} → {len(s)}개 (항 {sum(c['granularity'] == '항' for c in s)}, "
              f"조 {sum(c['granularity'] == '조' for c in s)}, 그대로 {sum(c['granularity'] == '그대로' for c in s)}), "
              f"평균 {sum(len(c['text']) for c in s) // len(s)}자, 최대 {max(len(c['text']) for c in s)}자, 조문 {len(arts)}건")
    ids = [c["chunk_id"] for c in all_chunks]
    assert len(ids) == len(set(ids)), "chunk_id 중복"
    with open(OUT / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(OUT / "articles.jsonl", "w", encoding="utf-8") as f:
        for a in all_articles:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    json.dump(docs, open(OUT / "documents.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(OLD2NEW, open(OUT / "old_to_new.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"저장: {OUT} (조각 {len(all_chunks)}개, 조문 {len(all_articles)}건)")


if __name__ == "__main__":
    main()
