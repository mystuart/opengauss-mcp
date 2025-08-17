#!/usr/bin/env python3
"""
简化的 MCP 测试工具 - 只测试核心功能
"""
import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict

# 添加源码路径
sys.path.insert(0, 'src')

# 配置日志级别 - 减少 INFO 日志的输出
logging.getLogger('postgres_mcp.sql.database_detection').setLevel(logging.WARNING)
logging.getLogger('postgres_mcp.sql.sql_driver').setLevel(logging.WARNING)


async def test_execute_sql():
    """测试 execute_sql 功能"""
    print("🧪 测试 execute_sql 功能")
    print("=" * 30)
    
    # 获取数据库连接
    database_uri = os.environ.get("DATABASE_URI")
    if not database_uri:
        database_uri = input("请输入数据库连接 URI: ").strip()
    
    if not database_uri:
        print("❌ 需要数据库连接 URI")
        return
    
    try:
        # 导入必要的模块
        from postgres_mcp.server import execute_sql, db_connection
        
        # 建立数据库连接
        print("🔌 连接数据库...")
        await db_connection.pool_connect(database_uri)
        print("✅ 数据库连接成功")
        
        # 测试查询
        test_queries = [
            "SELECT version();",
            "SELECT current_database();", 
            "SELECT current_user;",
            "SELECT 1 as test_number, 'hello' as test_string;",
        ]
        
        for i, query in enumerate(test_queries, 1):
            print(f"\n📝 测试 {i}: {query}")
            try:
                result = await execute_sql(query)
                
                if result and len(result) > 0:
                    # 尝试解析结果
                    text = result[0].text
                    if text.startswith("Error:"):
                        print(f"❌ 错误: {text}")
                    else:
                        try:
                            data = json.loads(text)
                            if isinstance(data, list) and len(data) > 0:
                                print(f"✅ 成功，返回 {len(data)} 行数据")
                                # 显示第一行数据
                                if data:
                                    print(f"   第一行: {data[0]}")
                            else:
                                print(f"✅ 成功: {text}")
                        except json.JSONDecodeError:
                            print(f"✅ 成功: {text}")
                else:
                    print("❌ 无结果返回")
                    
            except Exception as e:
                print(f"❌ 异常: {e}")
        
        print("\n🎉 测试完成!")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
    finally:
        # 清理连接
        try:
            await db_connection.close()
        except:
            pass


async def interactive_test():
    """交互式测试"""
    print("🤖 简化的 MCP 交互式测试")
    print("=" * 35)
    
    # 获取数据库连接
    database_uri = os.environ.get("DATABASE_URI")
    if not database_uri:
        database_uri = input("请输入数据库连接 URI: ").strip()
    
    if not database_uri:
        print("❌ 需要数据库连接 URI")
        return
    
    try:
        # 导入必要的模块
        from postgres_mcp.server import execute_sql, db_connection
        
        # 建立数据库连接
        print("🔌 连接数据库...")
        await db_connection.pool_connect(database_uri)
        print("✅ 数据库连接成功")
        
        print("\n📖 输入 SQL 查询，输入 'quit' 退出")
        
        while True:
            try:
                query = input("\n🤖 SQL> ").strip()
                
                if not query:
                    continue
                
                if query.lower() in ['quit', 'exit', 'q']:
                    print("👋 再见!")
                    break
                
                print(f"🔍 执行: {query}")
                result = await execute_sql(query)
                
                if result and len(result) > 0:
                    text = result[0].text
                    if text.startswith("Error:"):
                        print(f"❌ {text}")
                    else:
                        try:
                            data = json.loads(text)
                            if isinstance(data, list):
                                print(f"📊 返回 {len(data)} 行:")
                                for i, row in enumerate(data[:3]):  # 只显示前3行
                                    print(f"  {i+1}: {row}")
                                if len(data) > 3:
                                    print(f"  ... 还有 {len(data) - 3} 行")
                            else:
                                print(f"📄 结果: {text}")
                        except json.JSONDecodeError:
                            print(f"📄 结果: {text}")
                else:
                    print("📭 无结果")
                    
            except KeyboardInterrupt:
                print("\n👋 再见!")
                break
            except Exception as e:
                print(f"❌ 错误: {e}")
        
    except Exception as e:
        print(f"❌ 连接失败: {e}")
    finally:
        # 清理连接
        try:
            await db_connection.close()
        except:
            pass


async def main():
    """主函数"""
    if len(sys.argv) > 1 and sys.argv[1] == "auto":
        await test_execute_sql()
    else:
        await interactive_test()


if __name__ == "__main__":
    asyncio.run(main())