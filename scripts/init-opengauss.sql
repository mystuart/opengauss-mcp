-- openGauss 初始化脚本
-- 创建必要的扩展和用户权限

-- 创建扩展（如果不存在）
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS hypopg;

-- 创建示例数据库和用户（可选）
-- CREATE DATABASE mcp_test;
-- CREATE USER mcp_user WITH PASSWORD 'mcp_password';
-- GRANT ALL PRIVILEGES ON DATABASE mcp_test TO mcp_user;
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO mcp_user;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO mcp_user;

-- 创建示例表用于测试
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 插入一些示例数据
INSERT INTO users (name, email) VALUES 
('张三', 'zhangsan@example.com'),
('李四', 'lisi@example.com'),
('王五', 'wangwu@example.com')
ON CONFLICT (email) DO NOTHING;

INSERT INTO orders (user_id, amount, status) VALUES 
(1, 100.00, 'completed'),
(2, 200.00, 'pending'),
(3, 150.00, 'completed')
ON CONFLICT DO NOTHING;

-- 创建视图用于测试
CREATE OR REPLACE VIEW user_order_summary AS
SELECT 
    u.id,
    u.name,
    u.email,
    COUNT(o.id) as order_count,
    COALESCE(SUM(o.amount), 0) as total_amount
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
GROUP BY u.id, u.name, u.email;

-- 授权
GRANT SELECT ON ALL TABLES IN SCHEMA public TO PUBLIC;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO PUBLIC;