"""rag_tables.py 결과 점검: 표가 들어갔는지, 표 모양이 맞는지, 조각 ID가 그대로인지."""
import json
from pathlib import Path

HERE = Path(__file__).parent
FIX = json.loads((HERE / "data/regs/table_markdown.json").read_text(encoding="utf-8"))


def chunks(rel):
    return {json.loads(l)["chunk_id"]: json.loads(l) for l in (HERE / rel).read_text(encoding="utf-8").splitlines() if l.strip()}


def test_tables_applied_to_regs_and_hang():
    for rel in ("data/regs/chunks.jsonl", "data/hang/chunks.jsonl"):
        ch = chunks(rel)
        for cid, f in FIX.items():
            assert ch[cid]["text"] == f["text"], (rel, cid)
            assert ch[cid]["chunk_type"] == "별표"


def test_markdown_tables_have_even_columns():
    for cid, f in FIX.items():
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
