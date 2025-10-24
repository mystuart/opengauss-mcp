# openGauss MCP 测试指南

## 项目概述

openGauss MCP 是一个从 PostgreSQL MCP 迁移而来的数据库调优和分析工具，专门针对 openGauss 数据库进行了优化。该服务提供了全面的数据库性能分析、索引优化、健康监控等功能。

## 核心功能特性

### 🔍 数据库健康监控
- 连接健康检查
- 缓存命中率分析
- 复制延迟监控
- 约束验证
- 序列限制检查
- 清理健康状态

### ⚡ 索引优化
- 工作负载索引分析
- 查询特定索引推荐
- 虚拟索引支持
- 索引效益评估
- DTA (Database Tuning Advisor) 算法
- LLM 驱动的索引优化

### 📈 查询性能分析
- TOP 查询统计
- 资源使用指标
- 查询效率分析
- 执行计划解释
- 长时间运行查询监控
- 阻塞查询检测

### 🛡️ 安全 SQL 执行
- 只读模式支持
- SQL 解析安全检查
- 事务保护
- 权限控制

## 测试环境配置

### 1. 数据库准备

确保你有 openGauss 数据库的访问权限：

```bash
# 使用 docker 运行 openGauss (可选)
docker run --name opengauss \
  -e GS_PASSWORD=YourPassword123 \
  -p 15432:5432 \
  -d enmotech/opengauss:latest
```

### 2. 环境变量配置

创建 `.env` 文件：

```bash
# 数据库连接
DATABASE_URI=postgresql://username:password@localhost:15432/dbname

# LLM 优化 (可选)
OPENAI_API_KEY=your_openai_api_key_here
```

### 3. MCP 客户端配置

#### Claude Desktop 配置

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)：

```json
{
  "mcpServers": {
    "opengauss": {
      "command": "uv",
      "args": [
        "run",
        "opengauss-mcp",
        "--access-mode=unrestricted"
      ],
      "env": {
        "DATABASE_URI": "postgresql://username:password@localhost:15432/dbname",
        "OPENAI_API_KEY": "your_openai_api_key_here"
      }
    }
  }
}
```

#### Cursor 配置

在 MCP 设置中添加：

```json
{
  "opengauss": {
    "command": "opengauss-mcp",
    "args": ["--access-mode=unrestricted"],
    "env": {
      "DATABASE_URI": "postgresql://username:password@localhost:15432/dbname"
    }
  }
}
```

#### SSE 传输模式配置

启动 SSE 服务器：

```bash
docker run -p 8000:8000 \
  -e DATABASE_URI=postgresql://username:password@localhost:15432/dbname \
  opengauss-mcp --access-mode=unrestricted --transport=sse
```

客户端配置：

```json
{
  "mcpServers": {
    "opengauss": {
      "type": "sse",
      "url": "http://localhost:8000/sse"
    }
  }
}
```

## 功能测试用例

### 基础连接测试

**用户输入**：
```
检查数据库连接状态，告诉我数据库类型和可用功能
```

**预期响应**：
- 数据库类型：openGauss
- dbe_perf 可用性：True
- 虚拟索引支持：True
- 连接状态正常

### 模式探索测试

**用户输入**：
```
列出数据库中所有的模式，然后查看 public 模式中的表
```

**预期响应**：
- 模式列表：public, pg_catalog, information_schema 等
- 表列表：包含系统表和用户表的详细信息

### 健康检查测试

**用户输入**：
```
对数据库进行全面的健康检查，包括连接、缓存、索引等各个方面
```

**预期响应**：
- 连接健康报告
- 缓存命中率分析
- 索引健康状态
- 复制状态（如果有）
- 整体健康评分和建议

### 查询性能分析测试

**用户输入**：
```
分析数据库中运行最慢的查询，并提供优化建议
```

**预期响应**：
- TOP 查询列表
- 资源消耗统计
- 性能瓶颈识别
- 具体优化建议

### 索引优化测试

**用户输入**：
```
分析当前工作负载，推荐最优的索引配置来提升性能
```

**预期响应**：
- 工作负载分析结果
- 推荐的索引列表
- 预期性能提升
- 存储成本分析

### 虚拟索引测试

**用户输入**：
```
为表 pg_class 创建一个虚拟索引来测试 relname 字段的查询性能
```

**预期响应**：
- 虚拟索引创建结果
- 查询计划对比
- 性能提升评估

### 执行计划分析测试

**用户输入**：
```
解释这个查询的执行计划：SELECT * FROM pg_class WHERE relname = 'pg_class'
```

**预期响应**：
- 详细的执行计划
- 成本分析
- 潜在优化点
- 索引使用情况

## LLM 集成测试

### 基础对话测试

**用户输入**：
```
我的数据库响应很慢，帮我分析可能的原因并提供解决方案
```

**LLM 预期动作**：
1. 调用 `analyze_db_health` 工具检查整体健康状况
2. 调用 `get_top_queries` 工具分析慢查询
3. 调用 `analyze_workload_indexes` 工具检查索引优化空间
4. 综合分析结果，提供具体的优化建议

### 复杂优化场景测试

**用户输入**：
```
我们有一个电商系统，最近订单查询变得很慢。帮我分析订单相关的表结构，查询性能，并提供优化方案。
```

**LLM 预期动作**：
1. 调用 `list_schemas` 和 `list_objects` 了解表结构
2. 调用 `get_object_details` 分析订单表和索引
3. 调用 `get_top_queries` 找出订单相关的慢查询
4. 调用 `analyze_query_indexes` 为特定查询推荐索引
5. 调用 `explain_query` 验证优化效果
6. 提供完整的优化方案

### 实时监控测试

**用户输入**：
```
监控当前数据库的活动会话，看看是否有长时间运行的查询或阻塞情况
```

**LLM 预期动作**：
1. 调用 `get_detailed_session_info` 获取会话信息
2. 调用 `get_long_running_queries` 检查长时间运行查询
3. 调用 `get_blocked_queries` 检查阻塞情况
4. 分析结果并提供相应的处理建议

## 高级功能测试

### LLM 驱动的索引优化

**前提条件**：设置 `OPENAI_API_KEY` 环境变量

**用户输入**：
```
使用 LLM 优化功能来分析我的工作负载并提供索引建议
```

**LLM 预期动作**：
1. 调用 `analyze_workload_indexes` 工具，使用 `method="llm"`
2. LLM 分析数据库结构和查询模式
3. 通过多轮迭代优化索引配置
4. 提供最终的优化建议

### 综合性能报告

**用户输入**：
```
生成一份全面的数据库性能报告，包括所有关键指标和建议
```

**LLM 预期动作**：
1. 调用 `get_comprehensive_health_report` 获取综合健康报告
2. 调用各种分析工具收集性能数据
3. 整合所有信息，生成结构化的性能报告
4. 提供优先级排序的改进建议

## 故障排除指南

### 常见问题

1. **连接失败**
   ```
   错误：Database connection URL not provided
   解决：检查 DATABASE_URI 环境变量是否正确设置
   ```

2. **权限问题**
   ```
   错误：permission denied for relation
   解决：确保数据库用户有足够的权限访问相关表和视图
   ```

3. **扩展缺失**
   ```
   错误：dbe_perf.statement view is not available
   解决：确保 openGauss 的 dbe_perf 扩展已正确安装和配置
   ```

4. **虚拟索引不支持**
   ```
   错误：Virtual indexes are not supported
   解决：检查 openGauss 版本是否支持虚拟索引功能
   ```

### 调试技巧

1. **启用详细日志**：
   ```bash
   export OPENGAUSS_MCP_LOG_LEVEL=DEBUG
   ```

2. **测试数据库连接**：
   ```bash
   python -c "
   import asyncio
   from opengauss_mcp.sql.extension_utils import get_database_type
   from opengauss_mcp.sql import SqlDriver

   async def test():
       driver = SqlDriver('your_connection_string')
       db_type = await get_database_type(driver)
       print(f'Database type: {db_type}')

   asyncio.run(test())
   "
   ```

3. **检查 MCP 服务状态**：
   ```bash
   # 检查服务是否正常启动
   opengauss-mcp --help

   # 测试单个工具
   echo '{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "list_schemas"}, "id": 1}' | opengauss-mcp
   ```

## 性能基准测试

### 测试脚本

创建性能基准测试：

```python
import asyncio
import time
from opengauss_mcp.server import analyze_db_health, get_top_queries

async def benchmark():
    start_time = time.time()

    # 测试健康检查性能
    health_start = time.time()
    await analyze_db_health("connection")
    health_time = time.time() - health_start

    # 测试查询分析性能
    query_start = time.time()
    await get_top_queries(limit=10)
    query_time = time.time() - query_start

    total_time = time.time() - start_time

    print(f"Health check: {health_time:.2f}s")
    print(f"Query analysis: {query_time:.2f}s")
    print(f"Total time: {total_time:.2f}s")

if __name__ == "__main__":
    asyncio.run(benchmark())
```

## 总结

通过以上测试用例，你可以全面验证 openGauss MCP 服务的功能：

1. ✅ 基础连接和数据库识别
2. ✅ 模式和对象探索
3. ✅ 健康监控功能
4. ✅ 查询性能分析
5. ✅ 索引优化建议
6. ✅ 虚拟索引支持
7. ✅ LLM 集成优化
8. ✅ 实时监控能力

所有核心功能都已经从 PostgreSQL 成功迁移到 openGauss，并针对 openGauss 的特性进行了优化，特别是 dbe_perf 视图和虚拟索引功能的支持。