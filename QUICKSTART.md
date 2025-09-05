# openGauss MCP 快速启动指南

## 🚀 一键启动

### 使用 Docker Compose (推荐)

```bash
# 1. 启动完整环境
docker-compose -f docker-compose.opengauss.yml up -d

# 2. 查看服务状态
docker-compose -f docker-compose.opengauss.yml ps

# 3. 查看日志
docker-compose -f docker-compose.opengauss.yml logs -f opengauss-mcp
```

服务信息：
- **openGauss 数据库**: `localhost:5432`
  - 用户名: `gaussdb`
  - 密码: `Secur3P@ssw0rd`
  - 数据库: `postgres`
- **openGauss MCP**: `localhost:8000`

### 停止服务

```bash
# 停止服务
docker-compose -f docker-compose.opengauss.yml down

# 停止并删除数据
docker-compose -f docker-compose.opengauss.yml down -v
```

## 🛠️ 手动安装

### 1. 安装 Python 包

```bash
# 使用 uv (推荐)
uv pip install opengauss-mcp

# 或使用 pipx
pipx install opengauss-mcp
```

### 2. 运行服务

```bash
# 连接到您的 openGauss 数据库
opengauss-mcp "postgresql://user:password@host:5432/dbname"

# 或使用 SSE 模式
opengauss-mcp "postgresql://user:password@host:5432/dbname" --transport=sse
```

## 🔧 配置 AI 助手

### Claude Desktop

编辑配置文件 `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "opengauss": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "DATABASE_URI=postgresql://gaussdb:Secur3P@ssw0rd@localhost:5432/postgres",
        "your-registry/opengauss-mcp:latest",
        "--access-mode=unrestricted"
      ]
    }
  }
}
```

### 其他客户端

类似配置，将 `postgres` 替换为 `opengauss`，调整镜像名称和连接字符串。

## 📊 验证安装

### 测试数据库连接

```bash
# 连接到 openGauss
docker exec -it opengauss-db gsql -d postgres -U gaussdb

# 查看表
\dt

# 查看扩展
SELECT * FROM pg_extension;
```

### 测试 MCP 服务

```bash
# 检查服务健康状态
curl http://localhost:8000/health

# 或使用 Docker
docker exec opengauss-mcp python -c "from src.opengauss_mcp.sql.database_detection import detect_database_type; print('OK')"
```

## 💡 使用示例

在您的 AI 助手中尝试：

1. **数据库健康检查**：
   ```
   检查我的数据库健康状况并识别任何问题。
   ```

2. **索引优化**：
   ```
   分析我的数据库工作负载并建议索引以改善性能。
   ```

3. **查询优化**：
   ```
   帮我优化这个查询：SELECT * FROM users WHERE created_at > '2024-01-01';
   ```

## 🚨 故障排除

### 常见问题

1. **容器启动失败**
   ```bash
   # 查看详细日志
   docker-compose -f docker-compose.opengauss.yml logs opengauss
   
   # 检查端口占用
   lsof -i :5432
   lsof -i :8000
   ```

2. **数据库连接失败**
   ```bash
   # 检查数据库状态
   docker-compose -f docker-compose.opengauss.yml logs opengauss
   
   # 重启数据库
   docker-compose -f docker-compose.opengauss.yml restart opengauss
   ```

3. **MCP 服务无法连接**
   ```bash
   # 检查环境变量
   docker exec opengauss-mcp env | grep DATABASE
   
   # 测试连接
   docker exec opengauss-mcp python -c "
   import sys
   sys.path.append('/app')
   from src.opengauss_mcp.sql.database_detection import detect_database_type
   print('Connection test')
   "
   ```

## 📚 更多信息

- 📖 [详细安装指南](docs/INSTALLATION.md)
- 🔧 [开发文档](docs/gaussdb-architecture-guide.md)
- 🐛 [问题反馈](https://github.com/your-repo/issues)

---

**提示**: 首次启动可能需要几分钟时间下载镜像和初始化数据库。