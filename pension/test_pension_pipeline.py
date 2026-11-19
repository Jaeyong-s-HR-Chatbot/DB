"""퇴직연금 파이프라인 시험. 임시 폴더·임시 DB(pension_test)만 쓰고 끝나면 지움. 실제 hrdb·data/pension 은 건드리지 않음.
실행: .venv/bin/python pension/test_pension_pipeline.py
[가상 경로: 현재 사용]  기준가 생성 → 가공 → 적재 → 검증 규칙이 실제로 막는지(주입 시험) → 새 영업일이 이어 붙는지
[API 경로: 보관 중]    응답 해석 → 가공 → 적재 (펀드명·기준가는 모두 가짜, 응답 모양은 명세 기준 가정)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from db_setup import connect, get_server  # noqa: E402

PY = sys.executable
DB = "pension_test"


def mk():
    tmp = Path(tempfile.mkdtemp(prefix="pension_test_"))
    for n in ("pension_providers.csv", "pension_plans.csv", "pension_products.csv", "pension_contributions.csv", "pension_holdings.csv", "pension_events.csv", "pension_transactions.csv"):
        shutil.copyfile(ROOT / "data/pension" / n, tmp / n)
    return tmp, {**os.environ, "PENSION_DATA_DIR": str(tmp), "PENSION_DB_NAME": DB}


def run(env, script, *args, expect=0):
    r = subprocess.run([PY, str(ROOT / "pension" / script), *args], env=env, capture_output=True, text=True, cwd=ROOT)
    out = (r.stdout + r.stderr).strip()
    assert r.returncode == expect, f"{script} 종료코드 {r.returncode}: {out[-500:]}"
    return out


def q(srv, sql):
    with connect(srv, DB) as c:
        return c.execute(sql).fetchone()[0]


def demo_path(srv):
    print("[가상 경로]")
    tmp, env = mk()
    try:
        print(" 1)", run(env, "pension_sim.py"))
        print(" 2)", run(env, "pension_build.py"))
        print(" 3)", run(env, "pension_load.py"))
        NP = q(srv, "SELECT count(*) FROM pension.pension_products")
        assert NP == len(open(tmp / "pension_products.csv", encoding="utf-8-sig").read().strip().splitlines()) - 1
        assert q(srv, "SELECT count(*) FROM pension.pension_provider_products") == NP
        assert q(srv, "SELECT count(*) FROM pension.pension_guaranteed_rates") > 0
        assert q(srv, "SELECT count(*) FROM pension.pension_products WHERE ret_1y IS NULL AND last_price_date - first_price_date >= 365") == 0
        assert q(srv, "SELECT count(*) FROM pension.pension_products WHERE is_real <> 'N'") == 0
        # 같은 날짜의 값은 다시 돌려도 같다
        a = (tmp / "demo_prices.csv").read_text(encoding="utf-8-sig")
        run(env, "pension_sim.py")
        assert (tmp / "demo_prices.csv").read_text(encoding="utf-8-sig") == a, "재실행 결과가 달라짐"
        print(" 4) 같은 날 재실행 → 결과 동일 (통과)")
        # 직원 한 명이 고를 수 있는 상품: DC 직원은 자기 사업자 상품만
        n = q(srv, """SELECT count(*) FROM pension.pension_plans pl
                      JOIN pension.pension_provider_products pp ON pp.provider_id = pl.provider_id
                      JOIN pension.pension_products p ON p.fund_code = pp.fund_code
                      WHERE pl.emp_id = (SELECT emp_id FROM pension.pension_plans WHERE plan_type='DC' AND status='운용중' LIMIT 1)
                        AND pp.on_sale='Y' AND p.allowed_plan_types LIKE '%DC%'""")
        assert 0 < n <= 20, n
        print(f" 5) DC 직원 1명이 고를 수 있는 상품 {n}개 (통과)")
        # 주입 시험: 검증 규칙이 실제로 막는지
        pr =tmp / "build/pension_product_prices.csv"
        base = pr.read_text(encoding="utf-8-sig").splitlines()
        def inject(lines, idx, col, val):
            parts = lines[idx].split(","); parts[col] = val; out = list(lines); out[idx] = ",".join(parts); return out
        cases = [("기준가 0", inject(base, 5, 2, "0")),
                 ("하루 +50% 급등", inject(base, 300, 2, str(float(base[300].split(",")[2]) * 1.5)))]
        for label, lines in cases:
            pr.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
            out = run(env, "pension_load.py", expect=1)
            assert "검증 실패" in out, out
            print(f" 6) 주입({label}) → 적재 막힘:", [l.strip() for l in out.splitlines()[1:2]])
        assert q(srv, "SELECT count(*) FROM pension.pension_products") == NP, "실패 시 이전 데이터가 유지돼야 함"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def api_path(srv):
    print("[API 경로(보관)]")
    tmp, env = mk()
    try:
        print(" 1)", subprocess.run([PY, str(ROOT / "pension/pension_fetch_api.py"), "--selftest"], capture_output=True, text=True).stdout.strip())
        (tmp / "api").mkdir()
        with open(tmp / "api/fund_rows.jsonl", "w", encoding="utf-8") as f:
            for code, name in (("F001", "시험채권펀드"), ("F002", "시험주식펀드"), ("F003", "시험TDF 2040")):
                for i, d in enumerate(("20261110", "20261111", "20261112")):
                    f.write(json.dumps(dict(cmpyCd="C1", cmpyNm="시험운용", fndCd=code, fndNm=name, basDt=d, basprc=str(1000 + i * 3),
                                            nPptAmt="1,000000", ofrInstNm="시험협회"), ensure_ascii=False) + "\n")
        with open(tmp / "api/kdb_rows.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps(dict(bseYm="202611", irtAlySttDt="20261101", irtAlyEndDt="20261130", prdNm="시험예금", prdJinTrmCone="1년",
                                    set1Irt="3.1", set2Irt="3.2", set3Irt="3.3", set4Irt="3.4"), ensure_ascii=False) + "\n")
        print(" 2)", run(env, "pension_build.py", "--source", "api"))
        print(" 3)", run(env, "pension_load.py"))
        assert q(srv, "SELECT count(*) FROM pension.pension_products") == 3
        assert q(srv, "SELECT count(*) FROM pension.pension_products WHERE is_real='Y'") == 3
        (tmp / "api/fund_rows.jsonl").write_text("")
        print(" 4)", run(env, "pension_build.py", "--source", "api"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    srv = get_server()
    with connect(srv, "postgres") as c:
        c.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {DB}")
    try:
        demo_path(srv)
        api_path(srv)
        print("전체 통과")
    finally:
        with connect(srv, "postgres") as c:
            c.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")


if __name__ == "__main__":
    main()
