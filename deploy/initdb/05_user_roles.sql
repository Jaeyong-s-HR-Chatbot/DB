-- 데모용 가짜 데이터. 권한기준 v0.2. 여러 번 실행해도 안전합니다.
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.user_roles (
    emp_id text NOT NULL,
    role text NOT NULL CHECK (role IN ('HR_DISCIPLINE', 'HR_LABOR', 'SYS_ADMIN')),
    scope_type text NOT NULL DEFAULT 'GLOBAL',
    scope_value text NOT NULL DEFAULT '*',
    granted_by text,
    valid_from date NOT NULL DEFAULT CURRENT_DATE,
    valid_to date,
    PRIMARY KEY (emp_id, role, scope_type, scope_value)
);

COMMENT ON COLUMN app.user_roles.emp_id IS '권한을 부여받은 직원의 사번';
COMMENT ON COLUMN app.user_roles.role IS '기밀문서 관련 역할';
COMMENT ON COLUMN app.user_roles.scope_type IS '권한 범위의 종류';
COMMENT ON COLUMN app.user_roles.scope_value IS '권한 범위의 값';
COMMENT ON COLUMN app.user_roles.granted_by IS '권한을 부여한 직원의 사번';
COMMENT ON COLUMN app.user_roles.valid_from IS '권한 유효 시작일';
COMMENT ON COLUMN app.user_roles.valid_to IS '권한 유효 종료일, NULL이면 무기한';

INSERT INTO app.user_roles (emp_id, role, scope_type, scope_value, granted_by, valid_from, valid_to)
VALUES
    ('E1686', 'HR_DISCIPLINE', 'GLOBAL', '*', 'E1003', DATE '2026-11-20', NULL),
    ('E1707', 'HR_LABOR', 'GLOBAL', '*', 'E1003', DATE '2026-11-20', NULL),
    ('E1622', 'SYS_ADMIN', 'GLOBAL', '*', 'E1003', DATE '2026-11-20', NULL)
ON CONFLICT DO NOTHING;
