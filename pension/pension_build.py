"""퇴직연금 표 만들기 → data/pension/build/*.csv  (pension_load.py 가 읽음)

실행: .venv/bin/python pension/pension_build.py [--source demo|api]     기본 demo (팀 결정: 펀드는 가상으로)
  demo : data/pension/pension_products.csv(가상 상품 42개) + demo_prices.csv(가상 기준가, pension_sim.py) + 가상 사업자·직원 제도
  api  : data/pension/api/*.jsonl(실제 공시 API, pension_fetch_api.py) + 가상 사업자·직원 제도   ← 보관 중인 선택 경로. 지금은 쓰지 않음
출력 (build/): pension_products / pension_product_prices / pension_guaranteed_rates / pension_provider_products / pension_providers / pension_plans
원본이 비어 있으면 아무것도 쓰지 않고 끝냄 (기존 build 유지)
수익률(ret_1m, ret_3m, ret_1y)은 저장값이 아니라 기준가 이력에서 계산한 값 (이력이 모자라면 빈 칸)
"""
import bisect
import csv
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
DATA = Path(os.environ.get("PENSION_DATA_DIR") or ROOT / "data" / "pension")
API, OUT = DATA / "api", DATA / "build"
SOURCE = sys.argv[sys.argv.index("--source") + 1] if "--source" in sys.argv else "demo"

PRODUCT_COLS = ["fund_code", "fund_name", "company_code", "company_name", "source_org", "product_type", "risk_grade",
                "guaranteed", "risky_asset", "risk_label", "term_months", "rate_type", "allowed_plan_types", "first_price_date", "last_price_date", "last_nav",
                "ret_1m", "ret_3m", "ret_1y", "ret_3y", "vol_1y", "mdd_1y", "is_real"]
LINK_COLS = ["provider_id", "fund_code", "on_sale", "fee_rate", "fee_source", "is_demo"]
RATE_COLS = ["base_ym", "rate_start", "rate_end", "product_name", "term", "set1_rate", "set2_rate", "set3_rate", "set4_rate"]


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")] if p.exists() else []


def rd(p):
    return list(csv.DictReader(open(p, encoding="utf-8-sig")))


def num(s):
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


def write(name, rows, cols):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / name, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def date8(s):
    s = str(s)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else ""


def returns(series):
    """series: [(date_iso, nav)] 날짜순 → 1개월·3개월·1년 수익률 (기준일 N일 전 이하의 가장 가까운 가격 대비, 이력이 모자라면 '')"""
    ds = [d for d, _ in series]
    last_d, last_v = series[-1]
    ld = dt.date.fromisoformat(last_d)
    out = {}
    for k, days in (("ret_1m", 30), ("ret_3m", 91), ("ret_1y", 365), ("ret_3y", 1095)):
        t = (ld - dt.timedelta(days=days)).isoformat()
        i = bisect.bisect_right(ds, t) - 1
        out[k] = round(last_v / series[i][1] - 1, 4) if i >= 0 and ds[0] <= t else ""
    # 최근 1년 변동성(일 로그수익률 표준편차 x sqrt(252))·최대낙폭 (이력이 1년 모자라면 '')
    t = (ld - dt.timedelta(days=365)).isoformat()
    i = bisect.bisect_right(ds, t) - 1
    if i >= 0 and ds[0] <= t:
        w = [v for _, v in series[i:]]
        r = [math.log(b / a) for a, b in zip(w, w[1:]) if a > 0 and b > 0]
        m = sum(r) / len(r) if r else 0
        out["vol_1y"] = round(math.sqrt(sum((x - m) ** 2 for x in r) / max(len(r) - 1, 1)) * math.sqrt(252), 4)
        peak, mdd = w[0], 0.0
        for v in w:
            peak = max(peak, v)
            mdd = min(mdd, v / peak - 1)
        out["mdd_1y"] = round(mdd, 4)
    else:
        out["vol_1y"] = out["mdd_1y"] = ""
    return out


def finish(products, prices, rates, links):
    by = {}
    for p in prices:
        by.setdefault(p["fund_code"], []).append((p["price_date"], p["nav"]))
    for pr in products:
        s = sorted(by.get(pr["fund_code"], []))
        pr["first_price_date"] = s[0][0] if s else ""
        pr["last_price_date"] = s[-1][0] if s else ""
        pr["last_nav"] = s[-1][1] if s else ""
        pr.update(returns(s) if s else dict(ret_1m="", ret_3m="", ret_1y="", ret_3y="", vol_1y="", mdd_1y=""))
    prices.sort(key=lambda x: (x["fund_code"], x["price_date"]))
    write("pension_products.csv", products, PRODUCT_COLS)
    write("pension_product_prices.csv", prices, ["fund_code", "price_date", "nav", "net_asset"])
    write("pension_guaranteed_rates.csv", rates, RATE_COLS)
    write("pension_provider_products.csv", links, LINK_COLS)
    for n in ("pension_providers.csv", "pension_plans.csv", "pension_contributions.csv", "pension_holdings.csv", "pension_events.csv", "pension_transactions.csv"):
        shutil.copyfile(DATA / n, OUT / n)
    return len(products), len(prices), len(rates), len(links)


def build_demo():
    src, pf = DATA / "pension_products.csv", DATA / "demo_prices.csv"
    if not src.exists() or not pf.exists():
        print("pension_build: 가상 상품·기준가 없음 → 건너뜀 (gen_pension.py, pension_sim.py 먼저)")
        return None
    prov = {p["provider_id"]: p for p in rd(DATA / "pension_providers.csv")}
    products, links = [], []
    for r in rd(src):
        pv = prov[r["provider_id"]]
        products.append(dict(fund_code=r["product_id"], fund_name=r["product_name"], company_code=r["provider_id"],
                             company_name=pv["provider_name"], source_org="시연용 가상", product_type=r["product_type"],
                             risk_grade=r["risk_grade"], guaranteed=r["guaranteed"], risky_asset=r["risky_asset"],
                             risk_label=r["risk_label"], term_months=r["term_months"], rate_type=r["rate_type"],
                             allowed_plan_types=r["allowed_plan_types"], is_real="N"))
        links.append(dict(provider_id=r["provider_id"], fund_code=r["product_id"], on_sale=r["on_sale"],
                          fee_rate=r["product_fee_rate"], fee_source="시연용 가정", is_demo="Y"))
    prices = [dict(fund_code=x["product_id"], price_date=x["price_date"], nav=float(x["nav"]), net_asset="") for x in rd(pf)]
    return finish(products, prices, demo_rates(rd(src)), links)


def demo_rates(rows):
    """원리금보장 상품의 월별 약정금리(시연). set1_rate = 그 달 신규 가입분 적용 연금리, set2~4 는 비움.
    모든 원리금보장 상품에 월별 rate_shift 를 더함(신규 가입 금리). 확정형 보유분은 가입한 달 금리로 고정(holdings.locked_rate), 금리연동형은 이 금리를 그대로 따라감. 기준월 2026-11 에서 0, 이전·이후 달은 고정 난수로 이어짐"""
    import pension_sim
    today = dt.date.today()
    last = (max(today.year, 2026), today.month if today.year >= 2026 else 12)
    months, m = [], (2025, 11)
    while m <= last:
        months.append(m)
        m = pension_sim.ym_add(m, 1)
    out = []
    for r in rows:
        if r["guaranteed"] != "Y":
            continue
        for ym in months:
            y, mo = ym
            nxt = pension_sim.ym_add(ym, 1)
            rate = max(0.01, float(r["base_rate"]) + pension_sim.rate_shift(ym))   # 신규 약정금리는 달마다 시장을 따라 변함(확정형은 가입한 달 금리로 고정되므로 holdings.locked_rate)
            term = f"{int(r['term_months']) // 12}년" if r["term_months"] and int(r["term_months"]) % 12 == 0 else (f"{r['term_months']}개월" if r["term_months"] else "수시")
            out.append(dict(base_ym=f"{y}{mo:02d}", rate_start=f"{y}-{mo:02d}-01",
                            rate_end=(dt.date(nxt[0], nxt[1], 1) - dt.timedelta(days=1)).isoformat(),
                            product_name=r["product_name"], term=term, set1_rate=round(rate * 100, 3),
                            set2_rate="", set3_rate="", set4_rate=""))
    return out


def build_api():
    funds, kdb = jl(API / "fund_rows.jsonl"), jl(API / "kdb_rows.jsonl")
    if not funds:
        print("pension_build: 받은 펀드 데이터 없음 → 건너뜀 (기존 build 유지)")
        return None
    prices = []
    for r in funds:
        nav = num(r.get("basprc"))
        if nav is not None and date8(r.get("basDt")):
            prices.append(dict(fund_code=r["fndCd"], price_date=date8(r["basDt"]), nav=nav, net_asset=num(r.get("nPptAmt")) or ""))
    latest = {}
    for r in sorted(funds, key=lambda r: r["basDt"]):
        latest[r["fndCd"]] = r
    products = [dict(fund_code=c, fund_name=r.get("fndNm", ""), company_code=r.get("cmpyCd", ""), company_name=r.get("cmpyNm", ""),
                     source_org=r.get("ofrInstNm", ""), product_type="미분류", risk_grade="", guaranteed="", risky_asset="",
                     allowed_plan_types="", is_real="Y") for c, r in sorted(latest.items())]
    rates = [dict(base_ym=r["bseYm"], rate_start=date8(r.get("irtAlySttDt")), rate_end=date8(r.get("irtAlyEndDt")),
                  product_name=r["prdNm"], term=r.get("prdJinTrmCone", ""),
                  **{f"set{i}_rate": ("" if num(r.get(f"set{i}Irt")) is None else num(r.get(f"set{i}Irt"))) for i in range(1, 5)}) for r in kdb]
    ids = [p["provider_id"] for p in rd(DATA / "pension_providers.csv")]
    links = []
    for p in products:
        h = int(hashlib.sha1(p["fund_code"].encode()).hexdigest(), 16)
        for i in range(1 + h % len(ids)):
            links.append(dict(provider_id=ids[((h // 7) + i) % len(ids)], fund_code=p["fund_code"], on_sale="Y",
                              fee_rate="", fee_source="미정", is_demo="Y"))
    return finish(products, prices, rates, links)


def main():
    res = build_demo() if SOURCE == "demo" else build_api()
    if res:
        print(f"pension_build({SOURCE}): 상품 {res[0]}개, 기준가 {res[1]}행, 원리금보장 금리 {res[2]}행, 사업자 연결 {res[3]}행")


if __name__ == "__main__":
    main()
