"""퇴직연금 실데이터 받기(공공데이터포털 Open API 2종) → data/pension/api/ 에 원본 행 저장. 매일 돌려도 안전(변경분만).

실행: .venv/bin/python pension/pension_fetch_api.py [--days N] [--max-pages N] [--selftest]
필요: hr_db/.env 의 DATA_GO_KR_KEY (공공데이터포털에서 두 API 활용신청 후 발급, 채팅·코드에 적지 말 것)
  - 키가 없으면 "건너뜀" 으로 끝냄(종료 코드 0). 이미 받은 데이터는 그대로 두고 다음 단계가 그걸 씀

받는 곳 (명세 화면에서 확인한 주소·요청 항목. 응답 코드·단위·set1~4 순서는 키 발급 후 실제 호출로 확인 필요)
  1) 금융위원회_퇴직연금기본정보  apis.data.go.kr/1160100/service/GetRetirementPensionInfoService/getFundInfo
     요청: serviceKey, resultType=json, pageNo, numOfRows, beginBasDt(이상), endBasDt(미만)
     응답 항목: cmpyCd, cmpyNm, fndCd, fndNm, basDt, basprc, nPptAmt, ofrInstNm  → fund_rows.jsonl
  2) 한국산업은행_퇴직연금(원리금보장)상품 금리정보  apis.data.go.kr/B190030/rtpProductInfoService/rtpProductIrtList
     요청: serviceKey, pageNo, numOfRows, sBseYm, eBseYm (XML)
     응답 항목: bseYm, irtAlySttDt, irtAlyEndDt, prdNm, prdJinTrmCone, set1Irt~set4Irt  → kdb_rows.jsonl
변경 감지: 기준일(basDt)·기준월(bseYm) 상태를 state.json 에 저장해 그 이후분만 요청, 행 키로 중복 제거
결과 기록: data/pension/api/changes.json (새 행 수), state.json
호출 사이 0.3초 간격. 호출 주소(키 포함)는 로그에 남기지 않음
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = Path(os.environ.get("PENSION_DATA_DIR") or ROOT / "data" / "pension")
API = DATA / "api"

FSC_URL = "https://apis.data.go.kr/1160100/service/GetRetirementPensionInfoService/getFundInfo"
KDB_URL = "https://apis.data.go.kr/B190030/rtpProductInfoService/rtpProductIrtList"
OK_CODES = {"00", "0", "0000", "200", "INFO-000"}   # 성공 코드 (실제 호출로 확인 필요)
PAGE_ROWS = 1000


def read_key():
    k = os.environ.get("DATA_GO_KR_KEY")
    env = ROOT / ".env"
    if not k and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATA_GO_KR_KEY="):
                k = line.split("=", 1)[1].strip()
    return k or ""


def http_get(url, params, tries=3):
    q = urllib.parse.urlencode(params, safe="%+=")   # serviceKey 가 이미 인코딩된 키여도 그대로 전달
    err = None
    for i in range(tries):
        time.sleep(0.3)
        try:
            with urllib.request.urlopen(f"{url}?{q}", timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:            # 주소(키 포함)를 메시지에 넣지 않음
            err = type(e).__name__
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"호출 실패({err}): {url.split('/')[-1]}")


def as_list(x):
    if x in (None, ""):
        return []
    return x if isinstance(x, list) else [x]


def parse_fsc(text):
    """금융위 JSON → (items, totalCount). 오류 응답이면 예외"""
    try:
        j = json.loads(text)
    except ValueError:
        raise RuntimeError("금융위 응답이 JSON 이 아님: " + text[:120].replace("\n", " "))
    r = j.get("response") or j
    h = r.get("header") or {}
    if h.get("resultCode") not in OK_CODES:
        raise RuntimeError(f"금융위 오류 {h.get('resultCode')}: {h.get('resultMsg')}")
    b = r.get("body") or {}
    items = as_list((b.get("items") or {}).get("item") if isinstance(b.get("items"), dict) else b.get("items"))
    return items, int(b.get("totalCount") or 0)


def parse_kdb(text):
    """산업은행 XML → (items, totalCount). 오류 응답이면 예외"""
    root = ET.fromstring(text)
    if root.tag == "OpenAPI_ServiceResponse":   # 게이트웨이 오류 형식
        raise RuntimeError("공공데이터포털 오류: " + (root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or "?"))
    code = root.findtext("./header/resultCode")
    if code not in OK_CODES:
        raise RuntimeError(f"산업은행 오류 {code}: {root.findtext('./header/resultMsg')}")
    items = [{c.tag: (c.text or "").strip() for c in it} for it in root.findall("./body/items/item")]
    return items, int(root.findtext("./body/totalCount") or 0)


def paged(url, base, parse, max_pages):
    out, page, total = [], 1, None
    while page <= max_pages:
        items, total = parse(http_get(url, {**base, "pageNo": page, "numOfRows": PAGE_ROWS}))
        out += items
        if not items or len(out) >= total:
            break
        page += 1
    return out, total


def merge(path, rows, key_fn):
    old = {}
    if path.exists():
        for l in open(path, encoding="utf-8"):
            r = json.loads(l)
            old[key_fn(r)] = r
    before = len(old)
    for r in rows:
        old[key_fn(r)] = r
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for k in sorted(old):
            f.write(json.dumps(old[k], ensure_ascii=False) + "\n")
    return len(old) - before, len(old)


fund_key = lambda r: f"{r['fndCd']}|{r['basDt']}"
kdb_key = lambda r: f"{r['bseYm']}|{r['prdNm']}|{r['prdJinTrmCone']}|{r.get('irtAlySttDt', '')}"


def selftest():
    j = json.dumps({"response": {"header": {"resultCode": "00", "resultMsg": "OK"},
                                 "body": {"totalCount": 1, "items": {"item": {"fndCd": "F1", "basDt": "20261114"}}}}})
    assert parse_fsc(j) == ([{"fndCd": "F1", "basDt": "20261114"}], 1)
    j0 = json.dumps({"response": {"header": {"resultCode": "00"}, "body": {"totalCount": 0, "items": ""}}})
    assert parse_fsc(j0) == ([], 0)
    x = "<response><header><resultCode>00</resultCode></header><body><items><item><bseYm>202610</bseYm><prdNm>예금</prdNm></item></items><totalCount>1</totalCount></body></response>"
    assert parse_kdb(x) == ([{"bseYm": "202610", "prdNm": "예금"}], 1)
    for bad, fn in (('{"response":{"header":{"resultCode":"30","resultMsg":"KEY"}}}', parse_fsc),
                    ("<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg></cmmMsgHeader></OpenAPI_ServiceResponse>", parse_kdb)):
        try:
            fn(bad)
            raise SystemExit("오류 응답을 못 잡음")
        except RuntimeError:
            pass
    print("selftest 통과")


def main():
    if "--selftest" in sys.argv:
        return selftest()
    key = read_key()
    if not key:
        print("pension_fetch: DATA_GO_KR_KEY 없음 → 건너뜀 (기존 받은 데이터 유지)")
        return
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 365
    max_pages = int(sys.argv[sys.argv.index("--max-pages") + 1]) if "--max-pages" in sys.argv else 500
    API.mkdir(parents=True, exist_ok=True)
    sp = API / "state.json"
    st = json.load(open(sp)) if sp.exists() else {}
    today = dt.date.today()

    # 1) 펀드 기준가 (금융위)
    begin = st.get("fund_last_basDt") or (today - dt.timedelta(days=days)).strftime("%Y%m%d")
    end = (today + dt.timedelta(days=1)).strftime("%Y%m%d")
    rows, total = paged(FSC_URL, {"serviceKey": key, "resultType": "json", "beginBasDt": begin, "endBasDt": end}, parse_fsc, max_pages)
    new_f, all_f = merge(API / "fund_rows.jsonl", rows, fund_key)
    if rows:
        st["fund_last_basDt"] = max(r["basDt"] for r in rows)

    # 2) 원리금보장 금리 (산업은행, 마지막으로 받은 달부터 다시: 월 데이터 수정 대비)
    s_ym = st.get("kdb_last_ym") or "202101"
    e_ym = today.strftime("%Y%m")
    krows, _ = paged(KDB_URL, {"serviceKey": key, "sBseYm": s_ym, "eBseYm": e_ym}, parse_kdb, max_pages)
    new_k, all_k = merge(API / "kdb_rows.jsonl", krows, kdb_key)
    if krows:
        st["kdb_last_ym"] = max(r["bseYm"] for r in krows)

    json.dump(st, open(sp, "w"), ensure_ascii=False, indent=1)
    json.dump({"run_date": today.isoformat(), "fund_requested": len(rows), "fund_new": new_f, "fund_total": all_f,
               "kdb_requested": len(krows), "kdb_new": new_k, "kdb_total": all_k}, open(API / "changes.json", "w"), ensure_ascii=False, indent=1)
    print(f"pension_fetch: 펀드 기준가 새 {new_f}행(누적 {all_f}), 원리금보장 금리 새 {new_k}행(누적 {all_k})")


if __name__ == "__main__":
    main()
