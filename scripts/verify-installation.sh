#!/bin/bash

# openGauss MCP 安装验证脚本
# 使用方法: ./verify-installation.sh

set -e

echo "🔍 验证 openGauss MCP 安装"
echo "============================"

# 检查 Python 环境
echo "📋 检查 Python 环境..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    echo "✅ Python: $PYTHON_VERSION"
else
    echo "❌ Python 未安装"
    exit 1
fi

# 检查 uv
if command -v uv &> /dev/null; then
    UV_VERSION=$(uv --version)
    echo "✅ uv: $UV_VERSION"
else
    echo "⚠️  uv 未安装 (可选)"
fi

# 检查 Docker
if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version)
    echo "✅ Docker: $DOCKER_VERSION"
else
    echo "❌ Docker 未安装"
    exit 1
fi

# 检查 Docker Compose
if command -v docker-compose &> /dev/null; then
    COMPOSE_VERSION=$(docker-compose --version)
    echo "✅ Docker Compose: $COMPOSE_VERSION"
else
    echo "⚠️  Docker Compose 未安装 (可选)"
fi

echo ""
echo "📦 检查项目文件..."

# 检查关键文件
REQUIRED_FILES=(
    "pyproject.toml"
    "src/opengauss_mcp/__init__.py"
    "src/opengauss_mcp/server.py"
    "Dockerfile.opengauss"
    "docker-compose.opengauss.yml"
    "scripts/build-opengauss-docker.sh"
    "scripts/build-pip-package.sh"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "✅ $file"
    else
        echo "❌ $file 缺失"
        exit 1
    fi
done

echo ""
echo "🔨 测试构建..."

# 测试 Python 包构建
echo "📦 测试 Python 包构建..."
if command -v uv &> /dev/null; then
    uv build --quiet
    if [ $? -eq 0 ]; then
        echo "✅ Python 包构建成功"
    else
        echo "❌ Python 包构建失败"
        exit 1
    fi
else
    echo "⚠️  跳过 Python 包构建测试 (uv 未安装)"
fi

# 测试 Docker 镜像构建
echo "🐳 测试 Docker 镜像构建..."
docker build --file Dockerfile.opengauss --tag opengauss-mcp:test --quiet .
if [ $? -eq 0 ]; then
    echo "✅ Docker 镜像构建成功"
    # 清理测试镜像
    docker rmi opengauss-mcp:test > /dev/null 2>&1 || true
else
    echo "❌ Docker 镜像构建失败"
    exit 1
fi

echo ""
echo "🧪 测试导入..."

# 测试 Python 导入
python3 -c "
import sys
sys.path.append('src')
try:
    from opengauss_mcp.server import main
    from opengauss_mcp.sql.database_detection import detect_database_type
    from opengauss_mcp.gaussdb.config_loader import ConfigLoader
    print('✅ 所有核心模块导入成功')
except Exception as e:
    print(f'❌ 模块导入失败: {e}')
    sys.exit(1)
"

echo ""
echo "📋 检查脚本权限..."

# 检查脚本权限
SCRIPTS=(
    "scripts/build-opengauss-docker.sh"
    "scripts/build-pip-package.sh"
    "scripts/release.sh"
)

for script in "${SCRIPTS[@]}"; do
    if [ -x "$script" ]; then
        echo "✅ $script 可执行"
    else
        echo "⚠️  $script 无执行权限"
        chmod +x "$script"
        echo "✅ 已修复 $script 权限"
    fi
done

echo ""
echo "🎉 安装验证完成！"
echo ""
echo "📖 下一步："
echo "1. 阅读 docs/INSTALLATION.md 了解详细安装步骤"
echo "2. 使用 docker-compose.opengauss.yml 启动完整环境"
echo "3. 配置您的 AI 助手使用 openGauss MCP"
echo ""
echo "🚀 快速启动："
echo "docker-compose -f docker-compose.opengauss.yml up -d"