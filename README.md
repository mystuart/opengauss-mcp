<div align="center">

<img src="assets/opengauss-mcp.png" alt="OpenGauss MCP Logo" width="600"/>

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![PyPI - Version](https://img.shields.io/pypi/v/opengauss-mcp)](https://pypi.org/project/opengauss-mcp/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

<h3>专为 openGauss 数据库设计的智能 MCP 服务器，提供高级索引调优、执行计划分析、健康监控和智能优化功能。</h3>

<div class="toc">
  <a href="#概述">概述</a> •
  <a href="#特性">特性</a> •
  <a href="#快速开始">快速开始</a> •
  <a href="#安装">安装</a> •
  <a href="#配置">配置</a> •
  <a href="#使用方法">使用方法</a> •
  <a href="#mcp-服务器-api">MCP API</a> •
  <a href="#测试">测试</a> •
  <a href="#技术说明">技术说明</a>
</div>

</div>

## 概述

**OpenGauss MCP** 是一个专为 openGauss 数据库设计的强大模型上下文协议（MCP）服务器。通过迁移和增强 [PostgreSQL MCP Pro](https://github.com/crystaldba/postgres-mcp) 代码库构建，提供全面的数据库优化、监控和智能调优功能。

OpenGauss MCP 不仅仅提供简单的数据库连接，还提供针对 openGauss 独特功能的高级特性，包括 dbe_perf 性能视图和虚拟索引支持。

## 特性

### 🔍 高级数据库健康监控
- **连接健康监控**：监控活跃连接、空闲会话和连接池利用率
- **性能指标分析**：利用 openGauss 的 dbe_perf 视图进行全面性能分析
- **缓冲区缓存分析**：跟踪缓存命中率和 I/O 效率
- **复制健康监控**：监控复制延迟和同步状态
- **约束验证检查**：检查无效约束和数据完整性问题
- **序列健康监控**：监控序列使用情况并防止溢出场景
- **VACUUM 健康检查**：跟踪自动 VACUUM 性能并防止事务 ID 回卷

### ⚡ 智能索引优化
- **工作负载分析**：分析查询模式以识别性能瓶颈
- **DTA 算法**：数据库调优顾问算法，进行系统性索引优化
- **LLM 驱动优化**：使用高级推理的 AI 驱动索引推荐
- **虚拟索引支持**：测试索引性能而无需创建实际索引
- **成本效益分析**：平衡性能改进与存储成本
- **多列索引支持**：支持复杂的多列索引优化
- **纯 LLM 推荐**：基于 GLM-4.5-Flash 的快速智能索引建议

### 📈 查询性能分析
- **TOP 查询**：使用 dbe_perf.statement 识别资源密集型查询
- **资源指标**：全面分析 CPU、内存和 I/O 使用情况
- **查询效率**：按性能效率对查询进行排名并识别优化机会
- **长时间运行查询**：监控和长时间运行操作警报
- **阻塞查询检测**：检测和分析查询阻塞场景
- **会话监控**：实时会话活动跟踪

### 🧠 智能模式智能
- **模式发现**：自动检测和映射数据库对象
- **上下文感知 SQL**：基于详细模式理解生成优化 SQL
- **对象分析**：表、视图、索引和约束的详细信息
- **关系映射**：理解表关系和外键依赖

### 🛡️ 安全 SQL 执行
- **访问控制**：为不同环境配置可配置的访问模式
- **只读模式**：生产数据库的安全执行环境
- **SQL 解析**：高级 SQL 解析以防止不安全操作
- **事务安全**：受保护的事务管理和回滚功能

### 🚀 高性能架构
- **异步 I/O**：基于 psycopg3 构建以获得最佳性能
- **连接池**：高效的数据库连接管理
- **SSE 传输**：支持 Server-Sent Events 以实现可扩展部署
- **错误处理**：全面的错误处理和恢复机制

## 快速开始

### 前置条件

- openGauss 数据库（版本 3.0+）或 PostgreSQL 数据库（兼容模式）
- Python 3.12 或更高版本
- 具有适当权限的数据库凭据

### 安装

#### 选项 1：使用 pipx

```bash
pipx install opengauss-mcp
```

#### 选项 2：使用 uv

```bash
uv pip install opengauss-mcp
```

#### 选项 3：从源码安装

```bash
git clone https://github.com/mystuart/opengauss-mcp.git
cd opengauss-mcp
git checkout og
uv pip install -e .
```

## 配置

### 环境变量

设置以下环境变量：

```bash
# 必需：数据库连接
export DATABASE_URI="postgresql://username:password@localhost:15432/dbname"

# 可选：LLM 优化功能（使用智谱 AI）
export ZAI_API_KEY="your_zhipu_api_key_here"
```

### Claude Desktop 配置

添加到您的 Claude Desktop 配置文件：

```json
{
  "mcpServers": {
    "opengauss": {
      "command": "opengauss-mcp",
      "args": ["--access-mode=unrestricted"],
      "env": {
        "DATABASE_URI": "postgresql://username:password@localhost:15432/dbname",
        "ZAI_API_KEY": "your_zhipu_api_key_here"
      }
    }
  }
}
```

### SSE 传输模式

对于共享服务器部署：

```bash
# 启动 SSE 服务器
opengauss-mcp --access-mode=unrestricted --transport=sse --port=8000
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

## 使用方法

### 基本使用示例

**检查数据库健康**
```
对我的 openGauss 数据库进行全面健康检查
```

**分析慢查询**
```
我的数据库上运行最慢的查询是什么？我该如何优化它们？
```

**索引优化**
```
分析我的数据库工作负载并推荐索引以提高性能
```

**查询性能分析**
```
解释以下查询的执行计划：SELECT * FROM orders WHERE created_at > '2024-01-01'
```

### 高级使用

**LLM 驱动优化**
```
使用 AI 驱动的优化来分析我的复杂工作负载并建议索引改进
```

**纯 LLM 索引推荐**
```
使用基于 GLM-4.5-Flash 的智能索引分析来优化这些查询：
1. SELECT * FROM users WHERE email = 'test@example.com' AND status = 'active'
2. SELECT o.*, c.name FROM orders o JOIN customers c ON o.customer_id = c.id WHERE o.status = 'pending'
```

**虚拟索引测试**
```
在 orders(customer_id) 上创建虚拟索引并测试其性能影响
```

**实时监控**
```
显示活跃会话、长时间运行的查询以及任何阻塞情况
```

## MCP 服务器 API

OpenGauss MCP 通过模型上下文协议提供全面的工具：

### 核心工具

| 工具名称 | 描述 |
|-----------|-------------|
| `list_schemas` | 列出所有数据库模式 |
| `list_objects` | 列出模式中的对象（表、视图、索引） |
| `get_object_details` | 获取数据库对象的详细信息 |
| `execute_sql` | 使用安全控制执行 SQL 语句 |
| `explain_query` | 获取和分析查询执行计划 |

### 性能分析工具

| 工具名称 | 描述 |
|-----------|-------------|
| `get_top_queries` | 从 dbe_perf.statement 获取资源密集型查询 |
| `get_queries_with_resource_metrics` | 具有详细资源使用的查询 |
| `get_queries_by_resource_efficiency` | 按效率排名的查询 |
| `analyze_workload_indexes` | 全面工作负载索引分析 |
| `analyze_query_indexes` | 特定查询的索引分析 |
| `analyze_indexes_with_llm_only` | 🆕 纯 LLM 智能索引推荐（无需虚拟索引） |

### 健康监控工具

| 工具名称 | 描述 |
|-----------|-------------|
| `analyze_db_health` | 全面健康检查 |
| `get_detailed_session_info` | 活跃会话信息 |
| `get_long_running_queries` | 长时间运行查询检测 |
| `get_blocked_queries` | 阻塞查询分析 |
| `get_comprehensive_health_report` | 完整健康评估 |

### 虚拟索引工具

| 工具名称 | 描述 |
|-----------|-------------|
| `create_virtual_index` | 创建用于测试的虚拟索引 |
| `list_virtual_indexes` | 列出现有虚拟索引 |
| `drop_virtual_index` | 移除特定虚拟索引 |
| `drop_all_virtual_indexes` | 清理所有虚拟索引 |
| `estimate_index_benefit` | 估计索引的性能影响 |

### 监控工具

| 工具名称 | 描述 |
|-----------|-------------|
| `get_global_file_iostat` | 全局文件 I/O 统计 |
| `get_global_wait_events` | 全局等待事件分析 |

## 🆕 新增功能：纯 LLM 索引推荐

### `analyze_indexes_with_llm_only` 工具

这是一个专为快速智能索引优化设计的全新工具：

#### 特点
- **快速响应**：基于 GLM-4.5-Flash 模型，响应速度快
- **无需虚拟索引**：不依赖数据库虚拟索引功能
- **专家级建议**：提供专业的数据库优化建议
- **通用性强**：适用于任何 openGauss/PostgreSQL 数据库
- **免费使用**：基于免费的 GLM-4.5-Flash 模型

#### 使用场景
- 快速获得索引优化建议
- 不支持虚拟索引的数据库环境
- 需要专家级数据库调优建议
- 批量查询分析优化

#### 示例对话
```
用户：帮我分析这些 SQL 查询的索引优化：
1. SELECT * FROM users WHERE email = 'test@example.com' AND status = 'active'
2. SELECT o.*, c.name FROM orders o JOIN customers c ON o.customer_id = c.id WHERE o.status = 'pending'

LLM 助手：我来使用基于 GLM-4.5-Flash 的智能索引分析工具来分析您的查询。

[调用 analyze_indexes_with_llm_only 工具]

分析结果：
推荐创建以下索引：
1. CREATE INDEX ON users (email, status);
2. CREATE INDEX ON orders (status);
3. CREATE INDEX ON orders (customer_id);

这些索引将显著提高查询性能...
```

## 测试

### 运行测试

项目包含全面的测试套件：

```bash
# 运行测试脚本
python test_opengauss_mcp.py

# 设置数据库 URL
export DATABASE_URI="postgresql://user:pass@host:port/db"
python test_opengauss_mcp.py
```

### 测试覆盖范围

测试套件涵盖：
- ✅ 数据库连接和类型检测
- ✅ 基本 MCP 工具（模式、对象、执行计划）
- ✅ 查询分析工具
- ✅ 健康监控工具
- ✅ 虚拟索引功能
- ✅ 索引优化算法
- ✅ 性能监控工具
- ✅ 纯 LLM 索引推荐功能


## 技术说明

### openGauss 特定功能

此 MCP 服务器利用 openGauss 特定的功能：

- **dbe_perf 视图**：标准 PostgreSQL 中不可用的高级性能监控视图
- **虚拟索引**：测试索引性能而无存储开销
- **增强统计**：更详细的查询性能统计
- **优化算法**：针对 openGauss 查询优化器调优

### 从 PostgreSQL 迁移

此项目是从 PostgreSQL MCP Pro 成功迁移，具有以下增强：
- 适配所有查询以使用 openGauss 的 dbe_perf 视图
- 增强虚拟索引支持
- 改进 openGauss 特定功能的错误处理
- 添加 openGauss 特定健康检查
- 在可用时保持与 PostgreSQL 的完全兼容性

### GLM-4.5-Flash 集成

🆕 **智谱 AI 集成**：
- 使用官方 Zai SDK 与 GLM-4.5-Flash 模型集成
- 免费的高性能索引推荐
- 128K 上下文长度支持
- 智能错误处理和重试机制
- 专业的数据库优化知识库

### 性能优化

- **连接池**：高效的数据库连接管理
- **异步架构**：非阻塞 I/O 以获得最佳性能
- **智能缓存**：缓存频繁访问的元数据
- **批处理操作**：优化批量数据检索

## 需求和兼容性

### 数据库需求

- **openGauss**：版本 3.0+（完整功能支持）
- **PostgreSQL**：版本 13+（兼容模式，某些功能受限）

### Python 需求

- Python 3.12+
- psycopg[binary] >= 3.2.6
- mcp[cli] >= 1.5.0
- zai-sdk >= 0.0.4.1（用于 LLM 功能）
- pyproject.toml 中的其他依赖项

### 扩展

为了完整功能，确保这些扩展可用：
- `dbe_perf`（openGauss 内置）
- 虚拟索引支持（openGauss 内置）

## 贡献

欢迎贡献！请：

1. Fork 仓库
2. 创建功能分支
3. 为新功能添加测试
4. 确保所有测试通过
5. 提交 Pull Request

## 许可证

MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 支持

对于问题和疑问：
- 在 GitHub 上创建 issue
- 查看全面的测试套件以获取使用示例