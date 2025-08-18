# GaussDB 功能使用示例和故障排除指南

## 功能使用示例

### 1. 数据库健康检查

#### 基本健康检查

```python
# Python 客户端示例
import asyncio
from src.postgres_mcp.server import create_server

async def health_check_example():
    server = create_server()
    
    # 执行完整的数据库健康检查
    result = await server.call_tool("analyze_db_health", {})
    print("数据库健康状态:", result)
    
    # 检查特定组件
    index_health = await server.call_tool("analyze_db_health", {
        "component": "indexes"
    })
    print("索引健康状态:", index_health)

asyncio.run(health_check_example())
```

#### HTTP API 调用

```bash
# 完整健康检查
curl -X POST http://localhost:8000/mcp/tools/analyze_db_health \
  -H "Content-Type: application/json" \
  -d '{}'

# 检查连接健康
curl -X POST http://localhost:8000/mcp/tools/analyze_db_health \
  -H "Content-Type: application/json" \
  -d '{"component": "connections"}'

# 检查缓冲区健康
curl -X POST http://localhost:8000/mcp/tools/analyze_db_health \
  -H "Content-Type: application/json" \
  -d '{"component": "buffers"}'
```

### 2. 查询执行计划分析

#### 基本 EXPLAIN 分析

```python
async def explain_example():
    server = create_server()
    
    # 分析查询执行计划
    result = await server.call_tool("explain_query", {
        "query": "SELECT * FROM users WHERE age > 25 ORDER BY created_at",
        "analyze": True
    })
    print("执行计划:", result)

asyncio.run(explain_example())
```

#### HTTP API 调用

```bash
# 基本执行计划
curl -X POST http://localhost:8000/mcp/tools/explain_query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "SELECT u.name, p.title FROM users u JOIN posts p ON u.id = p.user_id WHERE u.active = true",
    "analyze": false
  }'

# 带实际执行统计的分析
curl -X POST http://localhost:8000/mcp/tools/explain_query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "SELECT * FROM orders WHERE order_date >= CURRENT_DATE - INTERVAL '\''30 days'\''",
    "analyze": true,
    "buffers": true
  }'
```

### 3. 索引调优建议

#### 工作负载分析

```python
async def index_tuning_example():
    server = create_server()
    
    # 分析工作负载并获取索引建议
    result = await server.call_tool("analyze_workload_indexes", {
        "hours": 24,  # 分析过去24小时的查询
        "min_calls": 10  # 最少执行10次的查询
    })
    print("索引建议:", result)
    
    # 分析特定查询的索引需求
    query_result = await server.call_tool("analyze_query_indexes", {
        "query": "SELECT * FROM products WHERE category_id = $1 AND price BETWEEN $2 AND $3"
    })
    print("查询索引建议:", query_result)

asyncio.run(index_tuning_example())
```

#### HTTP API 调用

```bash
# 工作负载索引分析
curl -X POST http://localhost:8000/mcp/tools/analyze_workload_indexes \
  -H "Content-Type: application/json" \
  -d '{
    "hours": 48,
    "min_calls": 5,
    "min_total_time": 1000
  }'

# 特定查询索引分析
curl -X POST http://localhost:8000/mcp/tools/analyze_query_indexes \
  -H "Content-Type: application/json" \
  -d '{
    "query": "SELECT o.*, c.name FROM orders o JOIN customers c ON o.customer_id = c.id WHERE o.status = '\''pending'\'' AND o.created_at > NOW() - INTERVAL '\''7 days'\''"
  }'
```

### 4. 基准测试

#### Sysbench 基准测试

```python
async def sysbench_example():
    server = create_server()
    
    # 运行 OLTP 读写测试
    result = await server.call_tool("gaussdb_benchmark", {
        "benchmark_type": "sysbench",
        "test_type": "oltp_read_write",
        "tables": 10,
        "table_size": 100000,
        "threads": 16,
        "time": 300  # 5分钟测试
    })
    print("Sysbench 结果:", result)

asyncio.run(sysbench_example())
```

#### TPC-C 基准测试

```bash
# TPC-C 基准测试
curl -X POST http://localhost:8000/mcp/tools/gaussdb_benchmark \
  -H "Content-Type: application/json" \
  -d '{
    "benchmark_type": "tpcc",
    "warehouses": 10,
    "connections": 20,
    "duration": 600,
    "ramp_up": 60
  }'
```

### 5. 慢查询分析

```python
async def slow_query_analysis():
    server = create_server()
    
    # 获取慢查询统计
    result = await server.call_tool("get_top_queries", {
        "limit": 20,
        "order_by": "total_time"
    })
    
    for query in result["queries"]:
        print(f"查询: {query['query'][:100]}...")
        print(f"总执行时间: {query['total_time']}ms")
        print(f"平均执行时间: {query['mean_time']}ms")
        print(f"执行次数: {query['calls']}")
        print("---")

asyncio.run(slow_query_analysis())
```

## 故障排除指南

### 1. 连接问题

#### 问题：无法连接到 GaussDB

**症状：**
```
ConnectionError: could not connect to server: Connection refused
```

**诊断步骤：**
```bash
# 1. 检查 GaussDB 服务状态
systemctl status gaussdb

# 2. 检查端口是否开放
netstat -tlnp | grep 8000

# 3. 测试网络连接
telnet your-gaussdb-host 8000

# 4. 检查防火墙设置
iptables -L | grep 8000
```

**解决方案：**
- 确保 GaussDB 服务正在运行
- 检查 `postgresql.conf` 中的 `listen_addresses` 设置
- 验证 `pg_hba.conf` 中的访问控制规则
- 确认防火墙允许相应端口的连接

#### 问题：认证失败

**症状：**
```
OperationalError: FATAL: password authentication failed for user "username"
```

**解决方案：**
```bash
# 1. 验证用户名和密码
psql -h your-gaussdb-host -p 8000 -U username -d database

# 2. 检查用户是否存在
SELECT usename FROM pg_user WHERE usename = 'your_username';

# 3. 重置密码（如果需要）
ALTER USER username PASSWORD 'new_password';
```

### 2. 兼容性问题

#### 问题：功能不支持

**症状：**
```
FeatureNotSupportedError: hypopg extension is not available in GaussDB
```

**解决方案：**
```python
# 检查功能可用性
from src.postgres_mcp.gaussdb.feature_checker import FeatureAvailabilityChecker

async def check_features():
    checker = FeatureAvailabilityChecker(sql_driver)
    
    hypopg_available = await checker.check_hypopg_support()
    if not hypopg_available:
        print("假设索引功能不可用，将使用替代方案")
    
    pg_stat_available = await checker.check_pg_stat_statements()
    if not pg_stat_available:
        print("查询统计功能不可用")
```

#### 问题：查询语法错误

**症状：**
```
SyntaxError: syntax error at or near "EXPLAIN"
```

**解决方案：**
- 检查 GaussDB 版本兼容性
- 查看查询适配日志
- 使用兼容的查询语法

```python
# 启用查询适配调试
import logging
logging.getLogger('postgres_mcp.gaussdb.sql_driver_adapter').setLevel(logging.DEBUG)
```

### 3. 性能问题

#### 问题：查询执行缓慢

**诊断步骤：**
```python
async def diagnose_performance():
    server = create_server()
    
    # 1. 检查数据库健康状态
    health = await server.call_tool("analyze_db_health", {})
    
    # 2. 分析慢查询
    slow_queries = await server.call_tool("get_top_queries", {
        "limit": 10,
        "order_by": "mean_time"
    })
    
    # 3. 检查索引使用情况
    for query in slow_queries["queries"]:
        explain = await server.call_tool("explain_query", {
            "query": query["query"],
            "analyze": True
        })
        print(f"查询计划: {explain}")
```

**优化建议：**
- 创建适当的索引
- 优化查询语句
- 调整数据库配置参数
- 考虑分区策略

### 4. 基准测试问题

#### 问题：基准测试失败

**症状：**
```
BenchmarkError: sysbench command not found
```

**解决方案：**
```bash
# 1. 安装 sysbench
# Ubuntu/Debian
apt-get install sysbench

# CentOS/RHEL
yum install sysbench

# 2. 验证安装
sysbench --version

# 3. 检查路径配置
export SYSBENCH_PATH=/usr/bin/sysbench
```

#### 问题：基准测试数据准备失败

**解决方案：**
```python
# 手动准备测试数据
async def prepare_benchmark_data():
    server = create_server()
    
    # 创建测试表
    await server.call_tool("execute_sql", {
        "query": """
        CREATE TABLE IF NOT EXISTS sbtest1 (
            id SERIAL PRIMARY KEY,
            k INTEGER DEFAULT 0 NOT NULL,
            c CHAR(120) DEFAULT '' NOT NULL,
            pad CHAR(60) DEFAULT '' NOT NULL
        )
        """,
        "readonly": False
    })
    
    # 插入测试数据
    for i in range(1000):
        await server.call_tool("execute_sql", {
            "query": "INSERT INTO sbtest1 (k, c, pad) VALUES ($1, $2, $3)",
            "params": [i, f"test_data_{i}", f"pad_{i}"],
            "readonly": False
        })
```

### 5. 日志和调试

#### 启用详细日志

```python
import logging

# 配置日志级别
logging.basicConfig(level=logging.DEBUG)

# 特定组件的日志
loggers = [
    'postgres_mcp.gaussdb',
    'postgres_mcp.sql.sql_driver',
    'postgres_mcp.database_health',
    'postgres_mcp.benchmark'
]

for logger_name in loggers:
    logging.getLogger(logger_name).setLevel(logging.DEBUG)
```

#### 常用调试命令

```bash
# 查看连接状态
SELECT * FROM pg_stat_activity WHERE datname = 'your_database';

# 检查锁等待
SELECT * FROM pg_locks WHERE NOT granted;

# 查看查询统计
SELECT query, calls, total_time, mean_time 
FROM pg_stat_statements 
ORDER BY total_time DESC 
LIMIT 10;

# 检查索引使用情况
SELECT schemaname, tablename, indexname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;
```

## 最佳实践

### 1. 监控和维护

- 定期运行数据库健康检查
- 监控慢查询并及时优化
- 定期更新统计信息
- 监控连接数和资源使用

### 2. 性能优化

- 使用连接池减少连接开销
- 合理设置查询超时时间
- 定期运行 VACUUM 和 ANALYZE
- 监控和调整内存参数

### 3. 安全考虑

- 使用最小权限原则
- 定期轮换数据库密码
- 启用 SSL 连接
- 监控异常访问模式

### 4. 故障预防

- 设置适当的监控告警
- 定期备份配置文件
- 测试故障恢复流程
- 保持系统和依赖项更新

## 获取帮助

如果遇到本指南未涵盖的问题：

1. 查看系统日志获取详细错误信息
2. 检查 [API 参考文档](gaussdb-api-reference.md)
3. 参考 [架构设计文档](gaussdb-architecture-guide.md)
4. 在项目 GitHub 仓库提交 Issue