# GaussDB 连接配置指南

## 概述

本指南将帮助您配置 Postgres MCP Pro 服务器以连接到华为 GaussDB 数据库。GaussDB 是基于 PostgreSQL 内核的企业级分布式数据库，本 MCP 服务器提供了完整的 GaussDB 兼容性支持。

## 前提条件

- GaussDB 数据库实例（版本 8.1.0 或更高）
- Python 3.8 或更高版本
- 已安装的 Postgres MCP Pro 服务器

## 连接配置

### 1. 环境变量配置

创建或更新您的环境配置文件：

```bash
# 基本连接配置
DATABASE_URI=postgresql://username:password@hostname:port/database_name

# GaussDB 特定配置
GAUSSDB_VERSION=8.1.0
GAUSSDB_COMPATIBILITY_MODE=auto  # auto, force, disabled

# 可选：启用基准测试功能
BENCHMARK_ENABLED=true
SYSBENCH_PATH=/usr/bin/sysbench
TPCC_PATH=/usr/bin/tpcc

# 可选：日志配置
LOG_LEVEL=INFO
GAUSSDB_DEBUG=false
```

### 2. 连接字符串格式

GaussDB 连接字符串遵循标准 PostgreSQL 格式：

```
postgresql://[username[:password]@][host[:port]][/database][?param1=value1&...]
```

**示例：**
```bash
# 基本连接
DATABASE_URI=postgresql://gaussdb_user:password@192.168.1.100:8000/testdb

# 使用 SSL 连接
DATABASE_URI=postgresql://gaussdb_user:password@192.168.1.100:8000/testdb?sslmode=require

# 连接池配置
DATABASE_URI=postgresql://gaussdb_user:password@192.168.1.100:8000/testdb?pool_size=10&max_overflow=20
```

### 3. Docker 配置

如果使用 Docker 部署，可以使用提供的 `docker-compose.gaussdb.yml` 文件：

```bash
# 复制环境配置文件
cp config/env.gaussdb.example .env.gaussdb

# 编辑配置文件
vim .env.gaussdb

# 启动服务
docker-compose -f docker-compose.gaussdb.yml up -d
```

### 4. 兼容性模式配置

系统支持三种兼容性模式：

- **auto**（推荐）：自动检测数据库类型并启用相应的兼容性功能
- **force**：强制启用 GaussDB 兼容性模式，即使检测失败
- **disabled**：禁用 GaussDB 特定功能，使用标准 PostgreSQL 模式

## 连接验证

### 1. 基本连接测试

使用以下命令测试连接：

```bash
# 使用配置验证脚本
python scripts/validate_gaussdb_config.py

# 或者直接测试连接
python -c "
import asyncio
from src.postgres_mcp.sql.sql_driver import SqlDriver

async def test_connection():
    driver = SqlDriver('your_connection_string')
    result = await driver.execute_query('SELECT version()')
    print(f'Connected to: {result[0][0]}')

asyncio.run(test_connection())
"
```

### 2. 功能验证

验证 GaussDB 特定功能是否正常工作：

```bash
# 测试数据库健康检查
curl -X POST http://localhost:8000/mcp/tools/analyze_db_health \
  -H "Content-Type: application/json" \
  -d '{}'

# 测试查询执行计划
curl -X POST http://localhost:8000/mcp/tools/explain_query \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT * FROM pg_stat_activity LIMIT 5"}'
```

## 常见问题

### 连接问题

**问题：** 连接超时或拒绝连接
```
解决方案：
1. 检查 GaussDB 服务是否运行
2. 验证网络连接和防火墙设置
3. 确认端口号正确（GaussDB 默认端口通常是 8000）
4. 检查用户名和密码是否正确
```

**问题：** SSL 连接失败
```
解决方案：
1. 确认 GaussDB 实例启用了 SSL
2. 使用正确的 SSL 模式：sslmode=require 或 sslmode=prefer
3. 如果使用自签名证书，添加 sslmode=require&sslcert=path/to/cert
```

### 兼容性问题

**问题：** 某些功能不可用
```
解决方案：
1. 检查 GaussDB 版本是否支持该功能
2. 查看兼容性配置文件 gaussdb_compatibility.yaml
3. 启用调试模式查看详细错误信息：GAUSSDB_DEBUG=true
```

**问题：** 查询语法错误
```
解决方案：
1. 系统会自动适配大部分 PostgreSQL 查询到 GaussDB
2. 对于不支持的语法，系统会提供错误信息和建议
3. 查看日志了解具体的查询适配过程
```

## 性能优化

### 连接池配置

```bash
# 推荐的连接池设置
DATABASE_URI=postgresql://user:pass@host:port/db?pool_size=20&max_overflow=30&pool_timeout=30
```

### 查询优化

- 启用查询统计：确保 GaussDB 实例启用了 `pg_stat_statements` 扩展
- 使用索引调优功能获得性能建议
- 定期运行数据库健康检查

## 安全配置

### 1. 用户权限

确保连接用户具有必要的权限：

```sql
-- 基本查询权限
GRANT SELECT ON ALL TABLES IN SCHEMA public TO gaussdb_user;
GRANT SELECT ON ALL TABLES IN SCHEMA information_schema TO gaussdb_user;
GRANT SELECT ON ALL TABLES IN SCHEMA pg_catalog TO gaussdb_user;

-- 健康检查权限
GRANT SELECT ON pg_stat_activity TO gaussdb_user;
GRANT SELECT ON pg_stat_database TO gaussdb_user;
GRANT SELECT ON pg_stat_user_tables TO gaussdb_user;
GRANT SELECT ON pg_stat_user_indexes TO gaussdb_user;

-- 基准测试权限（可选）
GRANT CREATE ON DATABASE testdb TO gaussdb_user;
GRANT USAGE ON SCHEMA public TO gaussdb_user;
```

### 2. 网络安全

- 使用 SSL/TLS 加密连接
- 限制数据库访问的 IP 地址范围
- 使用强密码和定期轮换
- 考虑使用连接代理或 VPN

## 监控和日志

### 启用详细日志

```bash
# 环境变量配置
LOG_LEVEL=DEBUG
GAUSSDB_DEBUG=true

# 或在代码中配置
import logging
logging.getLogger('postgres_mcp.gaussdb').setLevel(logging.DEBUG)
```

### 监控指标

系统会自动收集以下监控指标：
- 连接状态和延迟
- 查询执行时间
- 错误率和类型
- 功能使用统计

## 下一步

配置完成后，您可以：
1. 阅读[功能使用示例和故障排除指南](gaussdb-usage-examples.md)
2. 查看[API 参考文档](gaussdb-api-reference.md)
3. 了解[架构设计和扩展开发](gaussdb-architecture-guide.md)