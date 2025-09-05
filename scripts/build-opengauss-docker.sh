#!/bin/bash

# openGauss MCP Docker 镜像构建脚本
# 使用方法: ./build-opengauss-docker.sh [version]

set -e

# 默认版本
VERSION=${1:-latest}
IMAGE_NAME="opengauss-mcp"
REGISTRY=${REGISTRY:-"docker.io"}

echo "🔨 构建 openGauss MCP Docker 镜像"
echo "版本: $VERSION"
echo "镜像名: $IMAGE_NAME"
echo "注册表: $REGISTRY"
echo "============================"

# 检查 Docker 是否可用
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装或未在 PATH 中"
    exit 1
fi

# 检查 Docker 是否运行
if ! docker info &> /dev/null; then
    echo "❌ Docker 服务未运行"
    exit 1
fi

# 构建镜像
echo "📦 构建镜像..."
docker build \
    --file Dockerfile.opengauss \
    --tag ${REGISTRY}/${IMAGE_NAME}:${VERSION} \
    --tag ${REGISTRY}/${IMAGE_NAME}:latest \
    --build-arg VERSION=${VERSION} \
    .

if [ $? -eq 0 ]; then
    echo "✅ 镜像构建成功"
    echo "📋 镜像信息:"
    docker images ${REGISTRY}/${IMAGE_NAME}:${VERSION} --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"
    
    echo ""
    echo "🚀 运行镜像:"
    echo "docker run -e DATABASE_URI=postgresql://user:password@host:port/dbname ${REGISTRY}/${IMAGE_NAME}:${VERSION}"
    
    echo ""
    echo "📝 推送到注册表:"
    echo "docker push ${REGISTRY}/${IMAGE_NAME}:${VERSION}"
    echo "docker push ${REGISTRY}/${IMAGE_NAME}:latest"
else
    echo "❌ 镜像构建失败"
    exit 1
fi