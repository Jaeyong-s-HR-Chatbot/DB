"""rag_delegation.py 결과 점검: 큰 표의 결재 표시 행이 빠짐없이 같은 부서의 작은 조각에 있고, 연결표에는 안 섞임."""
import json
from pathlib import Path

from rag_delegation import SOURCE_HEAD, delegation_chunks, _leaf, _squash

HERE = Path(__file__).parent
CHUNKS = [json.loads(l) for l in (HERE / "data/hang/chunks.jsonl").read_text(encoding="utf-8").split("\n") if l.strip()]
SMALL = [c for c in CHUNKS if c["chunk_type"] == "전결항목"]


def test_file_matches_generator():
    assert SMALL and SMALL == delegation_chunks(CHUNKS)


def test_ids_are_separate():
    assert len({c["chunk_id"] for c in CHUNKS}) == len(CHUNKS)
    assert len({c["article_id"] for c in SMALL}) == len(SMALL)
    assert all(c["searchable"] and c["chunk_id"].startswith("r32-D") for c in SMALL)


def test_every_marked_row_is_in_a_small_chunk_of_same_department():
    have = set()
    for c in SMALL:
        lines = c["text"].split("\n")
        dept = _leaf(lines[0].split("부서: ", 1)[1])
        for l in lines[2:]:
            if ": 전결권자 " in l:
                task, who = l[2:].rsplit(": 전결권자 ", 1)
                have.add((dept, _squash(task), who))
    for c in CHUNKS:
        if c["chunk_type"] == "전결항목" or c["document_id"] != "r32" or SOURCE_HEAD not in c["text"]:
            continue
        dept = "공통"
        for l in c["text"].split("\n"):
            if l.startswith("[부서:"):
                dept = l[5:-1]
            elif l.startswith("|"):
                cells = [x.strip() for x in l[1:-1].split("|")]
                if len(cells) == 2 and cells[1] and cells[0] != "직무내용" and not set(cells[0]) <= set("-"):
                    assert (_leaf(dept), _squash(cells[0]), cells[1]) in have, (c["chunk_id"], dept, cells)


def test_not_linked_as_appendix():
    links = (HERE / "data/hang/appendix_links.json").read_text(encoding="utf-8")
    assert "r32:별표 1:D" not in links
