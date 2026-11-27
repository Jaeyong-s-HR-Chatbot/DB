"""통합 ETL 실행: CSV 동기화 → 규정·법령 받기(변경 확인) → 조각내기(바뀐 문서만 파싱) → 임베딩(바뀐 조각만) → rag 적재.
단계마다 app.etl_runs 에 기록. 규정·법령은 새로 받은 것/개정된 것이 있으면 기록(records 칸)에 건수가 남음.

실행: .venv/bin/python run_etl.py [--only csv,regs,...] [--from 단계] [--skip-fetch]
- 단계 실패 시 거기서 멈추고 실패 사유 기록. 같은 명령으로 다시 실행하면 됨 (각 단계는 다시 돌려도 안전)
- cron 예: 0 3 * * *  cd <hr_db> && .venv/bin/python run_etl.py >> data/etl.log 2>&1
- 임베딩은 torch 환경(~/rag_local/.venv)에서 실행. 환경변수 EMBED_PY 로 바꿀 수 있음
"""
import argparse
import datetime as dt
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from db_setup import connect, get_server

HERE = Path(__file__).parent
PY = sys.executable
EMBED_PY = os.environ.get("EMBED_PY", str(Path.home() / "rag_local/.venv/bin/python"))
STEPS = [  # (이름, 명령)
    ("csv", [PY, "connector.py"]),
    ("regs_fetch", [PY, "rag_fetch.py"]),
    ("laws_fetch", [PY, "law_fetch_api.py"]),
    ("ocr", [str(Path.home() / "ocr_local/bin/python"), "ocr_build.py"]),  # 스캔 쪽 OCR (이미 읽은 쪽은 건너뜀). 기본은 꺼짐: --with-ocr
    ("regs_build", [PY, "rag_build.py"]),
    ("laws_build", [PY, "law_build.py"]),
    ("embed_regs", [EMBED_PY, "rag_embed.py", "data/regs"]),
    ("embed_laws", [EMBED_PY, "rag_embed.py", "data/laws"]),
    ("rag_load", [PY, "rag_load.py"]),
    # 항 단위 조각 (팀 DB 저장소 8단계): rag_load 가 rag.chunks 를 조문 단위로 다시 만들기 때문에 바로 뒤에서 항 단위로 교체한다.
    # 글자가 같은 조각은 data/hang/embeddings.npy·예전 임베딩을 재사용해 새 조각만 임베딩 (처음 약 5분, 이후 몇 초)
    ("rechunk_hang", [PY, "rag_rechunk.py"]),
    ("load_hang", ["env", f"HRDB_URL=postgresql://postgres:@/hrdb?host={HERE / 'pgdata'}", f"PYTHONPATH={Path.home() / 'rag_local/extra_site'}",
                   "HF_HUB_OFFLINE=1", EMBED_PY, "rag_load_hang.py"]),
    ("old_to_new", [PY, "rag_old_to_new.py"]),   # 조문 단위 예전 조각 → 항 단위 새 조각 대응표 (골든셋 항 단위 정답 칸 만들 때 씀)
    # 퇴직연금 (팀 결정: 상품·시세 모두 가상). 맨 끝에 둬서 실패해도 위 단계에 영향 없음.
    # 실제 공시 API 경로(pension_fetch_api.py → pension_build.py --source api)는 코드만 보관 중이고 ETL 에는 넣지 않음
    ("pension_sim", [PY, "pension/pension_sim.py"]),       # 가상 기준가: 새 영업일이 생기면 그 날짜분이 늘어남
    ("pension_build", [PY, "pension/pension_build.py"]),
    ("pension_load", [PY, "pension/pension_load.py"]),
    # 권한 기준(app.user_roles·데모 계정·rag 등급 칸): rag_load 가 rag 스키마를 새로 만들기 때문에 rag 단계가 다 끝난 뒤에 붙인다
    ("access", [PY, "access_build.py"]),
]


def setup(con):
    con.execute("CREATE SCHEMA IF NOT EXISTS app")
    con.execute("""CREATE TABLE IF NOT EXISTS app.etl_runs (
        id bigserial PRIMARY KEY, run_id text NOT NULL, step text NOT NULL, status text NOT NULL,
        started_at timestamptz NOT NULL, finished_at timestamptz, seconds numeric, records text, error text)""")
    con.execute("COMMENT ON TABLE app.etl_runs IS '통합 ETL(run_etl.py) 단계별 실행 기록: 시작·종료, 출력 마지막 줄(처리 건수), 실패 사유'")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--with-ocr", action="store_true", help="스캔 쪽 OCR 단계 포함 (새 스캔 쪽만 읽음, 느림)")
    ap.add_argument("--skip-fetch", action="store_true", help="ALIO·법제처 새로 받기(변경 확인) 건너뜀")
    a = ap.parse_args()
    names = [n for n, _ in STEPS]
    sel = a.only.split(",") if a.only else names[names.index(a.start):] if a.start else names
    if not a.with_ocr and not a.only:
        sel = [n for n in sel if n != "ocr"]
    if a.skip_fetch:
        sel = [n for n in sel if n not in ("regs_fetch", "laws_fetch", "pension_fetch")]
    run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    srv = get_server()
    ok_all = True
    with connect(srv) as con:
        setup(con)
        con.commit()
        for name, cmd in STEPS:
            if name not in sel:
                continue
            t0 = dt.datetime.now().astimezone()
            res = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
            t1 = dt.datetime.now().astimezone()
            lines = [l for l in (res.stdout + res.stderr).strip().splitlines() if l.strip()]
            good = res.returncode == 0
            con.execute("INSERT INTO app.etl_runs (run_id, step, status, started_at, finished_at, seconds, records, error) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (run_id, name, "성공" if good else "실패", t0, t1, round((t1 - t0).total_seconds(), 1),
                         lines[-1][:300] if lines else "", None if good else "\n".join(lines[-8:])[:2000]))
            con.commit()
            print(f"[{'OK' if good else 'FAIL'}] {name:<11} {(t1 - t0).total_seconds():6.1f}초  {lines[-1][:80] if lines else ''}")
            if not good:
                print("\n".join(lines[-8:]))
                ok_all = False
                break
    print(f"ETL {run_id} — {'성공' if ok_all else '실패(위 단계에서 중단, app.etl_runs 참고)'}")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
