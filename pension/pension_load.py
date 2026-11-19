"""퇴직연금 적재: data/pension/build/*.csv → hrdb 의 pension 스키마. 검증을 통과해야만 이전 것과 한 번에 교체.

실행: .venv/bin/python pension/pension_load.py
  1) pension_staging 스키마에 표 6개를 새로 만들고 적재
  2) 검증: 행 수 일치, 기본키 중복 없음, 외래키(사업자·펀드), 기준가 > 0
  3) 통과하면 한 트랜잭션에서 DROP SCHEMA pension + RENAME pension_staging → pension (실패하면 이전 pension 그대로)
build/pension_products.csv 가 비어 있으면(받은 데이터 없음) 아무것도 하지 않고 끝냄
환경변수 PENSION_DB_NAME 로 다른 DB 에 적재 가능(시험용), PENSION_DATA_DIR 로 입력 폴더 변경
"""
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from db_setup import connect, get_server  # noqa: E402

DATA = Path(os.environ.get("PENSION_DATA_DIR") or ROOT / "data" / "pension")
BUILD = DATA / "build"
DB = os.environ.get("PENSION_DB_NAME") or "hrdb"

TABLES = {  # 표: (설명, DDL 열, CSV 열 순서)
    "pension_providers": ("퇴직연금사업자 (가상: 태용생명·혜림증권·재현생명·코어뱅크. 계좌수수료 = 운용관리 + 자산관리)",
        "provider_id text PRIMARY KEY, provider_name text NOT NULL, provider_type text, account_fee_rate numeric, mgmt_fee_rate numeric, custody_fee_rate numeric, is_demo text",
        ["provider_id", "provider_name", "provider_type", "account_fee_rate", "mgmt_fee_rate", "custody_fee_rate", "is_demo"]),
    "pension_products": ("퇴직연금 운용상품. 지금은 시연용 가상(is_real=N), 실제 공시 API 경로(is_real=Y)는 보관 중. 수익률(ret_*)·변동성(vol_1y)·최대낙폭(mdd_1y)은 기준가 이력에서 계산",
        "fund_code text PRIMARY KEY, fund_name text, company_code text, company_name text, source_org text, product_type text, "
        "risk_grade integer, guaranteed text, risky_asset text, risk_label text, term_months text, rate_type text, allowed_plan_types text, first_price_date date, last_price_date date, "
        "last_nav numeric, ret_1m numeric, ret_3m numeric, ret_1y numeric, ret_3y numeric, vol_1y numeric, mdd_1y numeric, is_real text",
        ["fund_code", "fund_name", "company_code", "company_name", "source_org", "product_type", "risk_grade", "guaranteed",
         "risky_asset", "risk_label", "term_months", "rate_type", "allowed_plan_types", "first_price_date", "last_price_date", "last_nav", "ret_1m", "ret_3m", "ret_1y", "ret_3y", "vol_1y", "mdd_1y", "is_real"]),
    "pension_product_prices": ("펀드별 기준일 기준가·순자산 (실제). 수익률은 여기서 계산",
        "fund_code text NOT NULL, price_date date NOT NULL, nav numeric NOT NULL, net_asset numeric, PRIMARY KEY (fund_code, price_date)",
        ["fund_code", "price_date", "nav", "net_asset"]),
    "pension_guaranteed_rates": ("원리금보장 상품 월별 약정금리(연 %). 시연: set1_rate = 그 달 신규 적용금리, set2~4 비움 / 실제 API 경로: 한국산업은행 set1~4 (제도 대응 미확인)",
        "base_ym text NOT NULL, rate_start date, rate_end date, product_name text NOT NULL, term text, "
        "set1_rate numeric, set2_rate numeric, set3_rate numeric, set4_rate numeric",
        ["base_ym", "rate_start", "rate_end", "product_name", "term", "set1_rate", "set2_rate", "set3_rate", "set4_rate"]),
    "pension_provider_products": ("가상 사업자 x 실제 펀드 연결. 수수료는 아직 없음",
        "provider_id text NOT NULL, fund_code text NOT NULL, on_sale text, fee_rate numeric, fee_source text, is_demo text, "
        "PRIMARY KEY (provider_id, fund_code)",
        ["provider_id", "fund_code", "on_sale", "fee_rate", "fee_source", "is_demo"]),
    "pension_plans": ("직원별 퇴직연금 제도 (가상). DB 는 개인 적립금 없음",
        "emp_id text PRIMARY KEY, plan_type text NOT NULL, provider_id text, enrolled_date date, contribution_rate numeric, "
        "balance bigint, status text, irp_provider_id text, transferred_date date, default_option text, is_demo text",
        ["emp_id", "plan_type", "provider_id", "enrolled_date", "contribution_rate", "balance", "status", "irp_provider_id",
         "transferred_date", "default_option", "is_demo"]),
    "pension_contributions": ("DC 연도별 부담금 (가상). 회사부담 = 연간임금총액 x 1/12 x 임금지급환산개월(paid_months)/12. 무급휴직은 0, 급여 70% 휴직은 0.7로 환산. 직원 추가납입 별도. 재직자 올해분은 10월까지",
        "emp_id text NOT NULL, year integer NOT NULL, months integer, paid_months numeric, annual_wage bigint, employer_contribution bigint, "
        "employee_extra bigint, is_demo text, PRIMARY KEY (emp_id, year)",
        ["emp_id", "year", "months", "paid_months", "annual_wage", "employer_contribution", "employee_extra", "is_demo"]),
    "pension_holdings": ("DC 계좌 보유 상품 (가상). 적립금 balance = 평가액 합계(기준일 as_of_date). 현재 평가 = units x 최신 기준가. 원리금보장 상품은 가입(갱신)일·약정금리(가입한 달 고정)·만기일, 금리연동형은 만기·약정금리 없음",
        "emp_id text NOT NULL, product_id text NOT NULL, weight integer, units numeric, principal bigint, eval_amount bigint, "
        "as_of_date date, subscribed_date date, locked_rate numeric, maturity_date date, is_demo text, PRIMARY KEY (emp_id, product_id)",
        ["emp_id", "product_id", "weight", "units", "principal", "eval_amount", "as_of_date", "subscribed_date", "locked_rate", "maturity_date", "is_demo"]),
    "pension_transactions": ("DC 월별 납입 거래내역 (가상, 최근 12개월). 급여일 25일(주말이면 앞 금요일), 회사부담금·직원추가납입. 휴직 달은 지급률만큼만",
        "tx_id text PRIMARY KEY, emp_id text NOT NULL, tx_date date, tx_type text, amount bigint, pay_month text, is_demo text",
        ["tx_id", "emp_id", "tx_date", "tx_type", "amount", "pay_month", "is_demo"]),
    "pension_events": ("중도인출·IRP 이전 이력 (가상). 퇴직금 = 근속 x 평균임금, 10원 미만 절상",
        "event_id text PRIMARY KEY, emp_id text NOT NULL, event_date date, event_type text, reason text, amount bigint, status text, note text",
        ["event_id", "emp_id", "event_date", "event_type", "reason", "amount", "status", "note"]),
}
CHECKS = [  # (이름, 위반 행을 세는 SQL — 0 이어야 통과)
    ("기준가 <= 0", "SELECT count(*) FROM {s}.pension_product_prices WHERE nav <= 0"),
    ("기준가의 펀드가 상품에 없음", "SELECT count(*) FROM {s}.pension_product_prices x LEFT JOIN {s}.pension_products p USING (fund_code) WHERE p.fund_code IS NULL"),
    ("연결의 사업자가 없음", "SELECT count(*) FROM {s}.pension_provider_products x LEFT JOIN {s}.pension_providers p USING (provider_id) WHERE p.provider_id IS NULL"),
    ("연결의 펀드가 상품에 없음", "SELECT count(*) FROM {s}.pension_provider_products x LEFT JOIN {s}.pension_products p USING (fund_code) WHERE p.fund_code IS NULL"),
    ("제도의 사업자가 없음", "SELECT count(*) FROM {s}.pension_plans x LEFT JOIN {s}.pension_providers p USING (provider_id) WHERE x.provider_id IS NOT NULL AND p.provider_id IS NULL"),
    ("원리금보장이 아닌 상품이 DB 허용", "SELECT count(*) FROM {s}.pension_products WHERE allowed_plan_types LIKE '%DB%' AND guaranteed <> 'Y'"),
    ("원리금보장인데 위험자산", "SELECT count(*) FROM {s}.pension_products WHERE guaranteed = 'Y' AND risky_asset = 'Y'"),
    ("기준가 일일 변동 15% 초과", "SELECT count(*) FROM (SELECT nav / nullif(lag(nav) OVER (PARTITION BY fund_code ORDER BY price_date), 0) - 1 AS r FROM {s}.pension_product_prices) q WHERE abs(r) > 0.15"),
    ("원리금보장 상품 기준가 하락", "SELECT count(*) FROM (SELECT nav < lag(nav) OVER (PARTITION BY x.fund_code ORDER BY price_date) AS down FROM {s}.pension_product_prices x JOIN {s}.pension_products p USING (fund_code) WHERE p.guaranteed = 'Y') q WHERE down"),
    ("퇴직 이전된 DC 계좌에 적립금이 남음", "SELECT count(*) FROM {s}.pension_plans WHERE plan_type='DC' AND status='이전' AND coalesce(balance,0) <> 0"),
    ("DB 인데 개인 적립금이 있음", "SELECT count(*) FROM {s}.pension_plans WHERE plan_type='DB' AND balance IS NOT NULL"),
    ("DC 운용중 적립금 != 보유 평가액 합계", "SELECT count(*) FROM {s}.pension_plans p WHERE p.plan_type='DC' AND p.status='운용중' AND p.balance <> coalesce((SELECT sum(eval_amount) FROM {s}.pension_holdings h WHERE h.emp_id=p.emp_id), -1)"),
    ("보유 비중 합계 != 100", "SELECT count(*) FROM (SELECT emp_id FROM {s}.pension_holdings GROUP BY emp_id HAVING sum(weight) <> 100) q"),
    ("위험자산 비중 70% 초과(적격 TDF 제외)", "SELECT count(*) FROM (SELECT h.emp_id FROM {s}.pension_holdings h JOIN {s}.pension_products p ON p.fund_code=h.product_id GROUP BY h.emp_id HAVING sum(CASE WHEN p.risky_asset='Y' AND p.product_type<>'TDF' THEN h.weight ELSE 0 END) > 70) q"),
    ("보유 상품이 직원 사업자 것이 아님", "SELECT count(*) FROM {s}.pension_holdings h JOIN {s}.pension_plans p USING (emp_id) JOIN {s}.pension_products x ON x.fund_code=h.product_id WHERE x.company_code <> p.provider_id"),
    ("DC 보유 상품이 DC 허용 아님", "SELECT count(*) FROM {s}.pension_holdings h JOIN {s}.pension_products x ON x.fund_code=h.product_id WHERE x.allowed_plan_types NOT LIKE '%DC%'"),
    ("부담금이 임금/12 x 지급환산개월/12 와 다름", "SELECT count(*) FROM {s}.pension_contributions WHERE abs(employer_contribution - annual_wage / 12.0 * paid_months / 12) > 1 OR paid_months > months"),
    ("부담금 행이 DC 가입자가 아님", "SELECT count(*) FROM {s}.pension_contributions c LEFT JOIN {s}.pension_plans p USING (emp_id) WHERE p.plan_type IS DISTINCT FROM 'DC'"),
    ("이력의 직원이 제도 가입자가 아님", "SELECT count(*) FROM {s}.pension_events e LEFT JOIN {s}.pension_plans p USING (emp_id) WHERE p.plan_type IS NULL OR p.plan_type='미가입'"),
    ("IRP 이전 금액 10원 단위 아님", "SELECT count(*) FROM {s}.pension_events WHERE event_type='IRP이전' AND amount % 10 <> 0"),
    ("원리금보장 확정형인데 만기가 지났거나 약정금리 없음", "SELECT count(*) FROM {s}.pension_holdings h JOIN {s}.pension_products p ON p.fund_code=h.product_id WHERE p.guaranteed='Y' AND p.rate_type='확정' AND (h.maturity_date IS NULL OR h.maturity_date <= h.as_of_date OR h.locked_rate IS NULL OR h.locked_rate NOT BETWEEN 0.005 AND 0.08)"),
    ("실적배당 상품에 만기·약정금리가 있음", "SELECT count(*) FROM {s}.pension_holdings h JOIN {s}.pension_products p ON p.fund_code=h.product_id WHERE p.guaranteed='N' AND (h.maturity_date IS NOT NULL OR h.locked_rate IS NOT NULL)"),
    ("올해 납입 거래 합 != 올해 회사부담금", "SELECT count(*) FROM (SELECT c.emp_id FROM {s}.pension_contributions c LEFT JOIN {s}.pension_transactions t ON t.emp_id=c.emp_id AND t.tx_type='회사부담금' AND t.pay_month LIKE '2026-%' WHERE c.year=2026 GROUP BY c.emp_id, c.employer_contribution HAVING coalesce(sum(t.amount),0) <> c.employer_contribution) q"),
    ("납입일이 주말·미래", "SELECT count(*) FROM {s}.pension_transactions WHERE extract(isodow FROM tx_date) >= 6 OR tx_date > date '2026-11-30'"),
    ("DC 인데 부담률이 없음", "SELECT count(*) FROM {s}.pension_plans WHERE plan_type='DC' AND contribution_rate IS NULL"),
]


# 퇴직금 추정 기준일: 골든셋(eval/pension/build_pension_golden.py AS_OF)과 같은 날로 고정. current_date 를 쓰면 날마다 값이 바뀜
SEVERANCE_AS_OF = "2026-11-19"

VIEW_SEVERANCE = """
CREATE VIEW {s}.v_db_severance_estimate AS
WITH r AS (SELECT emp_id, pay_month, gross_pay, row_number() OVER (PARTITION BY emp_id ORDER BY pay_month DESC) rn FROM hr.payroll),
l3 AS (SELECT emp_id, sum(gross_pay) AS pay3, min(to_date(pay_month || '-01', 'YYYY-MM-DD')) AS m0,
              max(to_date(pay_month || '-01', 'YYYY-MM-DD')) AS m1, count(*) AS n FROM r WHERE rn <= 3 GROUP BY emp_id),
x AS (SELECT p.emp_id, e.hire_date, date '{d}' AS as_of,
             (extract(year FROM age(date '{d}', e.hire_date)) * 12 + extract(month FROM age(date '{d}', e.hire_date))
              + CASE WHEN extract(day FROM age(date '{d}', e.hire_date)) > 0 THEN 1 ELSE 0 END)::int AS service_months,
             l3.pay3, ((l3.m1 + interval '1 month')::date - l3.m0) AS days3
      FROM {s}.pension_plans p JOIN hr.employees e ON e.emp_id = p.emp_id JOIN l3 ON l3.emp_id = p.emp_id
      WHERE p.plan_type = 'DB' AND p.status = '운용중' AND e.status = '재직' AND l3.n = 3)
SELECT emp_id, hire_date, as_of, service_months, pay3 AS last3_gross_pay, days3 AS last3_days,
       round(pay3::numeric / days3) AS avg_daily_wage,
       CASE WHEN service_months < 12 THEN 0 ELSE (ceil(pay3::numeric / days3 * 30 * service_months / 12 / 10) * 10)::bigint END AS est_severance
FROM x;
COMMENT ON VIEW {s}.v_db_severance_estimate IS 'DB 가입 재직자의 {d} 퇴직 가정 퇴직금 추정 = 최근 3개 급여월 임금총액 / 일수 x 30 x 근속개월/12, 10원 미만 절상(시행세칙 제8조). 근속 1년 미만 0. 평균임금은 근로기준법 3개월 방식 가정(규정은 보수규정 위임)'
"""


def nrows(p):
    with open(p, encoding="utf-8-sig") as f:
        return sum(1 for _ in csv.reader(f)) - 1


def main():
    need = [BUILD / f"{t}.csv" for t in TABLES]
    if any(not p.exists() for p in need) or nrows(BUILD / "pension_products.csv") <= 0:
        print("pension_load: build 결과 없음 → 건너뜀 (pension 스키마 그대로)")
        return
    S = "pension_staging"
    srv = get_server()
    with connect(srv, DB) as con:
        con.execute(f"DROP SCHEMA IF EXISTS {S} CASCADE")
        con.execute(f"CREATE SCHEMA {S}")
        for t, (desc, ddl, cols) in TABLES.items():
            con.execute(f"CREATE TABLE {S}.{t} ({ddl})")
            con.execute(f"COMMENT ON TABLE {S}.{t} IS '{desc.replace(chr(39), chr(39) * 2)}'")  # COMMENT 는 값 자리표시자를 못 씀
            with con.cursor() as cur, open(BUILD / f"{t}.csv", encoding="utf-8-sig") as f:
                next(f)  # 머리글
                with cur.copy(f"COPY {S}.{t} ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv, NULL '')") as cp:
                    while chunk := f.read(1 << 20):
                        cp.write(chunk)
        if con.execute("SELECT to_regclass('hr.payroll')").fetchone()[0]:
            con.execute(VIEW_SEVERANCE.format(s=S, d=SEVERANCE_AS_OF))
        errs = []
        for t in TABLES:
            got = con.execute(f"SELECT count(*) FROM {S}.{t}").fetchone()[0]
            want = nrows(BUILD / f"{t}.csv")
            if got != want:
                errs.append(f"{t}: 적재 {got} != 파일 {want}")
        for name, sql in CHECKS:
            n = con.execute(sql.format(s=S)).fetchone()[0]
            if n:
                errs.append(f"{name}: {n}건")
        if errs:
            con.execute(f"DROP SCHEMA {S} CASCADE")
            print("pension_load: 검증 실패 → 이전 pension 유지\n  - " + "\n  - ".join(errs))
            sys.exit(1)
        with con.transaction():
            con.execute("DROP SCHEMA IF EXISTS pension CASCADE")
            con.execute(f"ALTER SCHEMA {S} RENAME TO pension")
            con.execute("COMMENT ON SCHEMA pension IS '퇴직연금: 실제 펀드·기준가·원리금보장 금리 + 가상 사업자·직원 제도 (pension_load.py)'")
        cnt = {t: con.execute(f"SELECT count(*) FROM pension.{t}").fetchone()[0] for t in TABLES}
        if con.execute("SELECT to_regclass('pension.v_db_severance_estimate')").fetchone()[0]:
            cnt["v_db_severance_estimate(뷰)"] = con.execute("SELECT count(*) FROM pension.v_db_severance_estimate").fetchone()[0]
    print("pension_load: " + ", ".join(f"{t.replace('pension_', '')} {n}" for t, n in cnt.items()))


if __name__ == "__main__":
    main()
