#!/usr/bin/env python3
"""
端到端测试脚本
"""
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from typing import Any
from typing import Dict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class E2ETestRunner:
    """端到端测试运行器"""

    def __init__(self):
        self.test_results = {}
        self.database_uri = os.environ.get("DATABASE_URI")
        if not self.database_uri:
            raise ValueError("DATABASE_URI环境变量未设置")

    async def test_database_connection(self) -> bool:
        """测试数据库连接"""
        logger.info("🔌 测试数据库连接...")

        try:
            # 使用psql测试连接
            result = subprocess.run([
                "psql", self.database_uri, "-c", "SELECT version();"
            ], capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                raise Exception(f"数据库连接失败: {result.stderr}")

            logger.info("✅ 数据库连接成功")
            return True

        except subprocess.TimeoutExpired:
            raise Exception("数据库连接超时")
        except FileNotFoundError:
            raise Exception("psql命令未找到，请确保PostgreSQL客户端已安装")

    async def test_mcp_server_startup(self) -> bool:
        """测试MCP服务器启动"""
        logger.info("🚀 测试MCP服务器启动...")

        try:
            # 测试服务器帮助信息
            result = subprocess.run([
                "uv", "run", "postgres-mcp", "--help"
            ], capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                raise Exception(f"MCP服务器启动失败: {result.stderr}")

            logger.info("✅ MCP服务器启动正常")
            return True

        except subprocess.TimeoutExpired:
            raise Exception("MCP服务器启动超时")
        except FileNotFoundError:
            raise Exception("uv命令未找到，请确保uv已安装")

    async def test_mcp_protocol_stdio(self) -> bool:
        """测试MCP协议stdio通信"""
        logger.info("📡 测试MCP协议stdio通信...")

        try:
            process = await asyncio.create_subprocess_exec(
                "uv", "run", "postgres-mcp", self.database_uri,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # 等待服务器启动
            await asyncio.sleep(3)

            # 发送JSON-RPC请求
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {}
            }

            process.stdin.write((json.dumps(request) + "\n").encode())
            await process.stdin.drain()

            # 读取响应
            response = await asyncio.wait_for(process.stdout.readline(), timeout=10)
            response_data = json.loads(response.decode())

            if "error" in response_data:
                raise Exception(f"MCP协议错误: {response_data['error']}")

            tools = response_data.get("tools", [])
            logger.info(f"✅ MCP协议通信正常，发现{len(tools)}个工具")

            # 清理进程
            process.terminate()
            await process.wait()

            return True

        except asyncio.TimeoutError:
            raise Exception("MCP协议通信超时")
        except json.JSONDecodeError:
            raise Exception("MCP协议响应格式错误")

    async def test_specific_tools(self) -> bool:
        """测试特定工具功能"""
        logger.info("🔧 测试特定工具功能...")

        try:
            # 导入测试模块
            sys.path.insert(0, os.path.dirname(__file__))
            from simple_mcp_test import test_execute_sql
            from simple_mcp_test import test_list_schemas

            # 测试基本工具
            await test_list_schemas()
            await test_execute_sql()

            logger.info("✅ 工具功能测试通过")
            return True

        except Exception as e:
            raise Exception(f"工具功能测试失败: {e!s}")

    async def test_docker_build(self) -> bool:
        """测试Docker镜像构建"""
        logger.info("🐳 测试Docker镜像构建...")

        try:
            # 构建Docker镜像
            build_result = subprocess.run([
                "docker", "build", "-t", "postgres-mcp-e2e-test", "."
            ], capture_output=True, text=True, timeout=300)

            if build_result.returncode != 0:
                raise Exception(f"Docker构建失败: {build_result.stderr}")

            logger.info("✅ Docker镜像构建成功")

            # 测试容器运行
            run_result = subprocess.run([
                "docker", "run", "--rm",
                "-e", f"DATABASE_URI={self.database_uri}",
                "postgres-mcp-e2e-test",
                "--help"
            ], capture_output=True, text=True, timeout=60)

            if run_result.returncode != 0:
                raise Exception(f"Docker容器运行失败: {run_result.stderr}")

            logger.info("✅ Docker容器测试通过")
            return True

        except subprocess.TimeoutExpired:
            raise Exception("Docker操作超时")
        except FileNotFoundError:
            raise Exception("docker命令未找到，请确保Docker已安装")

    async def test_performance_metrics(self) -> bool:
        """测试性能指标"""
        logger.info("⚡ 测试性能指标...")

        try:
            # 测试响应时间
            start_time = time.time()

            process = await asyncio.create_subprocess_exec(
                "uv", "run", "postgres-mcp", self.database_uri,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # 等待服务器启动
            await asyncio.sleep(2)

            # 发送简单请求
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {}
            }

            process.stdin.write((json.dumps(request) + "\n").encode())
            await process.stdin.drain()

            # 读取响应
            response = await asyncio.wait_for(process.stdout.readline(), timeout=10)
            response_time = time.time() - start_time

            # 清理进程
            process.terminate()
            await process.wait()

            if response_time > 5:  # 超过5秒认为性能不佳
                raise Exception(f"响应时间过长: {response_time:.2f}秒")

            logger.info(f"✅ 性能指标正常，响应时间: {response_time:.2f}秒")
            return True

        except asyncio.TimeoutError:
            raise Exception("性能测试超时")

    async def test_error_handling(self) -> bool:
        """测试错误处理"""
        logger.info("🛡️ 测试错误处理...")

        try:
            # 测试无效数据库URI
            process = await asyncio.create_subprocess_exec(
                "uv", "run", "postgres-mcp", "postgres://invalid:invalid@localhost:5432/invalid",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # 等待进程结束
            await asyncio.wait_for(process.wait(), timeout=10)

            if process.returncode == 0:
                raise Exception("应该返回错误码但没有")

            logger.info("✅ 错误处理正常")
            return True

        except asyncio.TimeoutError:
            raise Exception("错误处理测试超时")

    async def run_all_tests(self) -> Dict[str, Any]:
        """运行所有测试"""
        logger.info("🧪 开始端到端测试...")

        tests = [
            ("数据库连接", self.test_database_connection),
            ("MCP服务器启动", self.test_mcp_server_startup),
            ("MCP协议通信", self.test_mcp_protocol_stdio),
            ("工具功能", self.test_specific_tools),
            ("Docker构建", self.test_docker_build),
            ("性能指标", self.test_performance_metrics),
            ("错误处理", self.test_error_handling),
        ]

        results = {}

        for test_name, test_func in tests:
            try:
                logger.info(f"\n📋 执行测试: {test_name}")
                result = await test_func()
                results[test_name] = "✅ 通过"
                logger.info(f"✅ 测试通过: {test_name}")
            except Exception as e:
                logger.error(f"❌ 测试失败: {test_name} - {e!s}")
                results[test_name] = f"❌ 失败: {e!s}"

        return results

    def generate_report(self, results: Dict[str, Any]) -> str:
        """生成测试报告"""
        report = ["=" * 60]
        report.append("🎯 端到端测试结果汇总")
        report.append("=" * 60)

        for test_name, result in results.items():
            report.append(f"  {test_name}: {result}")

        # 统计
        total = len(results)
        passed = sum(1 for result in results.values() if result.startswith("✅"))
        failed = total - passed

        report.append("")
        report.append("📊 测试统计:")
        report.append(f"  总计: {total}")
        report.append(f"  通过: {passed}")
        report.append(f"  失败: {failed}")
        report.append(f"  成功率: {passed/total*100:.1f}%")

        if failed > 0:
            report.append("")
            report.append("❌ 失败的测试:")
            for test_name, result in results.items():
                if result.startswith("❌"):
                    report.append(f"  - {test_name}: {result}")

        return "\n".join(report)

async def main():
    """主函数"""
    try:
        runner = E2ETestRunner()
        results = await runner.run_all_tests()

        # 生成报告
        report = runner.generate_report(results)
        print(report)

        # 根据测试结果返回退出码
        failed_tests = [name for name, result in results.items() if result.startswith("❌")]
        return 1 if failed_tests else 0

    except Exception as e:
        logger.error(f"测试运行失败: {e!s}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
