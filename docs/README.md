# GaussDB 兼容性扩展文档

欢迎使用 Postgres MCP Pro 服务器的 GaussDB 兼容性扩展文档。本文档集提供了完整的配置、使用和开发指南。

## 文档概览

### 🚀 快速开始

- **[GaussDB 连接配置指南](gaussdb-connection-guide.md)** - 配置 MCP 服务器连接到 GaussDB 数据库
- **[功能使用示例和故障排除](gaussdb-usage-examples.md)** - 实用的使用示例和常见问题解决方案

### 📚 参考文档

- **[API 参考文档](gaussdb-api-reference.md)** - 完整的 API 接口文档和参数说明
- **[架构设计和扩展开发指南](gaussdb-architecture-guide.md)** - 深入的架构设计和扩展开发指南

## 功能特性

### ✅ 已支持功能

- **数据库连接和检测**：自动检测 GaussDB 数据库类型和版本
- **健康检查**：全面的数据库健康状态分析
  - 索引健康检查
  - 连接状态监控
  - 缓冲区使用分析
  - 清理和维护状态
  - 序列和约束检查
- **查询分析**：执行计划分析和优化建议
- **索引调优**：基于工作负载的索引优化建议
- **基准测试**：集成 Sysbench 和 TPC-C 基准测试工具
- **兼容性适配**：自动适配 PostgreSQL 查询到 GaussDB 格式

### 🔄 版本兼容性

| GaussDB 版本 | 支持状态 | 功能完整性 |
|-------------|----------|------------|
| 8.1.0+ | ✅ 完全支持 | 100% |
| 8.0.x | ⚠️ 部分支持 | 85% |
| < 8.0 | ❌ 不支持 | - |

## 快速开始

### 1. 环境配置

```bash
# 设置连接字符串
export DATABASE_URI="postgresql://username:password@hostname:8000/database"

# 启用 GaussDB 兼容模式
export GAUSSDB_COMPATIBILITY_MODE="auto"

# 可选：启用基准测试功能
export BENCHMARK_ENABLED="true"
```

### 2. 基本使用

```bash
# 测试数据库连接
python scripts/validate_gaussdb_config.py

# 运行健康检查
curl -X POST http://localhost:8000/mcp/tools/analyze_db_health

# 分析查询执行计划
curl -X POST http://localhost:8000/mcp/tools/explain_query \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT * FROM users WHERE active = true"}'
```

### 3. Docker 部署

```bash
# 使用预配置的 Docker Compose
cp config/env.gaussdb.example .env.gaussdb
docker-compose -f docker-compose.gaussdb.yml up -d
```

## 核心概念

### 适配器模式

GaussDB 兼容性通过适配器模式实现，主要组件包括：

- **数据库检测器**：自动识别 GaussDB 实例
- **SQL 驱动适配器**：转换 PostgreSQL 查询为 GaussDB 兼容格式
- **健康检查适配器**：适配各种健康检查功能
- **基准测试工具**：集成性能测试功能

### 配置驱动

系统使用 YAML 配置文件管理不同 GaussDB 版本的兼容性差异：

```yaml
versions:
  "8.1.0":
    supports_hypopg: false
    supports_pg_stat_statements: true
    system_views:
      pg_stat_activity: "pg_stat_activity"
    query_adaptations:
      "EXPLAIN (ANALYZE, BUFFERS)": "EXPLAIN (ANALYZE true, BUFFERS true)"
```

### 回退机制

当 GaussDB 特定功能不可用时，系统会自动回退到 PostgreSQL 兼容的实现，确保功能的可用性。

## 使用场景

### 1. 数据库健康监控

定期检查 GaussDB 实例的健康状态，识别性能瓶颈和潜在问题：

```python
# 完整健康检查
result = await server.call_tool("analyze_db_health", {})

# 特定组件检查
index_health = await server.call_tool("analyze_db_health", {
    "component": "indexes"
})
```

### 2. 查询性能优化

分析慢查询并获得优化建议：

```python
# 获取慢查询列表
slow_queries = await server.call_tool("get_top_queries", {
    "limit": 10,
    "order_by": "total_time"
})

# 分析特定查询
explain_result = await server.call_tool("explain_query", {
    "query": "SELECT * FROM orders WHERE status = 'pending'",
    "analyze": True
})
```

### 3. 索引调优

基于实际工作负载生成索引建议：

```python
# 工作负载分析
recommendations = await server.call_tool("analyze_workload_indexes", {
    "hours": 24,
    "min_calls": 10
})

# 特定查询索引分析
query_indexes = await server.call_tool("analyze_query_indexes", {
    "query": "SELECT * FROM products WHERE category_id = $1"
})
```

### 4. 性能基准测试

运行标准化基准测试评估数据库性能：

```python
# Sysbench OLTP 测试
sysbench_result = await server.call_tool("gaussdb_benchmark", {
    "benchmark_type": "sysbench",
    "test_type": "oltp_read_write",
    "threads": 16,
    "time": 300
})

# TPC-C 基准测试
tpcc_result = await server.call_tool("gaussdb_benchmark", {
    "benchmark_type": "tpcc",
    "warehouses": 10,
    "duration": 600
})
```

## 故障排除

### 常见问题

1. **连接问题**：检查网络连接、端口配置和认证信息
2. **兼容性问题**：查看版本兼容性表，确认功能支持状态
3. **性能问题**：使用健康检查和基准测试工具诊断
4. **配置问题**：验证环境变量和配置文件设置

### 调试技巧

```bash
# 启用详细日志
export LOG_LEVEL=DEBUG
export GAUSSDB_DEBUG=true

# 验证配置
python scripts/validate_gaussdb_config.py

# 检查兼容性状态
curl -X POST http://localhost:8000/mcp/tools/gaussdb_compatibility_check
```

## 贡献指南

### 开发环境设置

```bash
# 克隆仓库
git clone <repository-url>
cd postgres-mcp-pro

# 安装依赖
pip install -r requirements.txt

# 运行测试
pytest tests/unit/gaussdb/
pytest tests/integration/test_gaussdb_*
```

### 扩展开发

参考 [架构设计和扩展开发指南](gaussdb-architecture-guide.md) 了解如何：

- 添加新的健康检查组件
- 实现自定义基准测试
- 扩展查询适配规则
- 创建新的 MCP 工具

## 支持和反馈

### 获取帮助

1. 查看相关文档章节
2. 检查系统日志获取详细错误信息
3. 在项目 GitHub 仓库提交 Issue
4. 参与社区讨论

### 报告问题

提交 Issue 时请包含：

- GaussDB 版本信息
- 错误日志和堆栈跟踪
- 重现步骤
- 环境配置信息

### 功能请求

欢迎提交功能请求和改进建议，请详细描述：

- 使用场景和需求
- 期望的功能行为
- 可能的实现方案

## 更新日志

### v1.0.0 (2024-01-15)
- 🎉 初始版本发布
- ✅ 基本 GaussDB 兼容性支持
- ✅ 健康检查功能
- ✅ 查询分析和索引调优
- ✅ 基准测试集成
- ✅ 完整文档和示例

### 未来版本计划

- **v1.1.0**：增强基准测试功能和报告
- **v1.2.0**：支持更多 GaussDB 特定优化
- **v2.0.0**：分布式 GaussDB 集群支持

---

**开始使用**：建议从 [GaussDB 连接配置指南](gaussdb-connection-guide.md) 开始，然后查看 [功能使用示例](gaussdb-usage-examples.md) 了解具体用法。

**深入了解**：查看 [API 参考文档](gaussdb-api-reference.md) 和 [架构设计指南](gaussdb-architecture-guide.md) 获取更多技术细节。