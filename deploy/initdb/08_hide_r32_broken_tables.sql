-- 위임전결규정(r32) 별표 1 중 결재권자 열이 사라져 'ㅇ'만 남은 15조각을 검색 대상에서 뺌 (2026-11-27)
-- '부칙'으로 잘못 잘린 조각들. 표로 옮겨 적은 r32-0025~0029(근무상황·출장 결재 등)와 진짜 부칙 r32-0013은 그대로.
-- 데이터 파일은 rag_tables.py(hide_broken_delegation)가 같은 일을 함. 이미 만든 DB에도 그대로 실행하면 됨
DO $$
DECLARE ids text[] := ARRAY['r32-0014','r32-0015','r32-0016','r32-0017','r32-0018','r32-0019','r32-0020',
                            'r32-0021','r32-0022','r32-0023','r32-0024','r32-0030','r32-0031','r32-0032','r32-0033'];
BEGIN
    UPDATE rag.chunks SET searchable = false WHERE chunk_id = ANY(ids);
    IF to_regclass('rag.chunks_article') IS NOT NULL THEN
        UPDATE rag.chunks_article SET searchable = false WHERE chunk_id = ANY(ids);
    END IF;
    UPDATE rag.documents d SET searchable = (SELECT count(*) FROM rag.chunks c WHERE c.document_id = 'r32' AND c.searchable)
    WHERE d.document_id = 'r32';
END $$;
