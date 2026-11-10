"""6단계 커넥터: 고객사 DB(erp, 회사식) → 읽기 전용 뷰 → 연결표로 변환 → 우리 표준 형식(hr) 적재.

실행: .venv/bin/python connector.py

흐름
  1. 읽기 전용 통로 준비: 스키마 erp_ro에 테이블마다 뷰를 만들고, 커넥터 전용 역할 hr_connector에게
     이 뷰 SELECT 권한만 줌 (erp 원본 테이블은 못 읽고, 아무것도 못 바꿈) — 실제 고객사가 열어 주는 방식 흉내
  2. 추출: hr_connector 역할로 뷰만 읽음
  3. 변환: mapping/nuri.yaml(회사 이름·코드·날짜 형식) + mapping/standard.yaml(우리 표준 타입)
           회사 열 이름 → 표준 이름, 코드 '1' → '정규직', '20230101' → 2023-01-01, 'Y' → true
           연결표에 없는 코드가 나오면 그 자리에서 멈춤 (조용히 틀린 값을 넣지 않음)
  4. 적재: 새 스키마 hr_staging에 먼저 넣음
  5. 검사: hr_staging을 임시 폴더로 꺼내 3단계 validate.py를 그대로 돌림
           통과 → hr_staging을 hr로 교체 (한 번에)  /  실패 → hr은 이전 상태 그대로 두고 중단
  6. 기록: app.sync_log에 실행마다 테이블별 원천 행 수·적재 행 수·결과·메시지 저장

다른 회사가 오면 nuri.yaml 대신 그 회사 연결표만 만들면 됨 (이 파일과 standard.yaml은 그대로)
"""
import csv
import datetime as dt
import json
import subprocess
import sys
import tempfile
import time
import uuid
from decimal import Decimal
from pathlib import Path

import yaml

from db_setup import connect, get_server

HERE = Path(__file__).parent
MAP = yaml.safe_load(open(HERE / "mapping/nuri.yaml", encoding="utf-8"))
STD = yaml.safe_load(open(HERE / "mapping/standard.yaml", encoding="utf-8"))
ROLE = "hr_connector"
EXTRA_TABLES = {"attendance"}  # 기준서 14종 밖 부가 파일 → 검사용 폴더에서 extra/ 에 둠


class SyncError(Exception):
    pass


def q(name):
    return '"' + name.replace('"', '""') + '"'


# ------------------------------------------------------------------ 1. 읽기 전용 통로
def setup_readonly(con):
    con.execute("CREATE SCHEMA IF NOT EXISTS erp_ro")
    con.execute("COMMENT ON SCHEMA erp_ro IS '고객사가 커넥터에게 열어 준 읽기 전용 뷰 (6단계)'")
    if not con.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (ROLE,)).fetchone():
        con.execute(f"CREATE ROLE {ROLE} NOLOGIN")
    for t in STD["order"]:
        ct = MAP["tables"][t]["name"]
        cols = ", ".join(q(c) for c in MAP["tables"][t]["columns"].values())
        con.execute(f"CREATE OR REPLACE VIEW erp_ro.{q(ct)} AS SELECT {cols} FROM erp.{q(ct)}")
    con.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA erp FROM {ROLE}")
    con.execute(f"REVOKE ALL ON SCHEMA erp FROM {ROLE}")
    con.execute(f"GRANT USAGE ON SCHEMA erp_ro TO {ROLE}")
    con.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA erp_ro TO {ROLE}")


def setup_app(con):
    con.execute("CREATE SCHEMA IF NOT EXISTS app")
    con.execute("""CREATE TABLE IF NOT EXISTS app.sync_log (
        log_id bigserial PRIMARY KEY, run_id text NOT NULL, company_id text NOT NULL, table_name text,
        source_rows integer, loaded_rows integer, status text NOT NULL, message text,
        started_at timestamptz NOT NULL, finished_at timestamptz NOT NULL DEFAULT now())""")


# ------------------------------------------------------------------ 3. 변환
def converter(t, c):
    """회사 DB 값 하나를 표준 값으로 바꾸는 함수를 열마다 하나 만들어 둠."""
    typ = STD["tables"][t]["columns"][c]
    key = MAP["code_columns"].get(f"{t}.{c}")
    back = {code: std for std, code in MAP["codes"][key].items()} if key else None
    fmt = MAP["date_format"]

    def conv(v):
        if v is None:
            return None
        if back is not None:
            if v not in back:
                raise SyncError(f"{t}.{c}: 연결표에 없는 코드 '{v}' → mapping/nuri.yaml codes.{key}에 추가 필요")
            v = back[v]
        if typ == "date" and isinstance(v, str):
            return dt.datetime.strptime(v, fmt).date()
        if typ == "boolean" and isinstance(v, str):
            return {"true": True, "false": False}[v]
        if typ == "integer" and isinstance(v, str):
            return int(v)
        return v
    return conv


def extract(con, t):
    m = MAP["tables"][t]
    std_cols = list(STD["tables"][t]["columns"])
    missing = [c for c in std_cols if c not in m["columns"]]
    if missing:
        raise SyncError(f"{t}: 연결표에 표준 열 {missing}의 회사 쪽 이름이 없음")
    sel = ", ".join(q(m["columns"][c]) for c in std_cols)
    con.execute(f"SET ROLE {ROLE}")
    try:
        rows = con.execute(f"SELECT {sel} FROM erp_ro.{q(m['name'])}").fetchall()
    finally:
        con.execute("RESET ROLE")
    convs = [converter(t, c) for c in std_cols]
    return std_cols, [[f(v) for f, v in zip(convs, r)] for r in rows]


# ------------------------------------------------------------------ 4. 적재 (hr_staging)
def create_table(con, t, schema):
    spec = STD["tables"][t]
    cols = [f"{q(c)} {ty}" for c, ty in spec["columns"].items()]
    cols.append("PRIMARY KEY (" + ", ".join(q(c) for c in spec["pk"]) + ")")
    con.execute(f"CREATE TABLE {schema}.{q(t)} (" + ", ".join(cols) + ")")


def add_fks(con, schema):
    for t in STD["order"]:
        for fk in STD["tables"][t]["fk"]:
            col, ref = [x.strip() for x in fk.split("->")]
            rt, rc = ref.split(".")
            con.execute(f"ALTER TABLE {schema}.{q(t)} ADD FOREIGN KEY ({q(col)}) REFERENCES {schema}.{q(rt)}({q(rc)})")
        if "emp_id" in STD["tables"][t]["columns"] and t != "employees":
            con.execute(f"CREATE INDEX ON {schema}.{q(t)} (emp_id)")


# ------------------------------------------------------------------ 5. 검사
def csv_text(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, dt.time):
        return v.strftime("%H:%M")
    if isinstance(v, (dt.date, Decimal, int, float)):
        return str(v)
    return v


def validate_schema(con, schema):
    tmp = Path(tempfile.mkdtemp(prefix="hr_sync_"))
    (tmp / "hr").mkdir()
    (tmp / "extra").mkdir()
    for t in STD["order"]:
        cols = list(STD["tables"][t]["columns"])
        rows = con.execute(f"SELECT {', '.join(q(c) for c in cols)} FROM {schema}.{q(t)}").fetchall()
        with open(tmp / ("extra" if t in EXTRA_TABLES else "hr") / f"{t}.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows([[csv_text(v) for v in r] for r in rows])
    res = subprocess.run([sys.executable, str(HERE / "validate.py"), str(tmp)], capture_output=True, text=True)
    return res.returncode == 0, res.stdout.strip().splitlines()


# ------------------------------------------------------------------ 실행
def main():
    run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    started = dt.datetime.now().astimezone()
    srv = get_server()
    logs = []  # (table, source_rows, loaded_rows, status, message)
    with connect(srv) as con:
        setup_app(con)
        try:
            setup_readonly(con)
            con.execute("DROP SCHEMA IF EXISTS hr_staging CASCADE")
            con.execute("CREATE SCHEMA hr_staging")
            for t in STD["order"]:
                cols, rows = extract(con, t)
                create_table(con, t, "hr_staging")
                with con.cursor().copy(f"COPY hr_staging.{q(t)} ({', '.join(q(c) for c in cols)}) FROM STDIN") as cp:
                    for r in rows:
                        cp.write_row([json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in r])
                n = con.execute(f"SELECT count(*) FROM hr_staging.{q(t)}").fetchone()[0]
                if n != len(rows):
                    raise SyncError(f"{t}: 원천 {len(rows)}행인데 {n}행만 적재됨")
                logs.append([t, len(rows), n, "적재", ""])
            add_fks(con, "hr_staging")

            ok, out = validate_schema(con, "hr_staging")
            summary = next((l for l in reversed(out) if "통과" in l), out[-1] if out else "")
            if not ok:
                fails = [l for l in out if l.startswith("[FAIL]")]
                raise SyncError("동기화 후 검사 실패 → hr은 이전 상태 유지. " + summary + " | " + " / ".join(fails[:3]))
            with con.transaction():
                con.execute("DROP SCHEMA IF EXISTS hr CASCADE")
                con.execute("ALTER SCHEMA hr_staging RENAME TO hr")
                con.execute("COMMENT ON SCHEMA hr IS '우리 표준 형식. 챗봇 조회 도구는 이 스키마만 읽음. 6단계 connector.py가 채움'")
            for l in logs:
                l[3], l[4] = "성공", f"검사 {summary}"
            status = "성공"
        except Exception as e:
            con.execute("RESET ROLE")
            con.execute("DROP SCHEMA IF EXISTS hr_staging CASCADE")
            for l in logs:
                l[3] = "취소"
            logs.append([None, None, None, "실패", str(e)])
            status = "실패"
        with con.transaction():
            for t, src, n, st, msg in logs:
                con.execute("INSERT INTO app.sync_log (run_id, company_id, table_name, source_rows, loaded_rows, "
                            "status, message, started_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (run_id, MAP["company"]["id"], t, src, n, st, msg, started))
        hr_n = {t: con.execute(f"SELECT count(*) FROM hr.{q(t)}").fetchone()[0] for t in STD["order"]} \
            if con.execute("SELECT 1 FROM pg_namespace WHERE nspname='hr'").fetchone() else {}

    print(f"동기화 {run_id} ({MAP['company']['name']}) — {status}")
    for t, src, n, st, msg in logs:
        if t:
            print(f"  {t:<16} 원천 {src:>7}  적재 {n:>7}  {st}")
        else:
            print(f"  ✗ {msg}")
    if status == "성공":
        print(f"  검사: {logs[0][4]}")
    print(f"지금 hr 스키마: 테이블 {len(hr_n)}개, 총 {sum(hr_n.values()):,}행  (기록: app.sync_log, run_id={run_id})")
    sys.exit(0 if status == "성공" else 1)


if __name__ == "__main__":
    main()
