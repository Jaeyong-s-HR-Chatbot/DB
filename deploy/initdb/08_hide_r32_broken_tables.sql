-- 위임전결규정(r32) 별표 1(본사 전결사항): 부칙 뒤에 붙어 '부칙' 조각으로 잘렸던 것 (2026-11-27)
-- r32-0014~0033 → '별표 1' 조각 (제8조 "별표 1과 같다"와 연결, rag.appendix_links)
-- 검색 대상(searchable)은 건드리지 않음: #23 에서 20조각 모두 마크다운 표로 바뀌어 데이터 파일에서 다시 검색 대상이 됨.
--   (예전 이 파일은 'ㅇ'만 남은 15조각을 searchable=false 로 숨겼음. rag_load_hang.py 로 다시 적재하면 파일 값으로 돌아감)
-- 데이터 파일은 rag_tables.py(hide_broken_delegation)가 같은 일을 함.
-- 파일 이름은 local_db.py·지시문과 맞추려고 그대로 둠.
-- 조문 단위 DB(01 덤프)와 항 단위 DB(rag_load_hang.py) 둘 다에서 돌아감. 이미 만든 DB에도 그대로 실행하면 됨
SET client_encoding = 'UTF8';
DO $$
DECLARE ids text[] := ARRAY['r32-0014','r32-0015','r32-0016','r32-0017','r32-0018','r32-0019','r32-0020',
                            'r32-0021','r32-0022','r32-0023','r32-0024','r32-0025','r32-0026','r32-0027',
                            'r32-0028','r32-0029','r32-0030','r32-0031','r32-0032','r32-0033'];
        t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['rag.chunks', 'rag.chunks_article'] LOOP
        IF to_regclass(t) IS NULL THEN CONTINUE; END IF;
        EXECUTE format($q$UPDATE %s SET chunk_type = '별표', article = '별표 1', article_title = '본사 전결사항'
                          WHERE chunk_id = ANY($1)$q$, t) USING ids;
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'rag' AND table_name = split_part(t, '.', 2) AND column_name = 'article_id') THEN
            EXECUTE format($q$UPDATE %s SET article_id = 'r32:별표 1', hang = '', granularity = '그대로'
                              WHERE chunk_id = ANY($1)$q$, t) USING ids;
        END IF;
    END LOOP;
END $$;
