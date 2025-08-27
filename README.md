<h3>支持索引调优、执行计划分析、健康检查和安全 SQL 执行的 openGauss MCP 服务器</h3>

<div class="toc">
  <a href="#概述">概述</a> •
  <a href="#演示">演示</a> •
  <a href="#快速开始">快速开始</a> •
  <a href="#技术说明">技术说明</a> •
  <a href="#mcp-服务器-api">MCP API</a> •
  <a href="#相关项目">相关项目</a> •
  <a href="#常见问题">常见问题</a>
</div>

</div>

## 概述

**openGauss MCP** 是一个开源的模型上下文协议 (MCP) 服务器，专为 openGauss 数据库设计，旨在支持您和您的 AI 代理完成**整个开发过程**——从初始编码、测试和部署，到生产调优和维护。

openGauss MCP 不仅仅是数据库连接的包装器。

主要功能包括：

- **🔍 数据库健康检查** - 分析索引健康状况、连接利用率、缓冲区缓存、VACUUM 健康状况、序列限制、复制延迟等。
- **⚡ 索引调优** - 使用工业级算法探索数千种可能的索引，为工作负载找到最佳解决方案。
- **📈 查询计划分析** - 通过检查 EXPLAIN 计划和模拟假设索引的影响来验证和优化性能。
- **🧠 模式智能** - 基于对数据库模式的详细理解进行上下文感知的 SQL 生成。
- **🛡️ 安全 SQL 执行** - 可配置的访问控制，包括支持只读模式和安全 SQL 解析，使其适用于开发和生产环境。

openGauss MCP 支持[标准输入/输出 (stdio)](https://modelcontextprotocol.io/docs/concepts/transports#standard-input%2Foutput-stdio)和[服务器发送事件 (SSE)](https://modelcontextprotocol.io/docs/concepts/transports#server-sent-events-sse)传输，在不同环境中具有灵活性。

### openGauss 专精设计

本项目基于原版的 [Crystal DBA Postgres MCP Pro](https://github.com/crystaldba/postgres-mcp) 项目，进行了深度改造以专精支持 openGauss 数据库。通过适配器模式实现了对 openGauss 的全面支持，包括其特有的性能特性和系统视图。

### 开发说明

⚠️ **注意**: 本项目在开发过程中使用了 Vibe Coding 方法，可能会存在一些错误。我们正在持续验证和修复中发现的问题。

## 演示

*从无法使用到极速运行*
- **挑战**: 我们使用 AI 助手生成了一个电影应用，但 SQLAlchemy ORM 代码运行极其缓慢。
- **解决方案**: 使用 openGauss MCP 与 Cursor，我们在几分钟内修复了性能问题。

我们的工作：
- 🚀 修复性能问题 - 包括 ORM 查询、索引和缓存
- 🛠️ 修复损坏的页面 - 通过提示代理探索数据、修复查询并添加相关内容
- 🧠 改进热门电影 - 通过探索数据并修复 ORM 查询以呈现更相关的结果

## 快速开始

### 前置要求

在开始之前，请确保您具备：
1. 数据库的访问凭据。
2. Docker *或* Python 3.12 或更高版本。

#### 访问凭据
您可以使用 `psql` 或 [pgAdmin](https://www.pgadmin.org/) 等 GUI 工具确认您的访问凭据是否有效。

#### Docker 或 Python

选择使用 Docker 还是 Python 由您决定。
我们通常推荐 Docker，因为 Python 用户可能会遇到更多环境特定的问题。
但是，使用您最熟悉的方法通常更有意义。

### 安装

选择以下方法之一安装 openGauss MCP：

#### 选项 1: 使用 Docker

拉取 openGauss MCP MCP 服务器 Docker 镜像。
此镜像包含所有必要的依赖项，为在各种环境中运行 openGauss MCP 提供了可靠的方式。

```bash
docker pull crystaldba/postgres-mcp
```

#### 选项 2: 使用 Python

如果您已安装 `pipx`，可以使用以下命令安装 openGauss MCP：

```bash
pipx install postgres-mcp
```

否则，使用 `uv` 安装 openGauss MCP：

```bash
uv pip install postgres-mcp
```

如果您需要安装 `uv`，请参阅 [uv 安装说明](https://docs.astral.sh/uv/getting-started/installation/)。

### 配置您的 AI 助手

我们提供了在 Claude Desktop 中配置 openGauss MCP 的完整说明。
许多 MCP 客户端具有类似的配置文件，您可以调整这些步骤以适用于您选择的客户端。

#### Claude Desktop 配置

您需要编辑 Claude Desktop 配置文件以添加 openGauss MCP。
此文件的位置取决于您的操作系统：
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%/Claude/claude_desktop_config.json`

您也可以使用 Claude Desktop 中的 `Settings` 菜单项来定位配置文件。

您现在将编辑配置文件的 `mcpServers` 部分。

##### 如果您使用 Docker

```json
{
  "mcpServers": {
    "postgres": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "DATABASE_URI",
        "crystaldba/postgres-mcp",
        "--access-mode=unrestricted"
      ],
      "env": {
        "DATABASE_URI": "postgresql://username:password@localhost:5432/dbname"
      }
    }
  }
}
```

openGauss MCP Docker 镜像将自动重新映射主机名 `localhost` 以从容器内部工作。

- macOS/Windows: 自动使用 `host.docker.internal`
- Linux: 自动使用 `172.17.0.1` 或适当的主机地址

##### 如果您使用 `pipx`

```json
{
  "mcpServers": {
    "postgres": {
      "command": "postgres-mcp",
      "args": [
        "--access-mode=unrestricted"
      ],
      "env": {
        "DATABASE_URI": "postgresql://username:password@localhost:5432/dbname"
      }
    }
  }
}
```

##### 如果您使用 `uv`

```json
{
  "mcpServers": {
    "postgres": {
      "command": "uv",
      "args": [
        "run",
        "postgres-mcp",
        "--access-mode=unrestricted"
      ],
      "env": {
        "DATABASE_URI": "postgresql://username:password@localhost:5432/dbname"
      }
    }
  }
}
```

##### 连接 URI

将 `postgresql://...` 替换为您的 [openGauss 数据库连接 URI](https://opengauss.org/zh/docs/3.0.0/docs/DevelopGuide/%E8%BF%9E%E6%8E%A5%E5%AD%97%E7%AC%A6%E4%B8%B2.html)。

##### 访问模式

openGauss MCP 支持多种*访问模式*，让您可以控制 AI 代理可以在数据库上执行的操作：
- **无限制模式**: 允许完全的读/写访问以修改数据和模式。适用于开发环境。
- **受限模式**: 将操作限制为只读事务，并对资源利用施加约束（目前仅执行时间）。适用于生产环境。

要使用受限模式，请将上述配置示例中的 `--access-mode=unrestricted` 替换为 `--access-mode=restricted`。

#### 其他 MCP 客户端

许多 MCP 客户端具有与 Claude Desktop 类似的配置文件，您可以调整上述示例以适用于您选择的客户端。

- 如果您使用 Cursor，可以从 `Command Palette` 导航到 `Cursor Settings`，然后打开 `MCP` 选项卡访问配置文件。
- 如果您使用 Windsurf，可以从 `Command Palette` 导航到 `Open Windsurf Settings Page` 以访问配置文件。
- 如果您使用 Goose，请运行 `goose configure`，然后选择 `Add Extension`。

## SSE 传输

openGauss MCP 支持 [SSE 传输](https://modelcontextprotocol.io/docs/concepts/transports#server-sent-events-sse)，允许多个 MCP 客户端共享一个服务器，可能是远程服务器。
要使用 SSE 传输，您需要使用 `--transport=sse` 选项启动服务器。

例如，使用 Docker 运行：

```bash
docker run -p 8000:8000 \
  -e DATABASE_URI=postgresql://username:password@localhost:5432/dbname \
  crystaldba/postgres-mcp --access-mode=unrestricted --transport=sse
```

然后更新您的 MCP 客户端配置以调用 MCP 服务器。
例如，在 Cursor 的 `mcp.json` 或 Cline 的 `cline_mcp_settings.json` 中，您可以输入：

```json
{
    "mcpServers": {
        "postgres": {
            "type": "sse",
            "url": "http://localhost:8000/sse"
        }
    }
}
```

对于 Windsurf，`mcp_config.json` 中的格式略有不同：

```json
{
    "mcpServers": {
        "postgres": {
            "type": "sse",
            "serverUrl": "http://localhost:8000/sse"
        }
    }
}
```

## Postgres 扩展安装（可选）

要启用索引调优和综合性能分析，您需要在数据库上加载 `pg_statements` 和 `hypopg` 扩展。

- `pg_statements` 扩展允许 openGauss MCP 分析查询执行统计信息。
例如，这使它能够理解哪些查询运行缓慢或消耗大量资源。
- `hypopg` 扩展允许 openGauss MCP 模拟添加索引后 openGauss 查询规划器的行为。

### 在 AWS RDS、Azure SQL 或 Google Cloud SQL 上安装扩展

如果您的 openGauss 数据库在云提供商托管服务上运行，`pg_statements` 和 `hypopg` 扩展应该已经在系统上可用。
在这种情况下，您只需使用具有足够权限的角色运行 `CREATE EXTENSION` 命令：

```sql
CREATE EXTENSION IF NOT EXISTS pg_statements;
CREATE EXTENSION IF NOT EXISTS hypopg;
```

### 在自管理的 Postgres 上安装扩展

如果您管理自己的 openGauss 安装，您可能需要做额外的工作。
在加载 `pg_statements` 扩展之前，您必须确保它列在 openGauss 配置文件的 `shared_preload_libraries` 中。
`hypopg` 扩展也可能需要额外的系统级安装（例如，通过您的包管理器），因为它并不总是随 openGauss 一起提供。

## 使用示例

### 获取数据库健康概览

询问：
> 检查我的数据库健康状况并识别任何问题。

### 分析慢查询

询问：
> 我的数据库中最慢的查询是什么？我该如何加快它们的速度？

### 获取加速建议

询问：
> 我的应用程序很慢。我该如何让它更快？

### 生成索引建议

询问：
> 分析我的数据库工作负载并建议索引以改善性能。

### 优化特定查询

询问：
> 帮我优化这个查询：SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id WHERE orders.created_at > '2023-01-01';

## MCP 服务器 API

[MCP 标准](https://modelcontextprotocol.io/) 定义了各种类型的端点：工具、资源、提示等。

openGauss MCP 仅通过 [MCP 工具](https://modelcontextprotocol.io/docs/concepts/tools) 提供功能。
我们选择这种方法是因为 [MCP 客户端生态系统](https://modelcontextprotocol.io/clients) 对 MCP 工具有广泛的支持。
这与其他 Postgres/openGauss MCP 服务器（包括[参考 PostgreSQL MCP 服务器](https://github.com/modelcontextprotocol/servers/tree/main/src/postgres)）的方法形成对比，后者使用 [MCP 资源](https://modelcontextprotocol.io/docs/concepts/resources) 来公开模式信息。

openGauss MCP 工具：

| 工具名称 | 描述 |
|-----------|-------------|
| `list_schemas` | 列出 openGauss 实例中所有可用的数据库模式。 |
| `list_objects` | 列出指定模式中的数据库对象（表、视图、序列、扩展）。 |
| `get_object_details` | 提供特定数据库对象的信息，例如表的列、约束和索引。 |
| `execute_sql` | 在数据库上执行 SQL 语句，在受限模式下连接时具有只读限制。 |
| `explain_query` | 获取 SQL 查询的执行计划，描述 openGauss 将如何处理它并公开查询规划器的成本模型。可以使用假设索引调用以模拟添加索引后的行为。 |
| `get_top_queries` | 基于 `pg_stat_statements` 数据报告按总执行时间计算的最慢 SQL 查询。 |
| `analyze_workload_indexes` | 分析数据库工作负载以识别资源密集型查询，然后为它们推荐最佳索引。 |
| `analyze_query_indexes` | 分析特定 SQL 查询列表（最多 10 个）并推荐最佳索引。 |
| `analyze_db_health` | 执行全面的健康检查，包括：缓冲区缓存命中率、连接健康、约束验证、索引健康（重复/未使用/无效）、序列限制和 VACUUM 健康状况。 |

## 相关项目

**Postgres/openGauss MCP 服务器**
- [Query MCP](https://github.com/alexander-zuev/supabase-mcp-server)。用于 Supabase Postgres 的 MCP 服务器，具有三层安全架构和 Supabase 管理 API 支持。
- [PG-MCP](https://github.com/stuzero/pg-mcp-server)。用于 PostgreSQL 的 MCP 服务器，具有灵活的连接选项、执行计划、扩展上下文等。
- [参考 PostgreSQL MCP 服务器](https://github.com/modelcontextprotocol/servers/tree/main/src/postgres)。一个简单的 MCP 服务器实现，将模式信息作为 MCP 资源公开并执行只读查询。
- [Supabase Postgres MCP 服务器](https://github.com/supabase-community/supabase-mcp)。此 MCP 服务器提供 Supabase 管理功能，并由 Supabase 社区积极维护。
- [Nile MCP 服务器](https://github.com/niledatabase/nile-mcp-server)。提供对 Nile 多租户 Postgres 服务管理 API 访问的 MCP 服务器。
- [Neon MCP 服务器](https://github.com/neondatabase-labs/mcp-server-neon)。提供对 Neon 无服务器 Postgres 服务管理 API 访问的 MCP 服务器。
- [Wren MCP 服务器](https://github.com/Canner/wren-engine)。为 Postgres 和其他数据库提供商业智能的语义引擎。

**DBA 工具（包括商业产品）**
- [Aiven Database Optimizer](https://aiven.io/solutions/aiven-ai-database-optimizer)。提供全面的数据库工作负载分析、查询优化和其他性能改进的工具。
- [dba.ai](https://www.dba.ai/)。与 GitHub 集成以解决代码问题的 AI 驱动数据库管理助手。
- [pgAnalyze](https://pganalyze.com/)。用于识别性能瓶颈、优化查询和实时警报的综合监控和分析平台。
- [Postgres.ai](https://postgres.ai/)。结合广泛的 Postgres 知识库和 GPT-4 的交互式聊天体验。
- [Xata Agent](https://github.com/xataio/agent)。开源 AI 代理，自动监控数据库健康状况，诊断问题并使用 LLM 驱动的推理和手册提供建议。

**Postgres 实用工具**
- [Dexter](https://github.com/DexterDB/dexter)。用于在 PostgreSQL 上生成和测试假设索引的工具。
- [PgHero](https://github.com/ankane/pghero)。Postgres 的性能仪表板，带有建议。
openGauss MCP 包含来自 PgHero 的健康检查。
- [PgTune](https://github.com/le0pard/pgtune?tab=readme-ov-file)。用于调整 Postgres 配置的启发式方法。

## 常见问题

*openGauss MCP 与其他 Postgres/openGauss MCP 服务器有何不同？*
有许多 MCP 服务器允许 AI 代理对 openGauss 数据库运行查询。
openGauss MCP 也可以做到这一点，但还添加了用于理解和改善 openGauss 数据库性能的工具。
例如，它实现了 [Microsoft SQL Server 数据库调优顾问的随时算法](https://www.microsoft.com/en-us/research/wp-content/uploads/2020/06/Anytime-Algorithm-of-Database-Tuning-Advisor-for-Microsoft-SQL-Server.pdf) 的版本，这是一个用于自动索引调优的现代工业级算法。

| openGauss MCP | 其他 Postgres/openGauss MCP 服务器 |
|--------------|----------------------------|
| ✅ 确定性的数据库健康检查 | ❌ 不可重复的 LLM 生成健康查询 |
| ✅ 有原则的索引搜索策略 | ❌ 生成式 AI 对索引改进的猜测 |
| ✅ 工作负载分析以找到主要问题 | ❌ 不一致的问题分析 |
| ✅ 模拟性能改进 | ❌ 自己尝试看看是否有效 |

openGauss MCP 通过添加确定性工具和经典优化算法来补充生成式 AI
这种组合既可靠又灵活。

*当 LLM 可以推理、生成 SQL 等时，为什么需要 MCP 工具？*
LLM 对于涉及模糊性、推理或自然语言的任务非常宝贵。
然而，与过程代码相比，它们可能很慢、昂贵、不确定，有时会产生不可靠的结果。
在数据库调优的情况下，我们有经过数十年发展的完善算法，被证明是有效的。
openGauss MCP 让您通过将 LLM 与经典优化算法和其他过程工具配对来结合两者的优势。

*您如何测试 openGauss MCP？*
测试对于确保 openGauss MCP 的可靠性和准确性至关重要。
我们正在构建一套 AI 生成的对抗性工作负载，旨在挑战 openGauss MCP 并确保其在各种场景下表现良好。

*支持哪些 openGauss 版本？*
我们目前的测试侧重于 openGauss 3.0、5.0 和最新版本。
我们计划支持 openGauss 2.0 及以上版本。

*谁创建了此项目？*
此项目基于 [Crystal DBA](https://www.crystaldba.ai/) 的开源项目创建，并由我们进行了 openGauss 专精改造。

## 路线图

*TBD*

您的需求是我们构建内容的关键驱动因素。
通过打开 [issue](https://github.com/crystaldba/postgres-mcp/issues) 或 [pull request](https://github.com/crystaldba/postgres-mcp/pulls) 告诉我们您希望看到什么。

## 技术说明

本节包括影响 openGauss MCP 设计的技术考虑因素的高级概述。

### 索引调优

开发人员知道缺失索引是数据库性能问题最常见的原因之一。
索引提供访问方法，允许 openGauss 快速定位执行查询所需的数据。
当表很小时，索引几乎没有区别，但随着数据大小的增长，表扫描和索引查找之间的算法复杂性差异变得显著（通常是 *O*(*n*) vs *O*(*log* *n*)，如果涉及多个表的连接，可能会更多）。

在 openGauss MCP 中生成建议索引的过程分为几个阶段：

1. *识别需要调优的 SQL 查询*。
    如果您知道特定 SQL 查询存在问题，您可以提供它。
    openGauss MCP 也可以分析工作负载以识别索引调优目标。
    为此，它依赖于 `pg_stat_statements` 扩展，该扩展记录每个查询的运行时间和资源消耗。

    如果查询是每次执行或总体上的顶级资源消耗者，则是索引调优的候选者。
    目前，我们使用执行时间作为累积资源消耗的代理，但查看特定资源也可能有意义，例如访问的块数或从磁盘读取的块数。
    `analyze_query_workload` 工具专注于慢查询，使用每次执行的平均时间以及执行计数和平均执行时间的阈值。
    代理也可以调用 `get_top_queries`，它接受平均与总执行时间的参数，然后将这些查询传递给 `analyze_query_indexes` 以获取索引建议。

    复杂的索引调优系统使用"工作负载压缩"来产生反映工作负载整体特征的代表性查询子集，从而简化下游算法的问题。
    openGauss MCP 通过规范化查询执行有限的工作负载压缩，使得从同一模板生成的查询显示为一个。
    它平等地权衡每个查询，这是一种在索引效益很大时有效的简化。

2. *生成候选索引*
    一旦我们有了希望通过索引改进的 SQL 查询列表，我们就会生成可能想要添加的索引列表。
    为此，我们解析 SQL 并识别在过滤器、连接、分组或排序中使用的任何列。

    要生成所有可能的索引，我们需要考虑这些列的组合，因为 Postgres 支持[多列索引](https://www.postgresql.org/docs/current/indexes-multicolumn.html)。
    在当前的实现中，我们只包含每个可能的多列索引的一个排列，这是随机选择的。
    我们做这个简化是为了减少搜索空间，因为排列通常具有等效的性能。
    但是，我们希望在这方面有所改进。

3. *搜索最佳索引配置*。
    我们的目标是找到最佳平衡性能收益与存储和维护这些索引成本的索引组合。
    我们通过使用 `hypopg` 扩展提供的"假设"功能来估计性能改进。
    这模拟了 openGauss 查询优化器在添加索引后将如何执行查询，并基于实际的 openGauss 成本模型报告变化。

    一个挑战是生成查询计划通常需要了解查询中使用的特定参数值。
    查询规范化对于减少考虑中的查询是必要的，它会删除参数常量。
    通过绑定变量提供的参数值对我们同样不可用。

    为了解决这个问题，我们通过从表统计信息中采样来产生可以作为参数提供的现实常量。
    在版本 16 中，Postgres 添加了[通用执行计划功能](https://www.postgresql.org/docs/current/sql-explain.html)，但它有限制，例如围绕 `LIKE` 子句，而我们的实现没有这些限制。

    搜索策略至关重要，因为评估所有可能的索引组合仅在简单情况下可行。
    这是最能区分各种索引方法的地方。
    采用 Microsoft 随时算法的方法，我们采用贪婪搜索策略，即找到最佳的单索引解决方案，然后找到要添加到其中的最佳索引以产生两索引解决方案。
    当时间预算耗尽或一轮探索未能产生超过最低改进阈值 10% 的收益时，我们的搜索终止。

4. *成本效益分析*。
    当面对两种索引选择时，一种产生更好的性能，一种需要更多的空间，我们如何决定选择哪一个？
    传统上，索引顾问要求存储预算并针对该存储预算优化性能。
    我们也采用存储预算，但在整个优化过程中执行成本效益分析。

    我们将其框架化为选择 [帕累托前沿](https://zh.wikipedia.org/wiki/%E5%B8%95%E7%B4%AF%E6%89%98%E5%89%8D%E6%B2%BF) 上的点的问题——即改进一个质量指标必然使另一个质量指标恶化的选择集合。
    在理想世界中，我们可能希望以货币术语评估存储成本和改进性能的收益。
    但是，有一个更简单实用的方法：以相对术语查看变化。
    大多数人会同意 100 倍的性能改进是值得的，即使存储成本是 2 倍。
    在我们的实现中，我们使用可配置参数来设置此阈值。
    默认情况下，我们要求性能改进的对数（以 10 为底）的变化是空间成本对数差异的 2 倍。
    这相当于允许 100 倍性能改进的最大 10 倍空间增加。

我们的实现与 Microsoft SQL Server 中发现的[随时算法](https://www.microsoft.com/en-us/research/wp-content/uploads/2020/06/Anytime-Algorithm-of-Database-Tuning-Advisor-for-Microsoft-SQL-Server.pdf)最密切相关。
与 [Dexter](https://github.com/ankane/dexter/)（Postgres 的自动索引工具）相比，我们搜索更大的空间并使用不同的启发式方法。
这使我们能够以更长的运行时间为代价产生更好的解决方案。

我们还显示了搜索中每一轮的工作，包括添加每个索引之前和之后的查询计划比较。
这为 LLM 提供了额外的上下文，可以在响应索引建议时使用。

### 实验性：LLM 索引调优

openGauss MCP 包括基于 [LLM 优化](https://arxiv.org/abs/2309.03409) 的实验性索引调优功能。
我们不使用启发式方法来探索可能的索引配置，而是将数据库模式和查询计划提供给 LLM，并要求它提出索引配置。
然后我们使用 `hypopg` 来预测建议索引的性能，然后将这些结果反馈给 LLM 以产生新的建议集。
我们重复此过程，直到多轮迭代不再产生进一步的改进。

当索引搜索空间很大，或者需要考虑具有许多列的索引时，LLM 索引优化具有优势。
与传统的基于搜索的方法一样，它依赖于 `hypopg` 性能预测的准确性。

为了执行 LLM 索引优化，您必须通过设置 `OPENAI_API_KEY` 环境变量提供 OpenAI API 密钥。

### 数据库健康

数据库健康检查在问题导致关键问题之前识别调优机会和维护需求。
在当前版本中，openGauss MCP 直接从 [PgHero](https://github.com/ankane/pghero) 调整数据库健康检查。
我们正在努力完全验证这些检查，并可能在将来扩展它们。

- *索引健康*。查找未使用的索引、重复索引和膨胀的索引。膨胀的索引对数据库页面的利用效率低下。
  openGauss autovacuum 清理指向死元组的索引条目，并将条目标记为可重用。但是，它不压缩索引页面，最终索引页面可能包含很少的活元组引用。
- *缓冲区缓存命中率*。测量从缓冲区缓存而不是磁盘提供的数据库读取比例。
  缓冲区缓存命中率低必须进行调查，因为它通常不是成本最优的，并导致应用程序性能下降。
- *连接健康*。检查到数据库的连接数量并报告其利用率。
  最大的风险是连接耗尽，但大量空闲或阻塞的连接也可能表示问题。
- *VACUUM 健康*。VACUUM 出于许多原因很重要。
  一个关键原因是防止事务 ID 回绕，这可能导致数据库停止接受写入。
  openGauss 多版本并发控制 (MVCC) 机制为每个事务需要唯一的事务 ID。
  但是，因为 openGauss 使用 32 位有符号整数作为事务 ID，它需要在最多 20 亿个事务后重用事务 ID。
  为此，它"冻结"历史事务的事务 ID，将它们全部设置为表示遥远过去的特殊值。
  当记录首次写入磁盘时，它们被写入对一系列事务 ID 的可见性。
  在重用这些事务 ID 之前，openGauss 必须更新任何磁盘记录，"冻结"它们以删除对要重用的事务 ID 的引用。
  此检查查找需要 VACUUM 以防止事务 ID 回绕的表。
- *复制健康*。通过监控主副本和副本之间的延迟、验证复制状态和跟踪复制槽使用情况来检查复制健康。
- *约束健康*。在正常操作期间，openGauss 拒绝任何会导致约束违反的事务。
  但是，在加载数据后或在恢复场景中可能会出现无效约束。此检查查找任何无效约束。
- *序列健康*。查找有超过其最大值风险的序列。

### Postgres 客户端库

openGauss MCP 使用 [psycopg3](https://www.psycopg.org/) 通过异步 I/O 连接到 openGauss。
在底层，psycopg3 使用 [libpq](https://www.postgresql.org/docs/current/libpq.html) 库连接到 openGauss，提供对完整 openGauss 功能集的访问和良好的底层实现支持。

一些其他基于 Python 的 MCP 服务器使用 [asyncpg](https://github.com/MagicStack/asyncpg)，这可能通过消除 `libpq` 依赖项来简化安装。
Asyncpg 也可能比 psycopg3 [更快](https://fernandoarteaga.dev/blog/psycopg-vs-asyncpg/)，但我们自己没有验证这一点。
[较旧的基准测试](https://gistpreview.github.io/?0ed296e93523831ea0918d42dd1258c2) 报告更大的性能差距，表明较新的 psycopg3 随着其成熟已经缩小了差距。

权衡这些考虑因素，我们选择了 `psycopg3` 而不是 `asyncpg`。
我们对将来修订此决定持开放态度。

### 连接配置

像[参考 PostgreSQL MCP 服务器](https://github.com/modelcontextprotocol/servers/tree/main/src/postgres)一样，openGauss MCP 在启动时接受 openGauss 连接信息。
这对于总是连接到同一数据库的用户很方便，但当用户切换数据库时可能很麻烦。

[PG-MCP](https://github.com/stuzero/pg-mcp-server) 采取的替代方法是在使用时通过 MCP 工具调用提供连接详细信息。
这对于切换数据库的用户更方便，并允许单个 MCP 服务器同时支持多个最终用户。

必须有比这两种更好的方法。
两者都有安全弱点——很少有 MCP 客户端安全地存储 MCP 服务器配置（Goose 是一个例外），通过 MCP 工具提供的凭据通过 LLM 传递并存储在聊天历史中。
两者在某些场景中也有可用性问题。

### 模式信息

模式信息工具的目的是为调用的 AI 代理提供生成正确且高性能 SQL 所需的信息。
例如，假设用户问："过去一年有多少航班从旧金山起飞并在巴黎降落？"
AI 代理需要找到存储航班的表、存储起点和目的地的列，以及可能在机场代码和机场位置之间映射的表。

*当 LLM 通常能够生成 SQL 直接从 Postgres 检索此信息时，为什么提供模式信息工具？*

我们使用 Claude 的经验表明，调用的 LLM 非常擅长生成 SQL 来通过查询 [openGauss 系统目录](https://opengauss.org/zh/docs/3.0.0/docs/DevelopGuide/%E7%B3%BB%E7%BB%9F%E7%9B%AE%E5%BD%95.html) 和 [信息模式](https://opengauss.org/zh/docs/3.0.0/docs/DevelopGuide/%E4%BF%A1%E6%81%AF%E6%A8%A1%E5%BC%8F.html)（ANSI 标准化的数据库元数据视图）来探索 openGauss 模式。
但是，我们不知道其他 LLM 是否如此可靠和熟练地这样做。

*使用 [MCP 资源](https://modelcontextprotocol.io/docs/concepts/resources) 而不是 [MCP 工具](https://modelcontextprotocol.io/docs/concepts/tools) 提供模式信息会更好吗？*

[参考 PostgreSQL MCP 服务器](https://github.com/modelcontextprotocol/servers/tree/main/src/postgres) 使用资源而不是工具来公开模式信息。
导航资源类似于导航文件系统，因此这种方法在许多方面很自然。
但是，在 MCP 客户端生态系统中，资源支持不如工具支持广泛（参见[示例客户端](https://modelcontextprotocol.io/clients)）。
此外，虽然 MCP 标准说资源可以由 AI 代理或最终用户人类访问，但某些客户端仅支持人类导航资源树。

### 受保护的 SQL 执行

AI 放大了长期存在的保护数据库免受一系列威胁的挑战，从简单错误到恶意行为者的复杂攻击。
无论威胁是意外还是恶意的，类似的安全框架都适用，目标分为三类：机密性、完整性和可用性。
便利性和安全性之间熟悉的紧张关系也很明显和突出。

openGauss MCP 的受保护 SQL 执行模式专注于完整性。
在 MCP 的背景下，我们最关心 LLM 生成的 SQL 造成损害——例如意外的数据修改或删除，或其他可能绕过组织变更管理流程的更改。

提供完整性的最简单方法是确保针对数据库执行的所有 SQL 都是只读的。
一种方法是创建具有只读访问权限的数据库用户。
虽然这是一个好方法，但许多人在实践中发现这很麻烦。
openGauss 提供了将连接或会话置于只读模式的方法，但 openGauss MCP 使用额外的保护层来确保在读写连接之上进行只读 SQL 执行。

openGauss MCP 提供防止数据和模式修改的只读事务模式。
像[参考 PostgreSQL MCP 服务器](https://github.com/modelcontextprotocol/servers/tree/main/src/postgres)一样，我们使用只读事务来提供受保护的 SQL 执行。

为了使这种机制健壮，我们需要确保 SQL 不会以某种方式绕过只读事务模式，比如通过发出 `COMMIT` 或 `ROLLBACK` 语句然后开始新事务。

例如，LLM 可以通过发出 `ROLLBACK` 语句然后开始新事务来绕过只读事务模式。
例如：
```sql
ROLLBACK; DROP TABLE users;
```

为了防止这种情况，我们在执行前使用 [pglast](https://pglast.readthedocs.io/) 库解析 SQL。
我们拒绝任何包含 `commit` 或 `rollback` 语句的 SQL。
有帮助的是，流行的 openGauss 存储过程语言，包括 PL/pgSQL 和 PL/Python，不允许 `COMMIT` 或 `ROLLBACK` 语句。
如果您的数据库上启用了不安全的存储过程语言，那么我们的只读保护可能会被绕过。

目前，openGauss MCP 为数据库提供两个级别的保护，一个在便利性/安全性频谱的任一端。
- "无限制"提供最大的灵活性。
它适用于速度和灵活性至关重要的开发环境，并且不需要保护有价值或敏感数据的环境。
- "受限"在灵活性和安全性之间取得平衡。
它适用于数据库暴露给不受信任用户的生产环境，并且保护有价值或敏感数据很重要。

无限制模式与 [Cursor 的自动运行模式](https://docs.cursor.com/chat/tools#auto-run) 方法一致，AI 代理在有限的人工监督或批准下操作。
我们期望自动运行部署在开发环境中，其中错误的后果很低，数据库不包含有价值或敏感的数据，并且可以在需要时重新创建或从备份恢复。

我们设计受限模式是保守的，即使可能不方便也要偏向安全。
受限模式仅限于只读操作，我们限制查询执行时间以防止长时间运行的查询影响系统性能。
我们可能会在未来添加措施，确保受限模式可以安全地用于生产数据库。

## openGauss MCP 开发

以下说明适用于想要开发 openGauss MCP 或更喜欢从源安装 openGauss MCP 的开发人员。

### 本地开发设置

1. **安装 uv**：

   ```bash
   curl -sSL https://astral.sh/uv/install.sh | sh
   ```

2. **克隆仓库**：

   ```bash
   git clone https://github.com/crystaldba/postgres-mcp.git
   cd postgres-mcp
   ```

3. **安装依赖项**：

   ```bash
   uv pip install -e .
   uv sync
   ```

4. **运行服务器**：
   ```bash
   uv run postgres-mcp "postgresql://user:password@localhost:5432/dbname"
   ```

### 测试

```bash
# 运行所有测试
uv run pytest

# 运行特定测试文件
uv run pytest tests/unit/test_obfuscate_password.py

# 运行特定测试
uv run pytest tests/unit/test_db_conn_pool.py::test_pool_connect_success

# 运行集成测试（需要 Docker）
uv run pytest tests/integration/
```

### 代码质量

```bash
# 使用 ruff 进行 lint
uv run ruff check .

# 使用 ruff 格式化
uv run ruff format .

# 使用 pyright 进行类型检查
uv run pyright
```

### 构建和发布

```bash
# 构建包
uv build

# 发布（详细信息请参见 justfile）
just release 0.3.0 "Release notes"
```

## 致谢

本项目基于 [Crystal DBA](https://www.crystaldba.ai/) 的优秀开源项目 [Postgres MCP Pro](https://github.com/crystaldba/postgres-mcp) 进行开发。感谢原作者的贡献，他们的工作为这个项目奠定了坚实的基础。我们在此基础上进行了 openGauss 专精改造，专注于 openGauss 数据库的优化和支持。