"""위임전결 본사 전결사항의 업무 묶음 조각: (부서, 업무) 하나 = 조각 하나.

왜: 별표 1 큰 표 조각은 하나에 약 80행·여러 부서가 들어 있어, "국내 출장은 누구 결재?" 같은 질문에
    해당 몇 줄이 묻혀 1위로 잘 안 올라옴.
무엇을: 큰 표 조각(r32-0013~0033)은 그대로 두고, 같은 내용을 업무별 작은 조각(r32-D0001~)으로 더 만듦.
    chunk_type='전결항목', article_id 는 조각마다 따로 → '같은 조의 항 펼치기'·조↔별표 연결로 한꺼번에 딸려오지 않음.
    조각 번호는 표의 순서라서, 표 내용을 바꾸면 번호가 밀릴 수 있음 (골든셋 정답에는 쓰지 말 것).
실행: rag_rechunk.py 가 자동으로 부름 (data/hang 에만 들어감. data/regs 는 바꾸지 않음)
"""
import re

SOURCE_HEAD = "| 직무내용 | 전결권자 |"
TOP = ("ㅇ", "○", "◌")           # 상위 업무 표시. '-', '‧', '(1)' 로 시작하면 앞 업무의 하위 항목


def _squash(s):
    return re.sub(r"[^가-힣0-9A-Za-z]", "", s)


def _leaf(dept):
    return _squash(dept.split(" / ")[-1])


def groups(chunks: list[dict]) -> list[dict]:
    """큰 표 조각을 순서대로 읽어 (부서, 상위 업무, [(직무내용, 전결권자)]) 묶음으로. 조각 경계에서 겹친 줄은 한 번만"""
    source = sorted((c for c in chunks if c["document_id"] == "r32" and c.get("chunk_type") != "전결항목"
                     and SOURCE_HEAD in c["text"]), key=lambda c: c["chunk_id"])
    out = []
    for c in source:
        dept = "공통"
        for line in c["text"].split("\n"):
            if line.startswith("[부서:"):
                dept = line[5:-1].strip()
                continue
            if not line.startswith("|"):
                continue
            cells = [x.strip() for x in line[1:-1].split("|")]
            if len(cells) != 2 or cells[0] == "직무내용" or set(cells[0]) <= set("-"):
                continue
            task, who = cells
            name = task.lstrip("ㅇ○◌ ")
            last = out[-1] if out else None
            same_dept = last is not None and _leaf(last["dept"]) == _leaf(dept)
            if not same_dept or (task.startswith(TOP) and _squash(name) != _squash(last["parent"])):
                out.append(dict(dept=dept, parent=name.lstrip("- "), rows=[], base=c))
            g = out[-1]
            if (task, who) not in g["rows"]:
                g["rows"].append((task, who))
    seen, uniq = set(), []
    for g in out:
        key = (_leaf(g["dept"]), _squash(g["parent"]), tuple((_squash(t), w) for t, w in g["rows"]))
        if key not in seen:
            seen.add(key)
            uniq.append(g)
    return uniq


def delegation_chunks(chunks: list[dict]) -> list[dict]:
    out = []
    for i, g in enumerate(groups(chunks), 1):
        lines = []
        for task, who in g["rows"]:
            item = task.lstrip("-ㅇ○◌ ")
            if who:
                lines.append(f"- {item}: 전결권자 {who}")
            elif _squash(item) != _squash(g["parent"]):
                lines.append(f"- {item}")
        if not any("전결권자" in x for x in lines):      # 결재 표시가 하나도 없는 제목 줄은 만들지 않음
            continue
        cid = f"r32-D{i:04d}"
        text = f"[위임전결 본사 전결사항] 부서: {g['dept']}\n업무: {g['parent']}\n" + "\n".join(lines)
        out.append(dict(g["base"], chunk_id=cid, chunk_type="전결항목", article="별표 1", article_title="본사 전결사항",
                        part=1, text=text, searchable=True, article_id=f"r32:별표 1:{cid[4:]}", hang="", granularity="그대로"))
    return out
