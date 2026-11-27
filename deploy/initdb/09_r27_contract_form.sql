-- 전문직직원 운영 세칙(r27) 별지 1 근로계약서 안의 제1조(당사자)~제10조(기타)가 조문으로 잘려 검색되던 것 (2026-11-27)
-- → 별지 1 서식의 이어지는 조각으로 바꾸고 검색 대상에서 뺌. 조각 id(r27-0034~0043)는 그대로.
-- 데이터 파일은 rag_build.py(새로 만들 때)·rag_tables.py fold_form_articles(이미 만든 파일)가 같은 일을 함.
-- 조문 단위 DB(01 덤프)와 항 단위 DB(rag_load_hang.py) 둘 다에서 돌아감. 이미 만든 DB에도 그대로 실행하면 됨
SET client_encoding = 'UTF8';
DO $$
DECLARE ids text[] := ARRAY['r27-0034','r27-0035','r27-0036','r27-0037','r27-0038',
                            'r27-0039','r27-0040','r27-0041','r27-0042','r27-0043'];
        t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['rag.chunks', 'rag.chunks_article'] LOOP
        IF to_regclass(t) IS NULL THEN CONTINUE; END IF;
        EXECUTE format($q$UPDATE %s c SET chunk_type = '서식', article = f.article, article_title = f.article_title,
                              categories = f.categories, searchable = false
                          FROM %s f WHERE f.chunk_id = 'r27-0033' AND c.chunk_id = ANY($1)$q$, t, t) USING ids;
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'rag' AND table_name = split_part(t, '.', 2) AND column_name = 'article_id') THEN
            EXECUTE format($q$UPDATE %s SET article_id = 'r27:별지 1', hang = '', granularity = '그대로'
                              WHERE chunk_id = ANY($1)$q$, t) USING ids;
        END IF;
    END LOOP;
    IF to_regclass('rag.articles') IS NOT NULL THEN
        DELETE FROM rag.articles WHERE document_id = 'r27' AND article_id LIKE 'r27:제%조#2';
    END IF;
    UPDATE rag.documents d SET searchable = (SELECT count(*) FROM rag.chunks c WHERE c.document_id = 'r27' AND c.searchable)
    WHERE d.document_id = 'r27';
END $$;
