#!/bin/bash

# openGauss MCP 发布脚本
# 使用方法: ./release.sh [version] [registry]

set -e

VERSION=${1:-$(grep -oP 'version = "\K[^"]+' pyproject.toml)}
REGISTRY=${2:-"docker.io"}

echo "🚀 发布 openGauss MCP v$VERSION"
echo "Docker 注册表: $REGISTRY"
echo "============================"

# 确认发布
read -p "确认发布版本 $VERSION 吗？(y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ 发布已取消"
    exit 1
fi

# 1. 构建 pip 包
echo "📦 构建 pip 包..."
./scripts/build-pip-package.sh $VERSION

# 2. 构建 Docker 镜像
echo "🐳 构建 Docker 镜像..."
REGISTRY=$REGISTRY ./scripts/build-opengauss-docker.sh $VERSION

# 3. 创建 Git 标签
echo "🏷️ 创建 Git 标签..."
git tag -a "v$VERSION" -m "Release v$VERSION" || true

echo "✅ 发布准备完成"
echo ""
echo "📋 发布清单:"
echo "1. Git 标签: v$VERSION"
echo "2. pip 包: dist/"
echo "3. Docker 镜像: ${REGISTRY}/opengauss-mcp:${VERSION}"
echo ""
echo "🚀 下一步:"
echo "1. 推送 Git 标签: git push origin v$VERSION"
echo "2. 发布到 PyPI: twine upload dist/*"
echo "3. 推送 Docker 镜像: docker push ${REGISTRY}/opengauss-mcp:${VERSION}"
echo "4. 更新 GitHub Release"