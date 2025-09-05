-- PostgreSQL Initialization Script
-- This script sets up the PostgreSQL database for comparison testing with MCP Pro

-- Create extensions
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS hypopg;

-- Create test schema
CREATE SCHEMA IF NOT EXISTS mcp_test;

-- Create sample tables for testing (same structure as GaussDB)
CREATE TABLE IF NOT EXISTS mcp_test.users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    is_active BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS mcp_test.orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES mcp_test.users(id),
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_amount DECIMAL(10,2),
    status VARCHAR(20) DEFAULT 'pending',
    shipping_address TEXT
);

CREATE TABLE IF NOT EXISTS mcp_test.products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    price DECIMAL(10,2),
    category VARCHAR(50),
    stock_quantity INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mcp_test.order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES mcp_test.orders(id),
    product_id INTEGER REFERENCES mcp_test.products(id),
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10,2)
);

-- Insert sample data (same as GaussDB)
INSERT INTO mcp_test.users (username, email, last_login, is_active) VALUES
    ('alice', 'alice@example.com', CURRENT_TIMESTAMP - INTERVAL '1 day', true),
    ('bob', 'bob@example.com', CURRENT_TIMESTAMP - INTERVAL '2 hours', true),
    ('charlie', 'charlie@example.com', CURRENT_TIMESTAMP - INTERVAL '1 week', false),
    ('diana', 'diana@example.com', CURRENT_TIMESTAMP - INTERVAL '3 days', true),
    ('eve', 'eve@example.com', NULL, true)
ON CONFLICT (username) DO NOTHING;

INSERT INTO mcp_test.products (name, description, price, category, stock_quantity) VALUES
    ('Laptop', 'High-performance laptop', 999.99, 'Electronics', 50),
    ('Mouse', 'Wireless optical mouse', 29.99, 'Electronics', 200),
    ('Keyboard', 'Mechanical keyboard', 79.99, 'Electronics', 100),
    ('Monitor', '24-inch LED monitor', 199.99, 'Electronics', 75),
    ('Desk Chair', 'Ergonomic office chair', 149.99, 'Furniture', 30)
ON CONFLICT DO NOTHING;

INSERT INTO mcp_test.orders (user_id, total_amount, status, shipping_address) VALUES
    (1, 1029.98, 'completed', '123 Main St, City, State'),
    (2, 79.99, 'pending', '456 Oak Ave, City, State'),
    (4, 349.98, 'shipped', '789 Pine Rd, City, State'),
    (1, 29.99, 'completed', '123 Main St, City, State')
ON CONFLICT DO NOTHING;

INSERT INTO mcp_test.order_items (order_id, product_id, quantity, unit_price) VALUES
    (1, 1, 1, 999.99),
    (1, 2, 1, 29.99),
    (2, 3, 1, 79.99),
    (3, 4, 1, 199.99),
    (3, 5, 1, 149.99),
    (4, 2, 1, 29.99)
ON CONFLICT DO NOTHING;

-- Create indexes for testing
CREATE INDEX IF NOT EXISTS idx_users_email ON mcp_test.users(email);
CREATE INDEX IF NOT EXISTS idx_users_last_login ON mcp_test.users(last_login);
CREATE INDEX IF NOT EXISTS idx_orders_user_id ON mcp_test.orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_date ON mcp_test.orders(order_date);
CREATE INDEX IF NOT EXISTS idx_products_category ON mcp_test.products(category);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON mcp_test.order_items(order_id);

-- Create a view for testing
CREATE OR REPLACE VIEW mcp_test.user_order_summary AS
SELECT 
    u.id,
    u.username,
    u.email,
    COUNT(o.id) as total_orders,
    COALESCE(SUM(o.total_amount), 0) as total_spent,
    MAX(o.order_date) as last_order_date
FROM mcp_test.users u
LEFT JOIN mcp_test.orders o ON u.id = o.user_id
GROUP BY u.id, u.username, u.email;

-- Create a function for testing
CREATE OR REPLACE FUNCTION mcp_test.get_user_stats(user_id INTEGER)
RETURNS TABLE(
    username VARCHAR(50),
    total_orders BIGINT,
    total_spent NUMERIC,
    avg_order_value NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        u.username,
        COUNT(o.id) as total_orders,
        COALESCE(SUM(o.total_amount), 0) as total_spent,
        COALESCE(AVG(o.total_amount), 0) as avg_order_value
    FROM mcp_test.users u
    LEFT JOIN mcp_test.orders o ON u.id = o.user_id
    WHERE u.id = user_id
    GROUP BY u.username;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions
GRANT USAGE ON SCHEMA mcp_test TO PUBLIC;
GRANT SELECT ON ALL TABLES IN SCHEMA mcp_test TO PUBLIC;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA mcp_test TO PUBLIC;

-- Create a test user for MCP connections
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mcp_user') THEN
        CREATE ROLE mcp_user WITH LOGIN PASSWORD 'mcp_password';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE postgres TO mcp_user;
GRANT USAGE ON SCHEMA mcp_test TO mcp_user;
GRANT SELECT ON ALL TABLES IN SCHEMA mcp_test TO mcp_user;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA mcp_test TO mcp_user;

-- Enable query statistics
SELECT pg_stat_statements_reset();

-- Create some sample queries to populate statistics
SELECT COUNT(*) FROM mcp_test.users;
SELECT COUNT(*) FROM mcp_test.orders;
SELECT COUNT(*) FROM mcp_test.products;
SELECT * FROM mcp_test.user_order_summary LIMIT 5;

COMMIT;