-- 材料实验室数据库初始化（按需执行）
CREATE USER lab WITH PASSWORD 'lab';
CREATE DATABASE materials_lab OWNER lab;
GRANT ALL PRIVILEGES ON DATABASE materials_lab TO lab;

-- 表结构由 SQLAlchemy metadata 在首次启动时创建：
--   backend/db.py: Base.metadata.create_all(engine)
-- JSONB 列：specimens.geometry, devices.params,
--           tests.raw_signal, tests.channel_units,
--           analyses.plan, analyses.excluded_points, analyses.report, analyses.summary
