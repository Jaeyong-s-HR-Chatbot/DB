# DB 배포 (누리철도 HR DB)

내 컴퓨터에서 만든 hrdb(가상 임직원 데이터 + 규정·법령 조문 조각 + 임베딩)를 팀원 누구나 같은 상태로 띄우는 방법입니다.

## 방법 1. Docker (추천)

```bash
docker compose up -d                 # 저장소 맨 위 폴더에서. 처음 켤 때 initdb 덤프로 hrdb 생성 (1~2분)
docker compose logs -f hrdb          # "database system is ready" 나오면 완료
```

- 접속: `postgresql://hr:hrpass@localhost:5432/hrdb` (DBeaver·psql·파이썬 어디서든)
- 처음부터 다시: `docker compose down -v && docker compose up -d`
- 저장소 스크립트를 이 DB에 붙이기: `export HRDB_URL=postgresql://hr:hrpass@localhost:5432/hrdb` 후 `connector.py`, `db_viewer.py` 등 실행

> 이미 띄워 둔 DB가 있으면 카테고리 변경만 적용: `docker exec -i nuri-hrdb psql -U hr -d hrdb < deploy/initdb/03_categories.sql`
> (initdb 폴더는 DB를 처음 만들 때만 실행돼요. 처음부터 다시 만들어도 돼요: `docker compose down -v && docker compose up -d`)

## 방법 2. 이미 있는 PostgreSQL 16 + pgvector에 직접

```bash
createdb hrdb
psql -d hrdb -f deploy/initdb/00_extensions.sql
gunzip -c deploy/initdb/01_hrdb.sql.gz | psql -d hrdb
psql -d hrdb -f deploy/initdb/02_grants.sql
psql -d hrdb -f deploy/initdb/03_categories.sql
```

## 들어 있는 것 (deploy/initdb)

| 파일 | 내용 |
| --- | --- |
| 00_extensions.sql | pgvector 확장, 커넥터 역할 hr_connector |
| 01_hrdb.sql.gz | 스키마 erp(회사 DB 흉내)·erp_ro(읽기 전용 뷰)·hr(표준 형식)·rag(규정 조각+임베딩)·app(동기화 기록) 전체 |
| 02_grants.sql | hr_connector는 erp_ro 뷰 SELECT만 |
| 03_categories.sql | `rag.chunks.category`(1개) → `categories`(여러 개). `rag_categories.py`가 만듦 |

- 테이블 35개, 약 49만 행, 규정·법령 조각 임베딩(BGE-M3, 1024차원) 2,583개, 문서 46건(규정 33 + 법령 13), 조각 2,915개
- 만든 방법: `.venv/bin/python db_export.py` — 덤프 후 새 DB에 되살려 모든 테이블 건수가 같은지 자동 확인
- 챗봇 조회 도구는 **hr**, 규정 검색은 **rag.chunks** (`embedding <=> 질문벡터`, `WHERE searchable AND categories && ARRAY['근태관리','공통']`)만 읽으면 됩니다
- 모든 인물·값은 가상 데이터입니다. 비밀번호 hrpass는 로컬 개발용입니다
