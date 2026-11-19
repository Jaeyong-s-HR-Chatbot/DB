"""가상 기준가 이력 생성 (시연용): 상품 42개의 영업일별 기준가를 만들어 data/pension/demo_prices.csv 에 씀.

실행: .venv/bin/python pension/pension_sim.py        (매일 돌려도 안전: 같은 날짜의 값은 항상 같고, 새 영업일이 생기면 그 날짜만 늘어남)
원리: 하루 가격 = 어제 가격 x exp(기대 추세 + 변동). 변동 = 시장 공통 충격(그날 모든 상품이 같이 받음) x 상품별 민감도 + 상품별 독립 충격
  - 충격은 (날짜, 상품) 이름으로 만든 난수라서 다시 돌려도 같은 결과 → 과거는 안 바뀌고 새 날짜만 이어 붙음 (ETL 의 "바뀐 것만" 과 같은 성질)
  - 위험등급 1 (원리금보장 예금·보험)은 하락 없이 매일 일정하게 증가
값은 전부 가정이며 실제 시장 통계가 아님. 화면에는 반드시 "가상 시세" 표시
"""
import csv
import datetime as dt
import math
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("PENSION_DATA_DIR") or ROOT / "data" / "pension")
START = dt.date(2023, 11, 14)     # 기준가 1,000 으로 시작하는 날 (3년 이력)
BASE = 1000.0
# 위험등급(한국 기준: 1 매우 높음 ~ 6 매우 낮음) → (연 변동성, 시장 민감도). 가정값. 기대수익률은 상품의 base_rate 를 씀
PARAMS = {6: (0.0, 0.0), 5: (0.02, 0.3), 4: (0.07, 0.9), 3: (0.11, 0.93), 2: (0.16, 0.95), 1: (0.22, 0.95)}
FAMILY_CORR = 0.92                # 같은 종류 상품(예: 국내주식형 펀드)끼리 상품 고유 충격의 상관
ANCHOR_YM = (2026, 11)            # 금리연동형 상품의 금리 경로 기준월(이 달의 금리 = base_rate)


def ym_add(ym, k):
    t = ym[0] * 12 + ym[1] - 1 + k
    return (t // 12, t % 12 + 1)


def rate_shift(ym):
    """금리연동형 상품의 월별 금리 변화(연 금리, 예: -0.002 = 0.2%p 낮음). 기준월=0, 이전 달은 거꾸로, 이후 달은 이어서. 고정 난수라 다시 돌려도 같다"""
    step = lambda m: gauss("steprate", m[0], m[1]) * 0.0006
    s, m = 0.0, ym
    while m > ANCHOR_YM:
        s += step(m); m = ym_add(m, -1)
    while m < ANCHOR_YM:
        m = ym_add(m, 1); s -= step(m)
    return s
DAYS = 252


def business_days(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:       # 공휴일은 반영하지 않음(가정)
            yield d
        d += dt.timedelta(days=1)


def gauss(*key):
    return random.Random("|".join(map(str, key))).gauss(0, 1)


def simulate(products, end):
    rows = []
    days = list(business_days(START, end))
    for p in products:
        vol, beta = PARAMS[int(p["risk_grade"])]
        mu = float(p["base_rate"])
        linked = p.get("rate_type") == "연동"
        price = BASE
        # 상품별로 기대수익률에 작은 차이를 줌(같은 등급이어도 똑같이 움직이지 않게)
        mu += (gauss("mu", p["product_id"]) * 0.0015) if vol > 0 else 0
        family = p["product_name"].split(" ", 1)[-1]      # 사업자 이름을 뺀 상품명: 같은 종류 상품은 같은 요인을 따라 움직임
        for i, d in enumerate(days):
            if i > 0:
                if vol == 0:
                    price *= math.exp((mu + (rate_shift((d.year, d.month)) if linked else 0.0)) / DAYS)
                else:
                    own = FAMILY_CORR * gauss("fam", family, d) + math.sqrt(1 - FAMILY_CORR ** 2) * gauss(p["product_id"], d)
                    z = beta * gauss("mkt", d) + math.sqrt(1 - beta ** 2) * own
                    price *= math.exp((mu - 0.5 * vol ** 2) / DAYS + vol * z / math.sqrt(DAYS))
            rows.append((p["product_id"], d.isoformat(), round(price, 2)))
    return rows


def main():
    src = DATA / "pension_products.csv"
    if not src.exists():
        sys.exit("pension_sim: pension_products.csv 없음 (pension/gen_pension.py 먼저)")
    products = list(csv.DictReader(open(src, encoding="utf-8-sig")))
    end = dt.date.today()
    rows = simulate(products, end)
    with open(DATA / "demo_prices.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["product_id", "price_date", "nav"])
        w.writerows(rows)
    last = max(r[1] for r in rows)
    print(f"pension_sim: 상품 {len(products)}개, 기준가 {len(rows)}행 ({START} ~ {last}, 영업일 {len(rows) // len(products)}일)")


if __name__ == "__main__":
    main()
