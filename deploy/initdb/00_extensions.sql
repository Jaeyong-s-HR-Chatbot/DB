-- 1) 확장과 역할 (덤프보다 먼저 실행됨)
CREATE EXTENSION IF NOT EXISTS vector;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hr_connector') THEN
  CREATE ROLE hr_connector NOLOGIN; END IF; END $$;
