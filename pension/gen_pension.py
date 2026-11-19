"""퇴직연금 가상 데이터 생성 v2 (시연용). 기존 ETL·DB는 건드리지 않고 data/pension/ 에 CSV 6개만 만든다.
실행: .venv/bin/python pension/gen_pension.py   (같은 시드 → 같은 결과. 직원별 난수는 사번으로 만들어 순서에 안 흔들림)

만드는 표
  pension_providers      계약 퇴직연금사업자 4곳 (가상. 보험·증권·보험, 계좌수수료 = 운용관리 + 자산관리)
  pension_products       사업자별 상품. 원리금보장은 업권별(은행·증권(제휴 은행 예금)=예금, 증권=발행어음·RP·ELB, 보험=보험), 펀드·ETF·TDF는 공통
  pension_plans          직원 800명의 제도(DB/DC/미가입). 2012-01-01 제도 도입 후 입사자는 전원 가입
  pension_contributions  DC 연도별 부담금 (연간임금총액 x 1/12 x 가입 개월/12) + 가입자 추가납입
  pension_holdings       DC 계좌의 보유 상품·비중·평가액·좌수 (적립금 = 평가액 합계)
  pension_transactions   DC 월별 납입 거래내역 (최근 12개월, 급여일 25일)
  pension_events         중도인출·IRP 이전 이력 (퇴직금 = 근속 x 평균임금, 10원 미만 절상: 시행세칙 제8조)
위험등급은 한국 펀드 기준: 1 매우 높은 위험 ~ 6 매우 낮은 위험
"""
import csv
import datetime as dt
import hashlib
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pension_sim  # noqa: E402

OUT = ROOT / "data" / "pension"
OUT.mkdir(parents=True, exist_ok=True)
AS_OF = dt.date(2026, 11, 18)          # 적립금·평가액 기준일 (가상)
SYSTEM_START = dt.date(2012, 1, 1)     # 퇴직연금제도 도입일 (가정)
WAGE_GROWTH = 0.04                     # 과거 임금 역산에 쓰는 연 임금상승률 (가정)
RISK_LABEL = {1: "매우 높은 위험", 2: "높은 위험", 3: "다소 높은 위험", 4: "보통 위험", 5: "낮은 위험", 6: "매우 낮은 위험"}


def rng(*key):
    return random.Random("pension-v2|" + "|".join(map(str, key)))


def write(name, rows, cols):
    with open(OUT / name, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def rd(p):
    return list(csv.DictReader(open(p, encoding="utf-8-sig")))


def ceil10(x):
    return int(math.ceil(x / 10.0) * 10)


def months_between(a, b):
    """a~b 근속 개월 (시행세칙 제7조: 12개월=1년, 1개월 미만 잔여일은 1개월)"""
    m = (b.year - a.year) * 12 + (b.month - a.month)
    if b.day < a.day:
        m -= 1
    base = a + dt.timedelta(0)
    y, mo = a.year + (a.month - 1 + m) // 12, (a.month - 1 + m) % 12 + 1
    try:
        anchor = dt.date(y, mo, a.day)
    except ValueError:
        anchor = dt.date(y, mo, 28)
    return m + (1 if b > anchor else 0)


# ---------------------------------------------------------------- providers
providers = [
    dict(provider_id="P01", provider_name="태용생명", provider_type="보험", mgmt_fee_rate=0.0020, custody_fee_rate=0.0010),
    dict(provider_id="P02", provider_name="혜림증권", provider_type="증권", mgmt_fee_rate=0.0025, custody_fee_rate=0.0010),
    dict(provider_id="P03", provider_name="재현생명", provider_type="보험", mgmt_fee_rate=0.0030, custody_fee_rate=0.0010),
    dict(provider_id="P04", provider_name="코어뱅크", provider_type="은행", mgmt_fee_rate=0.0030, custody_fee_rate=0.0012),  # 은행 대면 DC 합계 0.43~0.49% 수준보다 약간 낮게(규모 구간 요율 가정)
]
for p in providers:
    p["account_fee_rate"] = round(p["mgmt_fee_rate"] + p["custody_fee_rate"], 4)
    p["is_demo"] = "Y"
PCOLS = ["provider_id", "provider_name", "provider_type", "account_fee_rate", "mgmt_fee_rate", "custody_fee_rate", "is_demo"]
write("pension_providers.csv", providers, PCOLS)

# ---------------------------------------------------------------- products
# (type, name, guaranteed, risk_grade(한국 기준), risky_asset, fee, base_rate(연), term_months, rate_type, allowed plans)
GUAR = {
    "은행": [
        ("예금", "정기예금 6개월형", 0.0285, 6, "확정"), ("예금", "정기예금 1년형", 0.0310, 12, "확정"),
        ("예금", "정기예금 2년형", 0.0315, 24, "확정"), ("예금", "정기예금 3년형", 0.0320, 36, "확정"),
    ],
    "증권": [   # 정기예금은 제휴 은행 예금을 증권사가 판매하는 구조 (증권사 퇴직연금의 원리금보장 상품에 실제로 있음)
        ("예금", "정기예금 6개월형", 0.0285, 6, "확정"), ("예금", "정기예금 1년형", 0.0310, 12, "확정"),
        ("예금", "정기예금 2년형", 0.0315, 24, "확정"), ("예금", "정기예금 3년형", 0.0320, 36, "확정"),
        ("발행어음", "발행어음 1년형", 0.0330, 12, "확정"), ("RP", "RP 90일형", 0.0290, 3, "확정"),
        ("ELB", "원금보장형 ELB 1년", 0.0335, 12, "확정"),
    ],
    "보험": [
        ("보험", "금리확정형 보험 3년", 0.0325, 36, "확정"), ("보험", "이율보증형 보험 5년", 0.0330, 60, "확정"),
        ("보험", "금리연동형 적립보험", 0.0305, 0, "연동"),
    ],
}
COMMON = [  # type, name, risk, risky, fee, base_rate, plans
    ("펀드", "단기채권형 펀드", 5, "N", 0.0030, 0.037, "DC,IRP"),
    ("펀드", "국공채 펀드", 5, "N", 0.0035, 0.030, "DC,IRP"),
    ("펀드", "채권혼합형 펀드", 4, "Y", 0.0070, 0.052, "DC,IRP"),
    ("펀드", "주식혼합형 펀드", 3, "Y", 0.0095, 0.075, "DC,IRP"),
    ("펀드", "국내주식형 펀드", 2, "Y", 0.0120, 0.098, "DC,IRP"),
    ("펀드", "해외주식형(선진국) 펀드", 2, "Y", 0.0140, 0.105, "DC,IRP"),
    ("펀드", "해외테마주식 펀드", 1, "Y", 0.0150, 0.125, "DC,IRP"),
    ("ETF", "국내대표지수 ETF", 2, "Y", 0.0015, 0.090, "DC,IRP"),
    ("ETF", "해외채권 ETF", 4, "N", 0.0020, 0.042, "DC,IRP"),
    ("TDF", "TDF 2030", 4, "Y", 0.0060, 0.058, "DC,IRP"),
    ("TDF", "TDF 2040", 3, "Y", 0.0070, 0.078, "DC,IRP"),
    ("TDF", "TDF 2050", 2, "Y", 0.0080, 0.095, "DC,IRP"),
]
products, n = [], 0
for p in providers:
    r = rng("prod", p["provider_id"])
    items = [(t, name, "Y", 6, "N", 0.0 if t in ("예금", "발행어음", "RP") else 0.0010, br, tm, rt, "DB,DC,IRP")
             for t, name, br, tm, rt in GUAR[p["provider_type"]]]
    items += [(t, name, "N", rk, ry, fee, br, 0, "", pl) for t, name, rk, ry, fee, br, pl in COMMON]
    for t, name, g, rk, ry, fee, br, tm, rt, plans in items:
        n += 1
        jitter = r.uniform(-0.0012, 0.0012)
        fee_j = 0.0 if fee == 0 else round(max(0.0005, fee + jitter), 4)
        br_j = round(br + (r.uniform(-0.0012, 0.0012) if g == "Y" else 0), 4)
        products.append(dict(
            product_id=f"PR{n:03d}", provider_id=p["provider_id"], product_name=f"{p['provider_name']} {name}",
            product_type=t, guaranteed=g, risk_grade=rk, risk_label=RISK_LABEL[rk], risky_asset=ry,
            product_fee_rate=fee_j, base_rate=br_j, term_months=tm or "", rate_type=rt,
            as_of_date=AS_OF.isoformat(), allowed_plan_types=plans,
            on_sale="N" if (t == "펀드" and r.random() < 0.08) else "Y", is_demo="Y"))
PRCOLS = ["product_id", "provider_id", "product_name", "product_type", "guaranteed", "risk_grade", "risk_label", "risky_asset",
          "product_fee_rate", "base_rate", "term_months", "rate_type", "as_of_date", "allowed_plan_types", "on_sale", "is_demo"]
write("pension_products.csv", products, PRCOLS)
by_prov = defaultdict(list)
for pr in products:
    by_prov[pr["provider_id"]].append(pr)

# 기준일 기준가 (보유 좌수 계산용). pension_sim 과 같은 난수라 매일 돌려도 과거 값은 같다
nav = {}
for pid, d, v in pension_sim.simulate(products, AS_OF):
    if d == AS_OF.isoformat():
        nav[pid] = v

# ---------------------------------------------------------------- employees
emps = rd(ROOT / "data" / "hr" / "employees.csv")
payroll = defaultdict(list)
for r in rd(ROOT / "data" / "hr" / "payroll.csv"):
    payroll[r["emp_id"]].append(float(r["gross_pay"]))


def annual_wage_now(e):
    """연간임금총액 추정: 급여 지급 달이 6개월 이상이면 평균 x 12, 아니면(휴직 등) 기본급 x 12 x 1.22 (정상 근무자의 총급여/기본급 비율)"""
    g = [x for x in payroll.get(e["emp_id"], []) if x > 0]
    return sum(g) / len(g) * 12 if len(g) >= 6 else float(e["base_salary"]) * 12 * 1.22


absences = defaultdict(list)      # 휴직 이력: (시작, 끝, 급여 지급률). 육아휴직은 무급(0), 질병휴직은 70%
for _r in rd(ROOT / "data" / "hr" / "absence_history.csv"):
    absences[_r["emp_id"]].append((dt.date.fromisoformat(_r["start_date"]), dt.date.fromisoformat(_r["end_date"]), float(_r["pay_rate"])))


def month_factor(emp_id, y, m):
    """y년 m월 임금 지급 비율(0~1). 육아휴직(무급)은 0, 질병휴직(70%)은 0.7, 일 비례"""
    first = dt.date(y, m, 1)
    last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
    f = 1.0
    for s_, e_, pr in absences.get(emp_id, []):
        ov = (min(e_, last) - max(s_, first)).days + 1
        if ov > 0:
            f -= ov / last.day * (1 - pr)
    return max(f, 0.0)


def paid_months(emp_id, y, m_from, m_to):
    """y년 m_from~m_to월 중 임금이 지급된 달 수 환산(일 비례). 휴직 기간은 지급률만큼만 센다"""
    return round(sum(month_factor(emp_id, y, m) for m in range(m_from, m_to + 1)), 2)


def hash_int(s):
    return int(hashlib.sha1(s.encode()).hexdigest(), 16)


# ---------------------------------------------------------------- plans
import json
personas = [p["emp_id"] for p in json.load(open(ROOT / "data" / "meta" / "demo_personas.json", encoding="utf-8"))]
PROV_IDS = [p["provider_id"] for p in providers]
PROV_W = [0.25, 0.20, 0.15, 0.40]     # 사업자 점유 (가정: 은행이 가장 큼)
# 팀 골든셋 페르소나는 사업자·제도를 고정해 질문셋 값이 사업자 추가에도 안 흔들리게 함 (P1 이승민 DC 태용생명, P2 최준서 DB 혜림증권, P3 송은지 DC 혜림증권)
GOLDEN_PIN = {"E1634": ("DC", "P01"), "E1033": ("DB", "P02"), "E1768": ("DC", "P02")}
plans, plan_by = [], {}
for e in emps:
    r = rng("plan", e["emp_id"])
    hire = dt.date.fromisoformat(e["hire_date"])
    retired = e["status"] == "퇴직"
    pre = hire < SYSTEM_START
    ptype = "미가입" if (pre and r.random() < 0.22) else None
    if ptype is None:
        p_dc = 0.12 if pre else (0.35 if hire.year <= 2015 else 0.60)
        ptype = "DC" if r.random() < p_dc else "DB"
    if e["emp_id"] in personas:                       # 시연 인물: 짝수 DB / 홀수 DC (입사 시기가 허락하는 범위)
        ptype = "DC" if personas.index(e["emp_id"]) % 2 == 0 else "DB"
    row = dict(emp_id=e["emp_id"], plan_type=ptype, provider_id="", enrolled_date="", contribution_rate="", balance="",
               status="해당없음", irp_provider_id="", transferred_date="", default_option="", is_demo="Y")
    if ptype != "미가입":
        row["provider_id"] = r.choices(PROV_IDS, PROV_W)[0]
        if e["emp_id"] in GOLDEN_PIN:
            row["provider_id"] = GOLDEN_PIN[e["emp_id"]][1]
        enr = hire if not pre else SYSTEM_START + dt.timedelta(days=hash_int(e["emp_id"]) % 730)
        if retired and enr > dt.date.fromisoformat(e["retire_date"]):
            enr = hire
        row["enrolled_date"] = enr.isoformat()
        row["status"] = "이전" if retired else "운용중"
        if ptype == "DC":
            row["contribution_rate"] = "0.0833"        # 연간임금총액의 1/12 (규정 제5조 상한)
            row["default_option"] = "Y" if r.random() < 0.15 else "N"
        if retired:
            row["irp_provider_id"] = r.choices(PROV_IDS, PROV_W)[0]
            row["transferred_date"] = (dt.date.fromisoformat(e["retire_date"]) + dt.timedelta(days=1 + hash_int(e["emp_id"] + "t") % 14)).isoformat()
    if e["emp_id"] in GOLDEN_PIN:
        assert row["plan_type"] == GOLDEN_PIN[e["emp_id"]][0], f"{e['emp_id']} 골든 페르소나 제도가 달라짐: {row['plan_type']}"
    plans.append(row)
    plan_by[e["emp_id"]] = row
emp_by = {e["emp_id"]: e for e in emps}

# ---------------------------------------------------------------- contributions (DC)
contribs = {}      # emp_id -> [(year, months, wage, employer, extra)]
for pl in plans:
    if pl["plan_type"] != "DC":
        continue
    e = emp_by[pl["emp_id"]]
    enr = dt.date.fromisoformat(pl["enrolled_date"])
    end = dt.date.fromisoformat(e["retire_date"]) if e["status"] == "퇴직" else AS_OF
    now_wage = annual_wage_now(e)
    r = rng("contrib", e["emp_id"])
    extra_user = r.random() < 0.15                      # 추가납입 하는 직원
    extra_amt = round(r.uniform(1.2, 6.0), 1) * 1_000_000
    extra_from = r.choice([2020, 2021, 2022, 2023, 2024])
    rows = []
    for y in range(enr.year, end.year + 1):
        m_from = enr.month if y == enr.year else 1
        if y < end.year:
            m_to = 12
        else:
            m_to = end.month if e["status"] == "퇴직" else min(end.month, 10)   # 재직자: 이번 달 25일 납입분은 아직 안 들어감
        months = m_to - m_from + 1
        if months <= 0:
            continue
        wage = now_wage / (1 + WAGE_GROWTH) ** (AS_OF.year - y)
        pm = paid_months(e["emp_id"], y, m_from, m_to)
        employer = int(round(wage / 12 * pm / 12))
        extra = int(round(extra_amt * months / 12, -4)) if (extra_user and y >= max(extra_from, enr.year) and e["status"] != "퇴직") else 0
        rows.append((y, months, int(round(wage)), employer, extra, pm))
    contribs[pl["emp_id"]] = rows

# ---------------------------------------------------------------- 중도인출 (DC, 시행령 제14조 사유)
REASONS = [("주택 구입", 0.40), ("주거 목적 전세금 부담", 0.30), ("6개월 이상 요양 의료비", 0.20), ("개인회생", 0.10)]
events = []
dc_active = [p for p in plans if p["plan_type"] == "DC" and p["status"] == "운용중" and emp_by[p["emp_id"]]["status"] == "재직"]
r = rng("withdraw")
cands = [p for p in dc_active if (AS_OF - dt.date.fromisoformat(p["enrolled_date"])).days > 365 * 6]
for p in r.sample(cands, k=max(1, round(len(dc_active) * 0.03))):
    reason = r.choices([x[0] for x in REASONS], [x[1] for x in REASONS])[0]
    ev_date = AS_OF - dt.timedelta(days=r.randint(60, 365 * 4))
    ev_date = max(ev_date, dt.date.fromisoformat(p["enrolled_date"]) + dt.timedelta(days=365 * 3))
    paid = sum(x[3] + x[4] for x in contribs[p["emp_id"]] if x[0] <= ev_date.year)
    amt = int(round(paid * r.uniform(0.30, 0.55), -4))
    events.append(dict(emp_id=p["emp_id"], event_date=ev_date.isoformat(), event_type="중도인출", reason=reason, amount=amt,
                       status="지급완료", note="시행령 제14조 사유. 증빙서류 확인 후 지급 (가상)"))
# 심사 중 1건 (시연용)
pend = r.choice([p for p in cands if p["emp_id"] not in {x["emp_id"] for x in events}])
events.append(dict(emp_id=pend["emp_id"], event_date="2026-11-10", event_type="중도인출", reason="주거 목적 전세금 부담",
                   amount=int(round(sum(x[3] + x[4] for x in contribs[pend["emp_id"]]) * 0.35, -4)), status="심사중",
                   note="신청 후 심사 중 (가상)"))

# ---------------------------------------------------------------- holdings + balance (DC 운용중)
def growth_factor(year, r_p):
    return (1 + r_p) ** max(0.0, (AS_OF - dt.date(year, 7, 1)).days / 365.25)


holdings = []
for pl in plans:
    if pl["plan_type"] != "DC":
        continue
    e = emp_by[pl["emp_id"]]
    if pl["status"] == "이전":                                         # 퇴직: IRP 로 이전돼 DC 잔액 0
        pl["balance"] = 0
        end = dt.date.fromisoformat(e["retire_date"])
        amt = sum((c + ex) * 1.04 ** max(0.0, (end - dt.date(y, 7, 1)).days / 365.25) for y, _, _, c, ex, _pm in contribs[pl["emp_id"]])
        events.append(dict(emp_id=pl["emp_id"], event_date=pl["transferred_date"], event_type="IRP이전", reason="퇴직급여 IRP 이전",
                           amount=ceil10(amt), status="지급완료",
                           note="DC 적립금 전액 IRP 이전. 시행세칙 제4조·제7조: 지급사유 발생일부터 14일 이내 (가상)"))
        continue
    r = rng("hold", pl["emp_id"])
    mine = by_prov[pl["provider_id"]]
    guar = [x for x in mine if x["guaranteed"] == "Y"]
    bonds = [x for x in mine if x["guaranteed"] == "N" and x["risky_asset"] == "N" and x["product_type"] == "펀드"]
    riskyl = [x for x in mine if x["risky_asset"] == "Y" and x["product_type"] != "TDF"]
    tdf = {x["product_name"].split()[-1]: x for x in mine if x["product_type"] == "TDF"}
    retire_year = int(e["birth_date"][:4]) + 60
    if pl["default_option"] == "Y":
        vint = min((2030, 2040, 2050), key=lambda v: abs(v - retire_year))
        picks = [(tdf[str(vint)], 100)]
    else:
        style = r.choices(["safe", "mixed", "growth"], [0.60, 0.28, 0.12])[0]
        if style == "safe":
            g = r.sample(guar, k=r.choice([1, 2]))
            picks = [(g[0], 100)] if len(g) == 1 else [(g[0], 60), (g[1], 40)]
        elif style == "mixed":
            picks = [(r.choice(guar), r.choice([60, 70])), (r.choice(bonds), 0)]
            picks[1] = (picks[1][0], 100 - picks[0][1])
        else:
            rk = r.sample(riskyl, k=2)
            picks = [(r.choice(guar), 30), (rk[0], 40), (rk[1], 30)]
    r_p = sum(float(x["base_rate"]) * w / 100 for x, w in picks)
    r_p += r.gauss(0, 0.008)
    total = sum(growth_factor(y, r_p) * (emp_c + ex) for y, _, _, emp_c, ex, _pm in contribs[pl["emp_id"]])
    for ev in events:                                                 # 지급완료 중도인출은 그 시점 이후 성장분과 함께 빠짐
        if ev["emp_id"] == pl["emp_id"] and ev["status"] == "지급완료":
            total -= ev["amount"] * (1 + r_p) ** max(0.0, (AS_OF - dt.date.fromisoformat(ev["event_date"])).days / 365.25)
    balance = int(round(max(total, 0), 0))
    pl["balance"] = balance
    paid_total = sum(x[3] + x[4] for x in contribs[pl["emp_id"]]) - sum(
        ev["amount"] for ev in events if ev["emp_id"] == pl["emp_id"] and ev["status"] == "지급완료")
    acc, wsum = 0, 0
    for i, (x, w) in enumerate(picks):
        ev_amt = balance - acc if i == len(picks) - 1 else int(round(balance * w / 100))
        acc += ev_amt
        pr = nav[x["product_id"]]
        holdings.append(dict(emp_id=pl["emp_id"], product_id=x["product_id"], weight=w, units=round(ev_amt / pr, 4),
                             principal=int(round(max(paid_total, 0) * w / 100)), eval_amount=ev_amt,
                             as_of_date=AS_OF.isoformat(), is_demo="Y"))

# DB 퇴직자: 퇴직금 = 근속 1년당 평균임금 30일분 (규정 제4조) = 월평균임금 x 근속개월/12, 10원 미만 절상 (시행세칙 제8조)
for pl in plans:
    if pl["plan_type"] == "DB" and pl["status"] == "이전":
        e = emp_by[pl["emp_id"]]
        g = payroll.get(e["emp_id"])
        avg_month = sum(g) / len(g) if g else float(e["base_salary"]) * 1.25
        months = months_between(dt.date.fromisoformat(e["hire_date"]), dt.date.fromisoformat(e["retire_date"]))
        events.append(dict(emp_id=pl["emp_id"], event_date=pl["transferred_date"], event_type="IRP이전", reason="퇴직급여 IRP 이전",
                           amount=ceil10(avg_month * months / 12), status="지급완료",
                           note=f"DB 퇴직급여 = 퇴직금(근속 {months}개월 x 월평균임금) IRP 이전 (가상)"))

# 중도인출 건 번호 (날짜순)
events.sort(key=lambda x: (x["event_date"], x["emp_id"]))
for i, ev in enumerate(events, 1):
    ev["event_id"] = f"EV{i:04d}"


# ---------------------------------------------------------------- 보유 원리금보장 상품: 가입(갱신)일 · 약정금리 · 만기일
def add_months(d, k):
    y, m = d.year + (d.month - 1 + k) // 12, (d.month - 1 + k) % 12 + 1
    dim = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(y, m, min(d.day, dim))


prod_by_id = {p["product_id"]: p for p in products}
for h in holdings:
    h.update(subscribed_date="", locked_rate="", maturity_date="")
    p = prod_by_id[h["product_id"]]
    if p["guaranteed"] != "Y":
        continue
    rr = rng("lock", h["emp_id"], h["product_id"])        # 따로 만든 난수라 다른 값(적립금 등)에 영향 없음
    enr = dt.date.fromisoformat(plan_by[h["emp_id"]]["enrolled_date"])
    if p["rate_type"] == "연동":                           # 금리연동형: 수시 입출금, 만기·약정금리 없음(금리는 달마다 바뀜)
        h["subscribed_date"] = max(enr, AS_OF - dt.timedelta(days=rr.randint(120, 1500))).isoformat()
        continue
    term = int(p["term_months"])
    sub = max(enr, AS_OF - dt.timedelta(days=rr.randint(0, term * 30 - 1)))   # 가장 최근 가입·갱신일
    mat = add_months(sub, term)
    while mat <= AS_OF:                                    # 만기가 지났으면 자동 갱신으로 이어 붙임
        sub, mat = mat, add_months(mat, term)
    rate = max(0.01, float(p["base_rate"]) + pension_sim.rate_shift((sub.year, sub.month)))   # 가입 달의 신규 약정금리로 고정
    h.update(subscribed_date=sub.isoformat(), locked_rate=round(rate, 4), maturity_date=mat.isoformat())

# ---------------------------------------------------------------- 월별 납입 거래내역 (DC, 최근 12개월: 2025-11 ~ 2026-10)
TX_FROM = (2025, 11)
transactions = []


def pay_date(y, m):
    d = dt.date(y, m, 25)                                  # 급여일 25일, 주말이면 앞 금요일
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def split_exact(total, weights):
    """total 을 weights 비율로 나누되 합이 정확히 total (남는 원은 마지막 0 아닌 몫에)"""
    ws = sum(weights)
    parts = [int(round(total * w / ws)) if ws else 0 for w in weights]
    last = max((i for i, w in enumerate(weights) if w > 0), default=None)
    if last is not None:
        parts[last] += total - sum(parts)
    return parts


for pl in plans:
    if pl["plan_type"] != "DC":
        continue
    e = emp_by[pl["emp_id"]]
    enr = dt.date.fromisoformat(pl["enrolled_date"])
    retired = e["status"] == "퇴직"
    end = dt.date.fromisoformat(e["retire_date"]) if retired else AS_OF
    for y, months, wage, employer, extra, pm in contribs[pl["emp_id"]]:
        m_from = enr.month if y == enr.year else 1
        m_to = 12 if y < end.year else (end.month if retired else min(end.month, 10))
        ms = list(range(m_from, m_to + 1))
        emp_parts = split_exact(employer, [month_factor(e["emp_id"], y, m) for m in ms])
        ext_parts = split_exact(extra, [1.0] * len(ms)) if extra else [0] * len(ms)
        for m, a, b in zip(ms, emp_parts, ext_parts):
            if (y, m) < TX_FROM:
                continue
            for kind, amt in (("회사부담금", a), ("직원추가납입", b)):
                if amt > 0:
                    transactions.append(dict(emp_id=e["emp_id"], tx_date=pay_date(y, m).isoformat(), tx_type=kind, amount=amt,
                                             pay_month=f"{y}-{m:02d}", is_demo="Y"))
transactions.sort(key=lambda t: (t["tx_date"], t["emp_id"], t["tx_type"]))
for i, t in enumerate(transactions, 1):
    t["tx_id"] = f"TX{i:06d}"

write("pension_plans.csv", plans, ["emp_id", "plan_type", "provider_id", "enrolled_date", "contribution_rate", "balance", "status",
                                   "irp_provider_id", "transferred_date", "default_option", "is_demo"])
write("pension_contributions.csv",
      [dict(emp_id=k, year=y, months=m, paid_months=pm, annual_wage=w, employer_contribution=c, employee_extra=x, is_demo="Y")
       for k, v in contribs.items() for y, m, w, c, x, pm in v],
      ["emp_id", "year", "months", "paid_months", "annual_wage", "employer_contribution", "employee_extra", "is_demo"])
write("pension_holdings.csv", holdings, ["emp_id", "product_id", "weight", "units", "principal", "eval_amount", "as_of_date", "subscribed_date", "locked_rate", "maturity_date", "is_demo"])
write("pension_transactions.csv", transactions, ["tx_id", "emp_id", "tx_date", "tx_type", "amount", "pay_month", "is_demo"])
write("pension_events.csv", events, ["event_id", "emp_id", "event_date", "event_type", "reason", "amount", "status", "note"])

import collections
print("providers", len(providers), "| products", len(products), "| plans", len(plans), "| transactions", len(transactions), "| contributions",
      sum(len(v) for v in contribs.values()), "| holdings", len(holdings), "| events", len(events))
print("plan_type", dict(collections.Counter(r["plan_type"] for r in plans)))
print("events", dict(collections.Counter((e["event_type"], e["status"]) for e in events)))
