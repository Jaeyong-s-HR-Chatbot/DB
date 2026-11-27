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

> 이미 띄워 둔 DB에 퇴직연금만 추가: `gunzip -c deploy/initdb/04_pension.sql.gz | docker exec -i nuri-hrdb psql -U hr -d hrdb` (이미 있으면 `DROP SCHEMA pension CASCADE;` 후)

> 이미 띄워 둔 DB에 기밀문서 역할만 추가: `docker exec -i nuri-hrdb psql -U hr -d hrdb < deploy/initdb/05_user_roles.sql`

> 이미 띄워 둔 DB가 있으면 카테고리 변경만 적용: `docker exec -i nuri-hrdb psql -U hr -d hrdb < deploy/initdb/03_categories.sql`
> (initdb 폴더는 DB를 처음 만들 때만 실행돼요. 처음부터 다시 만들어도 돼요: `docker compose down -v && docker compose up -d`)

## 방법 2. 이미 있는 PostgreSQL 16 + pgvector에 직접

```bash
createdb hrdb
psql -d hrdb -f deploy/initdb/00_extensions.sql
gunzip -c deploy/initdb/01_hrdb.sql.gz | psql -d hrdb
psql -d hrdb -f deploy/initdb/02_grants.sql
psql -d hrdb -f deploy/initdb/03_categories.sql
gunzip -c deploy/initdb/04_pension.sql.gz | psql -d hrdb      # 퇴직연금(가상) 데이터
psql -d hrdb -f deploy/initdb/05_user_roles.sql
```

## 들어 있는 것 (deploy/initdb)

| 파일 | 내용 |
| --- | --- |
| 00_extensions.sql | pgvector 확장, 커넥터 역할 hr_connector |
| 01_hrdb.sql.gz | 스키마 erp(회사 DB 흉내)·erp_ro(읽기 전용 뷰)·hr(표준 형식)·rag(규정 조각+임베딩)·app(동기화 기록) 전체 |
| 02_grants.sql | hr_connector는 erp_ro 뷰 SELECT만 |
| 03_categories.sql | `rag.chunks.category`(1개) → `categories`(여러 개). `rag_categories.py`가 만듦 |
| 04_pension.sql.gz | 퇴직연금(가상) 스키마 `pension`: 테이블 10개(가입 800명, 납입, 보유 상품, 거래, 상품·운용사·기준가 등) + 뷰 1개(`v_db_severance_estimate`, DB형 퇴직금 추정, **기준일 2026-11-19 고정**). 01 뒤에 실행돼야 해요(뷰가 `hr.payroll`을 씀). Docker는 파일 이름순으로 자동 실행. 자세한 규칙은 `data/pension/README_퇴직연금_데이터.md` |
| 07_appendix_links.sql | 조 ↔ 별표 연결표 `rag.appendix_links`(article_id, appendix_id, evidence). `rag_appendix_links.py`가 만듦. 조로 찾은 뒤 `rag.chunks.article_id = appendix_id`인 별표 조각을 리랭크 후보에 붙일 때 사용. 이미 띄운 DB: `docker exec -i nuri-hrdb psql -U hr -d hrdb < deploy/initdb/07_appendix_links.sql` |
| 08_hide_r32_broken_tables.sql | 위임전결규정 별표 1 중 결재권자 열이 사라져 `ㅇ`만 남은 15조각(부칙으로 잘못 잘림) `searchable = false`. 표로 옮겨 적은 r32-0025~0029는 그대로. 이미 띄운 DB: `docker exec -i nuri-hrdb psql -U hr -d hrdb < deploy/initdb/08_hide_r32_broken_tables.sql` |

- 테이블 35개, 약 49만 행, 규정·법령 조각 임베딩(BGE-M3, 1024차원) 2,583개, 문서 46건(규정 33 + 법령 13), 조각 2,915개
- 만든 방법: `.venv/bin/python db_export.py` — 덤프 후 새 DB에 되살려 모든 테이블 건수가 같은지 자동 확인
- 챗봇 조회 도구는 **hr**, 규정 검색은 **rag.chunks** (`embedding <=> 질문벡터`, `WHERE searchable AND categories && ARRAY['근태관리','공통']`)만 읽으면 됩니다
- 모든 인물·값은 가상 데이터입니다. 비밀번호 hrpass는 로컬 개발용입니다
