"""pension CSV 검사 (시연용). 실패하면 종료코드 1. 실행: python pension/validate_pension.py"""
import csv, sys, datetime as dt
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
D = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "pension"
rd = lambda p: list(csv.DictReader(open(p, encoding="utf-8-sig")))
prov, prod, plan = rd(D/"pension_providers.csv"), rd(D/"pension_products.csv"), rd(D/"pension_plans.csv")
contrib, hold, ev = rd(D/"pension_contributions.csv"), rd(D/"pension_holdings.csv"), rd(D/"pension_events.csv")
tx = rd(D/"pension_transactions.csv")
emps = {r["emp_id"]: r for r in rd(ROOT/"data"/"hr"/"employees.csv")}
pids = {r["provider_id"] for r in prov}
errs = []
RISK = {1: "매우 높은 위험", 2: "높은 위험", 3: "다소 높은 위험", 4: "보통 위험", 5: "낮은 위험", 6: "매우 낮은 위험"}
ptype = {r["provider_id"]: r["provider_type"] for r in prov}
GUAR_OK = {"은행": {"예금"}, "증권": {"예금", "발행어음", "RP", "ELB"}, "보험": {"보험"}}
pbyid = {r["product_id"]: r for r in prod}
def chk(ok, msg):
    if not ok: errs.append(msg)
chk(len({r["provider_id"] for r in prov}) == len(prov), "provider_id 중복")
chk(len({r["product_id"] for r in prod}) == len(prod), "product_id 중복")
chk(len({r["emp_id"] for r in plan}) == len(plan), "plans emp_id 중복")
chk(set(emps) == {r["emp_id"] for r in plan}, "직원 수와 pension_plans 행이 안 맞음")
for r in prov:
    chk(0 <= float(r["account_fee_rate"]) <= 0.05, f"{r['provider_id']} 계좌수수료 범위")
    chk(abs(float(r["account_fee_rate"]) - float(r["mgmt_fee_rate"]) - float(r["custody_fee_rate"])) < 1e-9, f"{r['provider_id']} 계좌수수료 != 운용관리+자산관리")
for r in prod:
    i = r["product_id"]
    chk(r["provider_id"] in pids, f"{i} 사업자 없음")
    chk(0 <= float(r["product_fee_rate"]) <= 0.05, f"{i} 상품보수 범위")
    chk(1 <= int(r["risk_grade"]) <= 6, f"{i} 위험등급 범위")
    chk((r["guaranteed"] == "Y") == (int(r["risk_grade"]) == 6), f"{i} 원리금보장 <-> 6등급(매우 낮은 위험) 불일치")
    chk(r["risk_label"] == RISK[int(r["risk_grade"])], f"{i} 위험등급 라벨")
    chk(not (r["risky_asset"] == "Y" and int(r["risk_grade"]) >= 5), f"{i} 위험자산인데 낮은 위험 등급")
    chk(r["as_of_date"] != "" and r["as_of_date"] <= str(dt.date.today()), f"{i} 기준일 누락/미래")
    chk(r["guaranteed"] in "YN" and r["risky_asset"] in "YN" and r["on_sale"] in "YN", f"{i} Y/N 값")
    chk(set(r["allowed_plan_types"].split(",")) <= {"DB", "DC", "IRP"}, f"{i} allowed_plan_types")
    chk(not ("DB" in r["allowed_plan_types"] and r["guaranteed"] != "Y"), f"{i} 실적배당 상품이 DB 허용")
    chk(not (r["guaranteed"] == "Y" and r["risky_asset"] == "Y"), f"{i} 원리금보장인데 위험자산")
    chk(r["is_demo"] == "Y", f"{i} is_demo")
    chk(r["guaranteed"] != "Y" or r["product_type"] in GUAR_OK[ptype[r["provider_id"]]], f"{i} 업권에 맞지 않는 원리금보장 상품")
for r in plan:
    e = r["emp_id"]
    chk(r["plan_type"] in ("DB", "DC", "미가입"), f"{e} plan_type")
    if r["plan_type"] == "미가입":
        chk(r["provider_id"] == "" and r["balance"] == "", f"{e} 미가입인데 사업자/적립금 있음")
    else:
        chk(r["provider_id"] in pids, f"{e} 사업자 없음")
        chk(r["enrolled_date"] != "", f"{e} 가입일 없음")
    chk(not (r["plan_type"] == "DB" and r["balance"] != ""), f"{e} DB인데 개인 적립금 있음")
    chk(not (r["plan_type"] == "DC" and r["contribution_rate"] == ""), f"{e} DC인데 부담률 없음")
    chk(not (r["status"] == "이전" and r["irp_provider_id"] not in pids), f"{e} 퇴직자 IRP 사업자 없음")
    chk(not (emps[e]["status"] == "퇴직" and r["plan_type"] != "미가입" and r["status"] != "이전"), f"{e} 퇴직자 상태")
absence = {}
for _r in rd(ROOT / "data" / "hr" / "absence_history.csv"):
    absence.setdefault(_r["emp_id"], []).append((dt.date.fromisoformat(_r["start_date"]), dt.date.fromisoformat(_r["end_date"]), float(_r["pay_rate"])))
SYS = "2012-01-01"
pl = {r["emp_id"]: r for r in plan}
for e, r in emps.items():
    chk(not (r["hire_date"] >= SYS and pl[e]["plan_type"] == "미가입"), f"{e} 2012 이후 입사인데 미가입")
    chk(not (pl[e]["enrolled_date"] and pl[e]["enrolled_date"] < r["hire_date"]), f"{e} 입사 전에 가입")
    if r["status"] == "퇴직" and pl[e]["plan_type"] != "미가입":
        d = (dt.date.fromisoformat(pl[e]["transferred_date"]) - dt.date.fromisoformat(r["retire_date"])).days
        chk(1 <= d <= 14, f"{e} IRP 이전일이 퇴직 후 14일 이내가 아님")
# 보유·적립금
hsum, wsum = {}, {}
for r in hold:
    e = r["emp_id"]; p = pbyid[r["product_id"]]
    chk(p["provider_id"] == pl[e]["provider_id"], f"{e} 보유 상품이 다른 사업자 것")
    chk("DC" in p["allowed_plan_types"].split(","), f"{e} 보유 상품 DC 불허")
    hsum[e] = hsum.get(e, 0) + int(r["eval_amount"]); wsum[e] = wsum.get(e, 0) + int(r["weight"])
risky = {}
for r in hold:
    p = pbyid[r["product_id"]]
    if p["risky_asset"] == "Y" and p["product_type"] != "TDF":
        risky[r["emp_id"]] = risky.get(r["emp_id"], 0) + int(r["weight"])
for e, r in pl.items():
    if r["plan_type"] == "DC" and r["status"] == "운용중":
        chk(hsum.get(e) == int(r["balance"]), f"{e} 적립금 != 보유 평가액 합계")
        chk(wsum.get(e) == 100, f"{e} 보유 비중 합계 {wsum.get(e)}")
        chk(risky.get(e, 0) <= 70, f"{e} 위험자산 비중 70% 초과")
    else:
        chk(e not in hsum, f"{e} DC 운용중이 아닌데 보유 상품 있음")
# 보유 원리금보장 상품의 만기·약정금리
AS_OF_D = "2026-11-18"
for r in hold:
    p = pbyid[r["product_id"]]
    if p["guaranteed"] == "Y" and p["rate_type"] == "확정":
        chk(r["maturity_date"] > AS_OF_D and r["subscribed_date"] <= AS_OF_D, f"{r['emp_id']} {r['product_id']} 가입·만기일")
        chk(r["locked_rate"] != "" and 0.005 <= float(r["locked_rate"]) <= 0.08, f"{r['emp_id']} {r['product_id']} 약정금리")
        months = int(p["term_months"])
        sy, sm = int(r["subscribed_date"][:4]), int(r["subscribed_date"][5:7])
        my, mm = int(r["maturity_date"][:4]), int(r["maturity_date"][5:7])
        chk((my - sy) * 12 + (mm - sm) == months, f"{r['emp_id']} {r['product_id']} 만기-가입 기간이 상품 기간과 다름")
    else:
        chk(r["maturity_date"] == "" and r["locked_rate"] == "", f"{r['emp_id']} {r['product_id']} 만기·약정금리가 있으면 안 되는 상품")
# 월별 납입 거래: 올해 합계 = 올해 회사 부담금·추가납입, 급여일(평일), DC 가입자만
tsum = {}
for r in tx:
    e = r["emp_id"]
    chk(pl[e]["plan_type"] == "DC", f"{r['tx_id']} DC 아닌데 납입")
    chk(dt.date.fromisoformat(r["tx_date"]).weekday() < 5, f"{r['tx_id']} 주말 납입")
    chk(int(r["amount"]) > 0, f"{r['tx_id']} 금액")
    if r["pay_month"].startswith("2026"):
        tsum[(e, r["tx_type"])] = tsum.get((e, r["tx_type"]), 0) + int(r["amount"])
for r in contrib:
    if r["year"] == "2026":
        e = r["emp_id"]
        chk(tsum.get((e, "회사부담금"), 0) == int(r["employer_contribution"]), f"{e} 올해 납입 거래 합 != 회사 부담금")
        chk(tsum.get((e, "직원추가납입"), 0) == int(r["employee_extra"]), f"{e} 올해 납입 거래 합 != 직원 추가납입")
chk(len({r["tx_id"] for r in tx}) == len(tx), "tx_id 중복")
# 부담금
for r in contrib:
    e = r["emp_id"]
    chk(pl[e]["plan_type"] == "DC", f"{e} DC 아닌데 부담금")
    chk(abs(int(r["employer_contribution"]) - int(r["annual_wage"]) / 12 * float(r["paid_months"]) / 12) <= 1, f"{e} {r['year']} 회사 부담금 계산")
    chk(float(r["paid_months"]) <= int(r["months"]), f"{e} {r['year']} 지급환산개월이 개월 수보다 큼")
    # 지급환산개월을 휴직 이력·가입일·퇴직일로 독립 재계산해 비교
    y = int(r["year"]); enr = dt.date.fromisoformat(pl[e]["enrolled_date"])
    retired = emps[e]["status"] == "퇴직"; end = dt.date.fromisoformat(emps[e]["retire_date"]) if retired else dt.date(2026, 11, 18)
    m1 = enr.month if y == enr.year else 1
    m2 = 12 if y < end.year else (end.month if retired else min(end.month, 10))
    exp = 0.0
    for m in range(m1, m2 + 1):
        first = dt.date(y, m, 1); last = dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)
        f = 1.0
        for st, en, pr in absence.get(e, []):
            ov = (min(en, last) - max(st, first)).days + 1
            if ov > 0:
                f -= ov / last.day * (1 - pr)
        exp += max(f, 0.0)
    chk(abs(exp - float(r["paid_months"])) < 0.011, f"{e} {y} 지급환산개월 {r['paid_months']} != 재계산 {exp:.2f}")
    chk(int(r["months"]) == m2 - m1 + 1, f"{e} {y} 개월 수")
chk(len({(r["emp_id"], r["year"]) for r in contrib}) == len(contrib), "부담금 (사번, 연도) 중복")
# 이력
REASON = {"주택 구입", "주거 목적 전세금 부담", "6개월 이상 요양 의료비", "개인회생", "퇴직급여 IRP 이전"}
chk(len({r["event_id"] for r in ev}) == len(ev), "event_id 중복")
for r in ev:
    e = r["emp_id"]
    chk(r["reason"] in REASON, f"{r['event_id']} 사유")
    chk(r["event_type"] in ("중도인출", "IRP이전"), f"{r['event_id']} 종류")
    chk(pl[e]["plan_type"] != "미가입", f"{r['event_id']} 미가입자 이력")
    chk(not (r["event_type"] == "중도인출" and pl[e]["plan_type"] != "DC"), f"{r['event_id']} DC 아닌데 중도인출")
    chk(not (r["event_type"] == "IRP이전" and r["amount"] and int(r["amount"]) % 10), f"{r['event_id']} 10원 미만 절상 아님")
    chk(not (r["event_type"] == "IRP이전" and emps[e]["status"] != "퇴직"), f"{r['event_id']} 재직자 IRP 이전")
    chk(r["event_date"] <= str(dt.date.today()), f"{r['event_id']} 미래 일자")
irp = {r["emp_id"] for r in ev if r["event_type"] == "IRP이전"}
for e, r in emps.items():
    if r["status"] == "퇴직" and pl[e]["plan_type"] != "미가입":
        chk(e in irp, f"{e} 퇴직자인데 IRP 이전 이력 없음")
print("검사 항목 오류:", len(errs))
for m in errs[:20]: print(" -", m)
sys.exit(1 if errs else 0)
