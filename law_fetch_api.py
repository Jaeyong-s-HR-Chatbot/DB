"""법령 받기(법제처 Open API): 13개 법령의 '현행' 판(기준일 시점에 시행 중인 판)만 받아 data/laws/api/ 에 저장.

실행: .venv/bin/python law_fetch_api.py      (.env 의 LAW_OC 필요, 호출 IP 등록 필요)
- 기준일: BASE_DATE (기본 2026-11-11). 시행일이 기준일보다 뒤인 판(시행 예정)은 받지 않음. 시행 예정판은 나중에 자동화로 처리
- 법령명으로 lawSearch → 이름이 정확히 같은 '현행' 1건 → lawService(JSON) 로 본문 전체(조문·부칙·별표) 저장
- 저장: data/laws/api/<일련번호>.json (원본 응답), data/laws/api/index.json (법령별 판 정보),
        data/laws/attach_api/ (별표 텍스트), data/laws/attach_api_timing.json (law_build.py 가 읽는 별표 목록)
- 호출 사이 0.3초 간격 (과도한 호출 방지)
"""
import json
import subprocess
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
API = HERE / "data/laws/api"
ATT = HERE / "data/laws/attach_api"
API.mkdir(parents=True, exist_ok=True)
ATT.mkdir(parents=True, exist_ok=True)
OC = dict(l.strip().split("=", 1) for l in open(HERE / ".env") if "=" in l)["LAW_OC"]
BASE_DATE = "20261111"
NAMES = [  # law_build.LAWS 와 같은 13개
    "근로기준법", "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률", "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 시행령",
    "고용보험법", "고용보험법 시행령", "근로자퇴직급여 보장법 시행령", "고용상 연령차별금지 및 고령자고용촉진에 관한 법률",
    "산업안전보건법 시행규칙", "철도안전법 시행규칙", "민방위기본법", "성매매방지 및 피해자보호 등에 관한 법률 시행령",
    "성폭력방지 및 피해자보호 등에 관한 법률 시행령", "가정폭력방지 및 피해자보호 등에 관한 법률 시행령"]


def get(url):
    time.sleep(0.3)
    return subprocess.run(["curl", "-s", "--max-time", "120", url], capture_output=True).stdout


def flat(x):
    return "\n".join(flat(i) for i in x) if isinstance(x, list) else str(x)


index, att_rec, t_all = [], [], time.time()
for name in NAMES:
    q = urllib.parse.quote(name)
    L = json.loads(get(f"https://www.law.go.kr/DRF/lawSearch.do?OC={OC}&target=law&type=JSON&query={q}&display=30"))["LawSearch"]["law"]
    L = L if isinstance(L, list) else [L]
    hit = [x for x in L if x["법령명한글"].replace(" ", "") == name.replace(" ", "") and x["현행연혁코드"] == "현행"]
    assert len(hit) == 1, f"{name}: 현행 {len(hit)}건"
    h = hit[0]
    assert h["시행일자"] <= BASE_DATE, f"{name}: 시행일 {h['시행일자']} 이 기준일 {BASE_DATE} 보다 뒤 (시행 예정판)"
    t = time.time()
    raw = get(f"https://www.law.go.kr/DRF/lawService.do?OC={OC}&target=law&type=JSON&MST={h['법령일련번호']}")
    sec = time.time() - t
    (API / f"{h['법령일련번호']}.json").write_bytes(raw)
    b = json.loads(raw)["법령"]
    units = (b.get("별표") or {}).get("별표단위", [])
    units = units if isinstance(units, list) else [units]
    items = []
    for u in units:
        if u.get("별표구분") != "별표":
            continue
        txt = flat(u.get("별표내용", ""))
        fn = f"{h['법령일련번호']}_{u.get('별표번호', '')}_{u.get('별표가지번호', '')}.txt"
        (ATT / fn).write_text(txt, encoding="utf-8")
        items.append({"no": u.get("별표번호", ""), "sub": u.get("별표가지번호", ""), "title": u.get("별표제목", ""), "chars": len(txt), "file": fn})
    n_art = len([a for a in b["조문"]["조문단위"] if a.get("조문여부") == "조문"])
    index.append({"title": h["법령명한글"], "mst": h["법령일련번호"], "law_id": h["법령ID"], "kind": h["법령구분명"], "dept": h["소관부처명"],
                  "promulgated": h["공포일자"], "effective": h["시행일자"], "base_date": BASE_DATE, "articles": n_art, "byulpyo": len(items),
                  "url": f"https://www.law.go.kr/법령/{h['법령명한글'].replace(' ', '')}"})
    att_rec.append({"law": h["법령명한글"], "mst": h["법령일련번호"], "sec": round(sec, 2), "items": items})
    print(f"{h['법령명한글'][:30]:32} MST {h['법령일련번호']} 공포 {h['공포일자']} 시행 {h['시행일자']} 조문 {n_art:3} 별표 {len(items):3} {sec:.1f}초")
json.dump(index, open(API / "index.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump({"method": "Open API lawService JSON (법령당 1회, 현행판)", "sec_total": round(time.time() - t_all, 1), "calls": len(att_rec),
           "byulpyo_total": sum(len(r["items"]) for r in att_rec), "laws": att_rec},
          open(HERE / "data/laws/attach_api_timing.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n{len(index)}개 법령, 총 {time.time() - t_all:.1f}초, 기준일 {BASE_DATE}")
