#!/bin/bash

# openGauss MCP pip 安装包构建脚本
# 使用方法: ./build-pip-package.sh [version]

set -e

# 默认版本
VERSION=${1:-0.3.0}
PACKAGE_NAME="opengauss-mcp"

echo "📦 构建 openGauss MCP pip 安装包"
echo "版本: $VERSION"
echo "包名: $PACKAGE_NAME"
echo "============================"

# 检查依赖
if ! command -v uv &> /dev/null; then
    echo "❌ uv 未安装或未在 PATH 中"
    echo "请先安装 uv: curl -sSL https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# 清理之前的构建
echo "🧹 清理之前的构建..."
rm -rf dist/ build/ *.egg-info

# 构建
echo "🔨 构建包..."
uv build

# 检查构建结果
if [ $? -eq 0 ]; then
    echo "✅ 包构建成功"
    echo "📋 构建产物:"
    ls -la dist/
    
    echo ""
    echo "🚀 本地安装测试:"
    echo "uv pip install dist/${PACKAGE_NAME}-${VERSION}-py3-none-any.whl"
    
    echo ""
    echo "📝 发布到 PyPI:"
    echo "uv pip install twine"
    echo "twine upload dist/*"
    
    echo ""
    echo "🔍 检查包内容:"
    echo "tar -tzf dist/${PACKAGE_NAME}-${VERSION}.tar.gz"
else
    echo "❌ 包构建失败"
    exit 1
fi