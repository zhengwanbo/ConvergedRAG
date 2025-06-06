import os
import oracledb
from dotenv import load_dotenv
from database import DB_CONFIG

# 加载环境变量
load_dotenv("../../docker/.env")

def get_db_connection():
    """创建数据库连接"""
    return oracledb.connect(**DB_CONFIG)

def get_all_tables():
    """获取数据库中所有表的名称"""
    try:
        # 连接数据库
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 查询所有表名
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        
        print(f"数据库 {DB_CONFIG['database']} 中的表:")
        if tables:
            for i, table in enumerate(tables, 1):
                print(f"{i}. {table[0]}")
        else:
            print("数据库中没有表")
            
        # 检查是否存在特定表
        important_tables = ['document', 'files', 'file2document']
        print("\n检查重要表是否存在:")
        for table in important_tables:
            cursor.execute(f"SHOW TABLES LIKE '{table}'")
            exists = cursor.fetchone() is not None
            status = "✓ 存在" if exists else "✗ 不存在"
            print(f"{table}: {status}")
        
        cursor.close()
        conn.close()
        
    except oracledb.DatabaseError as err:
        print(f"数据库连接或查询出错: {e}")

if __name__ == "__main__":
    get_all_tables()
