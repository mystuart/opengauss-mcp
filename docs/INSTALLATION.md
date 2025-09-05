# openGauss MCP 安装指南

本指南提供详细的 openGauss MCP 安装步骤，包括 Docker 镜像和 Python 包的准备。

## 快速开始

### 方式一：使用 Docker Compose (推荐)

这是最简单的安装方式，一键启动 openGauss 数据库和 MCP 服务。

```bash
# 克隆项目
git clone <your-repo-url>
cd opengauss-mcp

# 启动服务
docker-compose -f docker-compose.opengauss.yml up -d

# 查看服务状态
docker-compose -f docker-compose.opengauss.yml ps

# 查看日志
docker-compose -f docker-compose.opengauss.yml logs -f
```

服务启动后：
- openGauss 数据库：`localhost:5432`
- openGauss MCP 服务：`localhost:8000`

### 方式二：使用 Docker 镜像

如果您已经有 openGauss 数据库，可以使用我们的 Docker 镜像：

```bash
# 拉取镜像
docker pull your-registry/opengauss-mcp:latest

# 运行容器
docker run -d \
  --name opengauss-mcp \
  -e DATABASE_URI=postgresql://username:password@host:5432/dbname \
  -p 8000:8000 \
  your-registry/opengauss-mcp:latest \
  --access-mode=unrestricted
```

### 方式三：使用 Python 包

#### 从 PyPI 安装

```bash
# 使用 pipx (推荐)
pipx install opengauss-mcp

# 或使用 uv
uv pip install opengauss-mcp

# 运行
opengauss-mcp "postgresql://username:password@host:5432/dbname"
```

#### 从源码安装

```bash
# 克隆项目
git clone <your-repo-url>
cd opengauss-mcp

# 安装依赖
uv pip install -e .

# 运行
uv run opengauss-mcp "postgresql://username:password@host:5432/dbname"
```

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `DATABASE_URI` | openGauss 数据库连接字符串 | 必填 |
| `ACCESS_MODE` | 访问模式 (unrestricted/restricted) | unrestricted |
| `TRANSPORT` | 传输方式 (stdio/sse) | stdio |
| `SSE_HOST` | SSE 监听地址 | 0.0.0.0 |
| `SSE_PORT` | SSE 监听端口 | 8000 |
| `OPENAI_API_KEY` | OpenAI API 密钥 (可选，用于 LLM 索引优化) | 无 |

### 访问模式

- **unrestricted**: 完全读写访问，适用于开发环境
- **restricted**: 只读访问，适用于生产环境

## 数据库准备

### openGauss 扩展安装

为了获得最佳性能，建议安装以下扩展：

```sql
-- 创建扩展
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS hypopg;

-- 检查扩展是否安装成功
SELECT * FROM pg_extension WHERE extname IN ('pg_stat_statements', 'hypopg');
```

### 用户权限

确保连接用户具有以下权限：

```sql
-- 基本权限
GRANT CONNECT ON DATABASE your_database TO your_user;
GRANT USAGE ON SCHEMA public TO your_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO your_user;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO your_user;

-- 如果需要写入权限
GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO your_user;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO your_user;
```

## 构建和发布

### 构建 Docker 镜像

```bash
# 构建镜像
./scripts/build-opengauss-docker.sh [version]

# 示例
./scripts/build-opengauss-docker.sh 0.3.0
```

### 构建 Python 包

```bash
# 构建 pip 包
./scripts/build-pip-package.sh [version]

# 示例
./scripts/build-pip-package.sh 0.3.0
```

### 发布

```bash
# 完整发布流程
./scripts/release.sh [version] [registry]

# 示例
./scripts/release.sh 0.3.0 docker.io
```

## 故障排除

### 常见问题

1. **数据库连接失败**
   - 检查 `DATABASE_URI` 是否正确
   - 确认 openGauss 数据库正在运行
   - 验证网络连接和防火墙设置

2. **扩展未找到**
   - 确认已安装 `pg_stat_statements` 和 `hypopg` 扩展
   - 检查用户权限

3. **权限错误**
   - 确认数据库用户具有必要权限
   - 检查访问模式设置

### 日志查看

```bash
# Docker 容器日志
docker logs opengauss-mcp

# Docker Compose 日志
docker-compose -f docker-compose.opengauss.yml logs -f opengauss-mcp
```

### 健康检查

```bash
# 检查容器健康状态
docker ps --filter "name=opengauss-mcp"

# 手动健康检查
docker exec opengauss-mcp python -c "import sys; sys.path.append('/app'); from src.opengauss_mcp.sql.database_detection import detect_database_type; print('Health check passed')"
```

## 性能优化

### 数据库配置

建议的 openGauss 配置参数：

```sql
-- 在 postgresql.conf 中设置
shared_preload_libraries = 'pg_stat_statements'
track_activity_query_size = 2048
pg_stat_statements.max = 10000
pg_stat_statements.track = all
```

### MCP 服务配置

- 使用 SSD 存储提高 I/O 性能
- 调整 `max_connections` 根据并发需求
- 监控内存使用情况

## 安全建议

1. **生产环境配置**
   - 使用 `restricted` 访问模式
   - 配置数据库用户最小权限原则
   - 启用 SSL 连接

2. **网络安全**
   - 使用防火墙限制访问
   - 考虑使用 VPN 或私有网络
   - 定期更新镜像和依赖

3. **监控和日志**
   - 启用详细日志记录
   - 监控资源使用情况
   - 定期备份数据库

## 支持

如果遇到问题，请：

1. 查看本文档的故障排除部分
2. 检查项目的 Issues 页面
3. 提交新的 Issue 描述问题
4. 提供详细的错误日志和环境信息

---

*本文档基于 openGauss MCP 项目的实际安装经验编写，将持续更新和完善。*