-- 3) 커넥터 역할은 고객사가 열어 준 읽기 전용 뷰(erp_ro)만 읽을 수 있음
REVOKE ALL ON SCHEMA erp FROM hr_connector;
GRANT USAGE ON SCHEMA erp_ro TO hr_connector;
GRANT SELECT ON ALL TABLES IN SCHEMA erp_ro TO hr_connector;
