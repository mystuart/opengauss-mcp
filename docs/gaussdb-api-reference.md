# GaussDB API 参考文档

## 概述

本文档提供了 Postgres MCP Pro 服务器中 GaussDB 兼容性功能的完整 API 参考。所有 API 都支持标准的 MCP (Model Context Protocol) 调用格式。

## 核心 API

### 1. 数据库健康检查 API

#### `analyze_db_health`

分析 GaussDB 数据库的整体健康状况。

**参数：**
```json
{
  "component": "string, optional",  // 指定检查组件: "indexes", "connections", "buffers", "vacuum", "sequences", "replication", "constraints"
  "detailed": "boolean, optional",  // 是否返回详细信息，默认 false
  "include_recommendations": "boolean, optional"  // 是否包含优化建议，默认 true
}
```

**返回值：**
```json
{
  "database_type": "gaussdb",
  "database_version": "8.1.0",
  "overall_health": "good|warning|critical",
  "components": {
    "indexes": {
      "status": "good|warning|critical",
      "invalid_indexes": 0,
      "unused_indexes": 2,
      "duplicate_indexes": 0,
      "recommendations": ["建议删除未使用的索引: idx_unused_1"]
    },
    "connections": {
      "status": "good",
      "active_connections": 15,
      "max_connections": 100,
      "connection_utilization": 0.15
    },
    "buffers": {
      "status": "good",
      "hit_ratio": 0.98,
      "shared_buffers_usage": 0.75
    }
  },
  "recommendations": [
    "考虑删除未使用的索引以节省存储空间",
    "连接数使用率正常，无需调整"
  ]
}
```

**示例调用：**
```bash
curl -X POST http://localhost:8000/mcp/tools/analyze_db_health \
  -H "Content-Type: application/json" \
  -d '{"component": "indexes", "detailed": true}'
```

### 2. 查询执行计划 API

#### `explain_query`

分析 GaussDB 查询的执行计划。

**参数：**
```json
{
  "query": "string, required",      // 要分析的 SQL 查询
  "analyze": "boolean, optional",   // 是否执行 EXPLAIN ANALYZE，默认 false
  "buffers": "boolean, optional",   // 是否包含缓冲区信息，默认 false
  "format": "string, optional"      // 输出格式: "text", "json", "xml", "yaml"，默认 "text"
}
```

**返回值：**
```json
{
  "query": "SELECT * FROM users WHERE age > 25",
  "execution_plan": "Seq Scan on users  (cost=0.00..431.00 rows=143 width=68)",
  "analysis": {
    "total_cost": 431.00,
    "estimated_rows": 143,
    "actual_time": 12.5,
    "actual_rows": 142,
    "buffers_hit": 25,
    "buffers_read": 5
  },
  "recommendations": [
    "考虑在 age 列上创建索引以提高查询性能",
    "当前查询使用全表扫描，可能影响性能"
  ],
  "gaussdb_specific": {
    "optimizer_version": "8.1.0",
    "plan_cache_hit": true
  }
}
```

### 3. 索引调优 API

#### `analyze_workload_indexes`

分析工作负载并提供索引优化建议。

**参数：**
```json
{
  "hours": "integer, optional",        // 分析时间范围（小时），默认 24
  "min_calls": "integer, optional",    // 最小执行次数，默认 5
  "min_total_time": "number, optional", // 最小总执行时间（毫秒），默认 1000
  "schema": "string, optional",        // 指定模式名，默认 public
  "include_hypothetical": "boolean, optional" // 是否包含假设索引分析，默认 true
}
```

**返回值：**
```json
{
  "analysis_period": {
    "start_time": "2024-01-15T10:00:00Z",
    "end_time": "2024-01-16T10:00:00Z",
    "total_queries": 1250
  },
  "recommendations": [
    {
      "priority": "high",
      "table": "users",
      "columns": ["email", "status"],
      "index_type": "btree",
      "estimated_benefit": {
        "queries_affected": 45,
        "time_saved_ms": 15000,
        "cost_reduction": 0.75
      },
      "create_statement": "CREATE INDEX idx_users_email_status ON users (email, status);",
      "rationale": "该索引将显著提高用户查询的性能"
    }
  ],
  "existing_indexes": [
    {
      "table": "users",
      "index": "idx_users_id",
      "usage_stats": {
        "scans": 1200,
        "tuples_read": 45000,
        "tuples_fetched": 1200
      },
      "recommendation": "keep"
    }
  ],
  "gaussdb_compatibility": {
    "hypopg_available": false,
    "alternative_analysis": "使用基于统计信息的分析方法"
  }
}
```

#### `analyze_query_indexes`

分析特定查询的索引需求。

**参数：**
```json
{
  "query": "string, required",         // 要分析的查询
  "explain_analyze": "boolean, optional", // 是否执行实际分析，默认 false
  "suggest_hypothetical": "boolean, optional" // 是否建议假设索引，默认 true
}
```

### 4. 基准测试 API

#### `gaussdb_benchmark`

在 GaussDB 上运行基准测试。

**参数：**
```json
{
  "benchmark_type": "string, required", // "sysbench" 或 "tpcc"
  "test_type": "string, optional",      // sysbench 测试类型，默认 "oltp_read_write"
  "tables": "integer, optional",        // 表数量，默认 10
  "table_size": "integer, optional",    // 每表行数，默认 100000
  "threads": "integer, optional",       // 并发线程数，默认 16
  "time": "integer, optional",          // 测试时间（秒），默认 300
  "warehouses": "integer, optional",    // TPC-C 仓库数，默认 10
  "connections": "integer, optional",   // TPC-C 连接数，默认 20
  "duration": "integer, optional",      // TPC-C 持续时间（秒），默认 600
  "ramp_up": "integer, optional"        // TPC-C 预热时间（秒），默认 60
}
```

**返回值：**
```json
{
  "benchmark_type": "sysbench",
  "test_configuration": {
    "test_type": "oltp_read_write",
    "tables": 10,
    "table_size": 100000,
    "threads": 16,
    "duration": 300
  },
  "results": {
    "transactions_per_second": 1250.5,
    "queries_per_second": 22509.0,
    "latency": {
      "min": 2.1,
      "avg": 12.8,
      "max": 45.2,
      "95th_percentile": 25.3
    },
    "errors": 0,
    "reconnects": 0
  },
  "database_metrics": {
    "cpu_usage": 0.65,
    "memory_usage": 0.78,
    "io_read_mb": 125.5,
    "io_write_mb": 89.2,
    "connections_used": 16
  },
  "recommendations": [
    "性能表现良好，TPS 超过预期",
    "考虑增加 shared_buffers 以进一步提升性能"
  ]
}
```

### 5. 查询统计 API

#### `get_top_queries`

获取 GaussDB 的慢查询统计信息。

**参数：**
```json
{
  "limit": "integer, optional",        // 返回查询数量，默认 20
  "order_by": "string, optional",      // 排序字段: "total_time", "mean_time", "calls"，默认 "total_time"
  "min_calls": "integer, optional",    // 最小执行次数过滤，默认 1
  "schema": "string, optional"         // 指定模式名
}
```

**返回值：**
```json
{
  "total_queries": 156,
  "analysis_period": "24 hours",
  "queries": [
    {
      "query": "SELECT u.name, p.title FROM users u JOIN posts p ON u.id = p.user_id WHERE u.active = $1",
      "calls": 1250,
      "total_time": 45000.5,
      "mean_time": 36.0,
      "min_time": 12.1,
      "max_time": 156.8,
      "stddev_time": 15.2,
      "rows": 125000,
      "shared_blks_hit": 45000,
      "shared_blks_read": 1200,
      "temp_blks_read": 0,
      "temp_blks_written": 0
    }
  ],
  "gaussdb_compatibility": {
    "pg_stat_statements_available": true,
    "version": "8.1.0"
  }
}
```

## GaussDB 特定 API

### 1. 兼容性检查 API

#### `gaussdb_compatibility_check`

检查 GaussDB 实例的兼容性状态。

**参数：**
```json
{
  "check_features": "boolean, optional",    // 是否检查功能可用性，默认 true
  "check_extensions": "boolean, optional",  // 是否检查扩展，默认 true
  "detailed": "boolean, optional"           // 是否返回详细信息，默认 false
}
```

**返回值：**
```json
{
  "database_info": {
    "type": "gaussdb",
    "version": "8.1.0",
    "build_info": "GaussDB Kernel V500R002C00",
    "compatibility_mode": "auto"
  },
  "feature_availability": {
    "pg_stat_statements": true,
    "hypopg": false,
    "explain_analyze": true,
    "query_optimization": true,
    "benchmark_tools": true
  },
  "extensions": {
    "available": ["pg_stat_statements", "btree_gin", "btree_gist"],
    "missing": ["hypopg"],
    "recommendations": [
      "hypopg 扩展不可用，将使用替代的索引分析方法"
    ]
  },
  "system_views": {
    "pg_stat_activity": "available",
    "pg_stat_database": "available",
    "pg_stat_user_tables": "available",
    "pg_stat_user_indexes": "available"
  },
  "compatibility_status": "good",
  "warnings": [],
  "recommendations": [
    "所有核心功能都可用",
    "建议启用查询统计收集以获得更好的分析结果"
  ]
}
```

### 2. 配置管理 API

#### `get_gaussdb_config`

获取当前的 GaussDB 兼容性配置。

**返回值：**
```json
{
  "version": "8.1.0",
  "compatibility_mode": "auto",
  "features": {
    "supports_hypopg": false,
    "supports_pg_stat_statements": true,
    "supports_explain_analyze": true
  },
  "system_views_mapping": {
    "pg_stat_user_indexes": "pg_stat_user_indexes",
    "pg_stat_user_tables": "pg_stat_user_tables"
  },
  "query_adaptations": {
    "enabled": true,
    "cache_size": 1000
  },
  "benchmark_config": {
    "sysbench_enabled": true,
    "tpcc_enabled": true,
    "default_threads": 16
  }
}
```

## 错误处理

### 错误响应格式

所有 API 在出错时返回统一的错误格式：

```json
{
  "error": {
    "code": "GAUSSDB_CONNECTION_ERROR",
    "message": "无法连接到 GaussDB 实例",
    "details": {
      "original_error": "connection to server at \"localhost\" (127.0.0.1), port 8000 failed",
      "suggestions": [
        "检查 GaussDB 服务是否运行",
        "验证连接参数是否正确",
        "确认网络连接正常"
      ]
    },
    "timestamp": "2024-01-15T10:30:00Z"
  }
}
```

### 常见错误代码

| 错误代码 | 描述 | 解决建议 |
|---------|------|----------|
| `GAUSSDB_CONNECTION_ERROR` | 连接失败 | 检查连接参数和网络 |
| `GAUSSDB_AUTHENTICATION_ERROR` | 认证失败 | 验证用户名和密码 |
| `GAUSSDB_FEATURE_NOT_SUPPORTED` | 功能不支持 | 使用替代方案或升级版本 |
| `GAUSSDB_QUERY_SYNTAX_ERROR` | 查询语法错误 | 检查查询语法或查看适配日志 |
| `GAUSSDB_PERMISSION_DENIED` | 权限不足 | 检查用户权限设置 |
| `GAUSSDB_BENCHMARK_ERROR` | 基准测试失败 | 检查测试工具安装和配置 |

## 认证和安全

### API 认证

如果启用了认证，需要在请求头中包含认证信息：

```bash
curl -X POST http://localhost:8000/mcp/tools/analyze_db_health \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-token" \
  -d '{}'
```

### 权限要求

不同 API 需要的最小数据库权限：

| API | 所需权限 |
|-----|----------|
| `analyze_db_health` | SELECT on system views |
| `explain_query` | SELECT on target tables |
| `analyze_workload_indexes` | SELECT on pg_stat_statements |
| `gaussdb_benchmark` | CREATE, INSERT, UPDATE, DELETE |
| `get_top_queries` | SELECT on pg_stat_statements |

## 限制和配额

### 请求限制

- 每分钟最多 100 个 API 请求
- 基准测试 API 每小时最多 5 次调用
- 单个查询分析最大查询长度：10KB

### 资源限制

- 工作负载分析最多分析过去 7 天的数据
- 索引建议最多返回 50 个建议
- 查询统计最多返回 1000 条记录

## 版本兼容性

### 支持的 GaussDB 版本

| GaussDB 版本 | 支持状态 | 功能限制 |
|-------------|----------|----------|
| 8.1.0+ | 完全支持 | 无 |
| 8.0.x | 部分支持 | 不支持某些高级功能 |
| < 8.0 | 不支持 | 建议升级 |

### API 版本

当前 API 版本：`v1.0`

版本信息可通过以下方式获取：
```bash
curl http://localhost:8000/mcp/version
```

## 示例和最佳实践

### 批量操作示例

```python
import asyncio
import aiohttp

async def batch_health_check():
    """批量执行健康检查"""
    components = ["indexes", "connections", "buffers", "vacuum"]
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for component in components:
            task = session.post(
                "http://localhost:8000/mcp/tools/analyze_db_health",
                json={"component": component}
            )
            tasks.append(task)
        
        responses = await asyncio.gather(*tasks)
        
        for i, response in enumerate(responses):
            result = await response.json()
            print(f"{components[i]} 健康状态: {result}")

asyncio.run(batch_health_check())
```

### 性能监控示例

```python
async def performance_monitoring():
    """性能监控示例"""
    # 1. 获取慢查询
    slow_queries = await call_api("get_top_queries", {
        "limit": 10,
        "order_by": "total_time"
    })
    
    # 2. 分析每个慢查询
    for query in slow_queries["queries"]:
        explain_result = await call_api("explain_query", {
            "query": query["query"],
            "analyze": True
        })
        
        # 3. 获取索引建议
        index_suggestions = await call_api("analyze_query_indexes", {
            "query": query["query"]
        })
        
        print(f"查询: {query['query'][:50]}...")
        print(f"执行计划: {explain_result['execution_plan']}")
        print(f"索引建议: {index_suggestions['recommendations']}")
```

## 更新日志

### v1.0.0 (2024-01-15)
- 初始版本发布
- 支持基本的 GaussDB 兼容性功能
- 包含健康检查、查询分析、索引调优和基准测试 API

### 未来版本计划
- v1.1.0: 增强的基准测试功能
- v1.2.0: 更多 GaussDB 特定优化
- v2.0.0: 支持分布式 GaussDB 集群