"""법령 별표 받기(PDF 방식): data/laws/attachments.json 의 별표(서식 제외)를 PDF로 받아 글자를 뽑아 data/laws/attach/ 에 저장.
실행: ~/ocr_local/bin/python law_attach.py     (pymupdf 필요)
- 받기·글자 추출 시간을 data/laws/attach_timing.json 에 기록 → 나중에 Open API 방식과 속도·품질 비교용
"""
import json
import subprocess
import time
from pathlib import Path

import pymupdf

HERE = Path(__file__).parent
OUT = HERE / "data/laws/attach"
OUT.mkdir(parents=True, exist_ok=True)
rows = [r for r in json.load(open(HERE / "data/laws/attachments.json", encoding="utf-8")) if r["kind"] == "별표"]
t_all = time.time()
rec, dl, ex = [], 0.0, 0.0
for i, r in enumerate(rows, 1):
    key = f"{i:03d}"
    pdf = OUT / f"{key}.pdf"
    t = time.time()
    if not pdf.exists():
        subprocess.run(["curl", "-sL", "--max-time", "90", "-o", str(pdf), r["pdf"]], check=True)
    d = time.time() - t
    t = time.time()
    try:
        doc = pymupdf.open(pdf)
        text = "\n".join(p.get_text() for p in doc)
        pages = len(doc)
    except Exception as e:
        text, pages = "", 0
    e = time.time() - t
    (OUT / f"{key}.txt").write_text(text, encoding="utf-8")
    dl += d
    ex += e
    rec.append({"key": key, "law": r["law"], "no": r["no"], "sub": r["sub"], "title": r["title"], "pages": pages,
                "chars": len(text), "sec_download": round(d, 2), "sec_extract": round(e, 2)})
    print(f"{key} {r['law'][:12]:12} 별표{r['no']} {pages}쪽 {len(text):6}자 {d:.1f}s  {r['title'][:36]}")
tot = time.time() - t_all
json.dump({"method": "PDF 링크 받기 + pymupdf 글자 추출", "count": len(rows), "sec_total": round(tot, 1),
           "sec_download": round(dl, 1), "sec_extract": round(ex, 1),
           "empty_text": sum(1 for x in rec if x["chars"] < 30), "items": rec},
          open(HERE / "data/laws/attach_timing.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n{len(rows)}개 총 {tot:.0f}초 (받기 {dl:.0f}초, 글자 추출 {ex:.1f}초), 글자 없는 것 {sum(1 for x in rec if x['chars'] < 30)}개")
