"""rag_tables.py 결과 점검: 표가 들어갔는지, 표 모양이 맞는지, 조각 ID가 그대로인지."""
import json
from pathlib import Path

HERE = Path(__file__).parent
load = lambda n: json.loads((HERE / "data/regs" / n).read_text(encoding="utf-8"))
FIX = load("table_markdown.json")
PORTED = load("table_markdown_ported.json")


def chunks(rel):
    return {json.loads(l)["chunk_id"]: json.loads(l) for l in (HERE / rel).read_text(encoding="utf-8").splitlines() if l.strip()}


def test_tables_applied_to_regs_and_hang():
    hang = chunks("data/hang/chunks.jsonl")
    src = {**chunks("data/regs/chunks.jsonl"), **chunks("data/laws/chunks.jsonl")}
    for cid, f in {**FIX, **PORTED}.items():
        assert src[cid]["text"] == f["text"], ("조문 단위", cid)
        if cid in hang:
            assert hang[cid]["text"] == f["text"], ("항 단위", cid)
        else:                       # 계산식 조문: 항 단위에서는 cid-01, -02 … 로 나뉨
            assert src[cid]["chunk_type"] == "조문" and f"{cid}-01" in hang, cid
    for cid in FIX:
        assert src[cid]["chunk_type"] == "별표"


def test_no_chunk_in_both_files():
    assert not set(FIX) & set(PORTED)


def test_markdown_tables_have_even_columns():
    for cid, f in {**FIX, **PORTED}.items():
        block = []
        for line in f["text"].split("\n") + [""]:
            if line.startswith("|"):
                block.append(line)
                continue
            if block:
                widths = {l.replace("\\|", "").count("|") for l in block}
                assert len(widths) == 1, (cid, block[0])
                assert set(block[1].replace("|", "")) <= {"-"}, (cid, block[1])
            block = []


def test_appendix_head_kept():
    """별표 머리 줄(첫 줄)은 원래 글 그대로여야 별표 인식·별표↔조 연결이 유지됨."""
    for cid, f in FIX.items():
        assert f["text"].lstrip().startswith(("[별표", "【별표")), cid
    before = chunks("data/regs/chunks.jsonl")
    for cid, f in PORTED.items():
        if cid in before and f["text"].startswith("[별표"):
            assert before[cid]["chunk_type"] == "별표", cid
