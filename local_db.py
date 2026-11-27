"""내 컴퓨터에 hrdb 띄우기 (PostgreSQL 비밀번호·Docker 필요 없음).

pgserver 에 들어 있는 PostgreSQL 16 + pgvector 를 DB/pgdata 폴더로 켭니다.
이미 깔린 PostgreSQL 18(5432)과 겹치지 않게 포트 5433 을 씁니다.

  .venv\\Scripts\\python local_db.py start    # 켜기 (컴퓨터 다시 켠 뒤에도 이것만)
  .venv\\Scripts\\python local_db.py load     # 처음 한 번: 팀 덤프(deploy/initdb)로 hrdb 만들기
  .venv\\Scripts\\python local_db.py stop     # 끄기
  .venv\\Scripts\\python local_db.py status
  (맥·리눅스는 .venv/bin/python local_db.py ... 로 같은 명령)

접속: postgresql://hr:hrpass@localhost:5433/hrdb  (로컬 접속만 허용, 가상 데이터 전용)
"""
import gzip
import os
import subprocess
import sys
from pathlib import Path

import pgserver

HERE = Path(__file__).parent
PGDATA = HERE / "pgdata"
BIN = Path(pgserver.__file__).parent / "pginstall" / "bin"
INIT = HERE / "deploy" / "initdb"
PORT = 5433


def exe(name):
    """Windows 는 .exe, 맥·리눅스는 확장자 없음"""
    return name + (".exe" if os.name == "nt" else "")
URL = f"postgresql://hr:hrpass@localhost:{PORT}/hrdb"


def run(*args, **kw):
    return subprocess.run([str(BIN / args[0]), *args[1:]], check=True, **kw)


def running():
    return subprocess.run([str(BIN / exe("pg_ctl")), "-D", str(PGDATA), "status"], capture_output=True).returncode == 0


def start():
    if not (PGDATA / "PG_VERSION").exists():
        pgserver.get_server(str(PGDATA), cleanup_mode=None)  # 처음: initdb (trust, 로컬만)
        run(exe("pg_ctl"), "-D", str(PGDATA), "stop", "-m", "fast")
    if running():
        print("이미 켜져 있어요")
    else:
        # 서버가 이 창의 입출력을 물고 있지 않게 (안 그러면 명령이 안 끝난 것처럼 보임)
        run(exe("pg_ctl"), "-D", str(PGDATA), "-l", str(PGDATA / "server.log"), "-o", f"-p {PORT} -c listen_addresses=localhost", "-w", "start",
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    print("접속:", URL)


def psql(db, *args, user="postgres", **kw):
    return run(exe("psql"), "-h", "localhost", "-p", str(PORT), "-U", user, "-d", db, "-v", "ON_ERROR_STOP=1", "-q", *args, **kw)


def load():
    start()
    out = subprocess.run([str(BIN / exe("psql")), "-h", "localhost", "-p", str(PORT), "-U", "postgres", "-tAc",
                          "SELECT 1 FROM pg_database WHERE datname='hrdb'"], capture_output=True, text=True).stdout.strip()
    if out == "1":
        sys.exit("hrdb 가 이미 있어요. 처음부터 다시: stop 후 pgdata 폴더를 지우고 load")
    psql("postgres", "-c", "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='hr') "
                           "THEN CREATE ROLE hr LOGIN PASSWORD 'hrpass'; END IF; END $$;")
    psql("postgres", "-c", "CREATE DATABASE hrdb OWNER hr ENCODING 'UTF8' TEMPLATE template0")
    psql("hrdb", "-f", str(INIT / "00_extensions.sql"))
    print("덤프 적재 중 (1~2분)")
    with gzip.open(INIT / "01_hrdb.sql.gz", "rb") as f:
        psql("hrdb", user="hr", input=f.read(), stdout=subprocess.DEVNULL)
    psql("hrdb", "-f", str(INIT / "02_grants.sql"), user="hr")
    psql("hrdb", "-f", str(INIT / "03_categories.sql"), user="hr")
    pension = INIT / "04_pension.sql.gz"   # 퇴직연금(가상) pension 스키마. 01 뒤에 실행 (뷰가 hr.payroll 을 씀)
    if pension.exists():
        with gzip.open(pension, "rb") as f:
            psql("hrdb", user="hr", input=f.read(), stdout=subprocess.DEVNULL)
    psql("hrdb", "-f", str(INIT / "05_user_roles.sql"), user="hr")   # 기밀문서 역할 (app.user_roles)
    psql("hrdb", "-f", str(INIT / "06_remove_r16.sql"), user="hr")   # 기간제근로자운영내규 삭제
    psql("hrdb", "-f", str(INIT / "07_appendix_links.sql"), user="hr")   # 조 ↔ 별표 연결표 (rag.appendix_links)
    psql("hrdb", "-f", str(INIT / "08_hide_r32_broken_tables.sql"), user="hr")   # 위임전결 깨진 표 15조각 검색 제외
    psql("hrdb", "-f", str(INIT / "09_r27_contract_form.sql"), user="hr")   # 전문직 근로계약서 안의 조 → 서식
    print("완료:", URL)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "start":
        start()
    elif cmd == "stop":
        run(exe("pg_ctl"), "-D", str(PGDATA), "stop", "-m", "fast")
    elif cmd == "status":
        print("켜짐" if running() else "꺼짐", URL)
    elif cmd == "load":
        load()
    else:
        sys.exit(__doc__)
