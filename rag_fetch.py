"""7단계-1 규정 원문 받기: ALIO 코레일 내부규정 중 인사 업무 관련 33건의 최신 파일을 data/regs/raw 에 저장.

실행: .venv/bin/python rag_fetch.py
- 목록: rules/regulations.yaml (규정명 · 핵심/보조 · 팀 카테고리)
- 각 규정 상세 페이지에서 파일 목록을 읽고, 파일명 속 개정일이 가장 늦은 PDF/HWP 1개를 받음 (zip 묶음 제외)
- 이미 받은 파일은 건너뜀. 받은 목록은 data/regs/manifest.json
"""
import json
import re
import ssl
import subprocess
import urllib.parse
from pathlib import Path

import yaml

HERE = Path(__file__).parent
RAW = HERE / "data/regs/raw"
REGS = yaml.safe_load(open(HERE / "rules/regulations.yaml", encoding="utf-8"))
BASE = "https://www.alio.go.kr"


def curl(url, data=None, out=None):
    cmd = ["curl", "-sL", "--max-time", "60", url]
    if data is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(data)]
    if out:
        cmd += ["-o", str(out)]
        subprocess.run(cmd, check=True)
        return None
    return subprocess.run(cmd, check=True, capture_output=True).stdout.decode("utf-8", "replace")


def rule_list():
    rows, page = {}, 1
    while True:
        j = json.loads(curl(f"{BASE}/item/itemReportListSusi.json",
                            {"pageNo": page, "apbaId": "C0268", "reportFormRootNo": "21110", "search_word": ""}))
        for r in j["data"]["result"]:
            rows[r["title"]] = r
        if not j["data"]["page"]["nextPage_is"] and page >= j["data"]["page"]["totalPage"]:
            break
        page += 1
        if page > j["data"]["page"]["totalPage"]:
            break
    return rows


def date_key(name):
    m = re.search(r"(\d{4})\s*년(?:도)?\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", name)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    rows = rule_list()
    manifest = []
    for reg in REGS["regulations"]:
        r = rows[reg["name"]]
        q = urllib.parse.urlencode(dict(disclosureNo="null", apbaId="C0268", nowcode="21110", reportFormNo="21110",
                                        table_name="COMM_RULE", idx_name="RULE_NO", idx=r["idx"], reportGbn="N",
                                        bid_type=r["bidType"]))
        page = curl(f"{BASE}/item/itemBoard21110.do?{q}")
        files = []
        for m in re.finditer(r"rulefiledown\.json\?fileNo=(\d+)", page):
            tail = re.sub(r"<[^>]+>", " ", page[m.end():m.end() + 400])
            head = re.sub(r"<[^>]+>", " ", page[max(0, m.start() - 400):m.start()])
            nm = re.findall(r"[^\s>][^<>]*?\.(?:pdf|hwp|hwpx|zip)", head + " " + tail, re.I)
            name = (nm[-1] if nm else "").strip()
            files.append((m.group(1), name))
        docs = [(no, nm) for no, nm in files if re.search(r"\.(pdf|hwp|hwpx)$", nm, re.I)]
        if not docs:
            print(f"✗ {reg['name']}: 파일 없음")
            continue
        no, nm = max(docs, key=lambda x: (date_key(x[1]), int(x[0])))
        ext = nm.rsplit(".", 1)[-1].lower()
        dest = RAW / f"{reg['id']}.{ext}"
        if not dest.exists():
            curl(f"{BASE}/download/rulefiledown.json?fileNo={no}", out=dest)
        magic = dest.read_bytes()[:8]
        kind = "pdf" if magic.startswith(b"%PDF") else "hwp" if magic.startswith(b"\xd0\xcf\x11\xe0") else \
               "hwpx" if magic.startswith(b"PK") else "?"
        manifest.append(dict(id=reg["id"], name=reg["name"], file_name=nm, file_no=no, saved=dest.name, kind=kind,
                             size=dest.stat().st_size, alio_date=r["stDate"]))
        print(f"{'✓' if kind != '?' else '✗'} {reg['id']} {reg['name']:<22} {kind:<4} {dest.stat().st_size // 1024:>6}KB  {nm}")
    json.dump(manifest, open(HERE / "data/regs/manifest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n{len(manifest)}/{len(REGS['regulations'])}건 받음 → data/regs/raw")


if __name__ == "__main__":
    main()
