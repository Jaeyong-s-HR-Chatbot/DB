-- 철도공사 기간제근로자운영내규(r16) 삭제: 팀 결정(2026-11-27). 이미 만든 DB에도 그대로 실행하면 됨
DO $$
BEGIN
    IF to_regclass('rag.chunks_article') IS NOT NULL THEN
        DELETE FROM rag.chunks_article WHERE document_id = 'r16';
    END IF;
    IF to_regclass('rag.articles') IS NOT NULL THEN
        DELETE FROM rag.articles WHERE document_id = 'r16';
    END IF;
END $$;
DELETE FROM rag.chunks WHERE document_id = 'r16';
DELETE FROM rag.documents WHERE document_id = 'r16';
