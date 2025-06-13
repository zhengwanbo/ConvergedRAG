import os
import oracledb
from tabulate import tabulate
from dotenv import load_dotenv
from minio import Minio
from io import BytesIO
from management.server.database import get_db_connection, get_minio_client, get_redis_connection

# 加载环境变量
load_dotenv("../../docker/.env")

# MinIO连接配置
MINIO_CONFIG = {
    "endpoint": "localhost:" + os.getenv("MINIO_PORT", "9000"),
    "access_key": os.getenv("MINIO_USER", "rag_flow"),
    "secret_key": os.getenv("MINIO_PASSWORD", "infini_rag_flow"),
    "secure": False
}

def get_all_documents():
    """获取所有文档信息及其在MinIO中的存储位置"""
    try:
        # 连接到MySQL数据库
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 首先获取document表的列信息
        cursor.execute("""
            SELECT 
                column_name, 
                data_type, 
                data_length, 
                data_precision, 
                data_scale, 
                nullable, 
                data_default
            FROM user_tab_columns
            WHERE table_name = 'DOCUMENT'
            ORDER BY column_id
        """)
        columns = [column[0] for column in cursor.fetchall()]
        print(f"下载: {columns}")

        # 构建动态查询语句，只选择存在的列
        select_fields = []
        for field in ['id', 'name', 'kb_id', 'location', 'type', 'created_by', 'create_time']:
            if field.upper() in columns:
                select_fields.append(f'd.{field}')
        
        # 添加可选字段
        optional_fields = ['token_count', 'chunk_count']
        for field in optional_fields:
            if field.upper() in columns:
                select_fields.append(f'd.{field}')
        
        # 构建并执行查询
        query = f"""
            SELECT {', '.join(select_fields)}
            FROM document d
            ORDER BY d.create_time DESC
        """

        print(f"执行: {query}")
        cursor.execute(query)
        cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))
        results = cursor.fetchall()
        documents = [{k.lower(): v for k, v in item.items()} for item in results]

        # 获取文档与文件的关联信息
        cursor.execute("""
            SELECT f2d.document_id, f.id as file_id, f.parent_id, f.source_type
            FROM file2document f2d
            JOIN files f ON f2d.file_id = f.id
        """)
        cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))
        file_mappings = {}
        for row in cursor.fetchall():
            result = {k.lower(): v for k, v in row.items()}
            file_mappings[result['document_id']] = {
                'file_id': result['file_id'],
                'parent_id': result['parent_id'],
                'source_type': result['source_type']
            }
        
        # 整合信息
        result = []
        for doc in documents:
            doc_id = doc['id']
            kb_id = doc['kb_id']
            location = doc['location']
            
            # 确定存储位置
            storage_bucket = kb_id
            storage_location = location
            
            # 如果有文件映射，检查是否需要使用文件的parent_id作为bucket
            if doc_id in file_mappings:
                file_info = file_mappings[doc_id]
                # 模拟File2DocumentService.get_storage_address的逻辑
                if file_info.get('source_type') is None or file_info.get('source_type') == 0:  # LOCAL
                    storage_bucket = file_info['parent_id']
            
            # 构建MinIO存储路径
            minio_path = f"{storage_bucket}/{storage_location}"
            print(f"minio_path: {minio_path}")
            # 构建结果字典，只包含存在的字段
            result_item = {
                'id': doc_id,
                'name': doc.get('name', ''),
                'kb_id': kb_id,
                'size': doc.get('size', 0),
                'type': doc.get('type', ''),
                'minio_path': minio_path,
                'storage_bucket': storage_bucket,
                'storage_location': storage_location
            }
            
            # 添加可选字段
            if 'token_count' in doc:
                result_item['token_count'] = doc['token_count']
            if 'chunk_count' in doc:
                result_item['chunk_count'] = doc['chunk_count']
                
            result.append(result_item)
        
        cursor.close()
        conn.close()
        print(f"result: {result}")
        return result
    
    except Exception as e:
        print(f"Error: {e}")
        return []

def download_document_from_minio(bucket, object_name, output_path):
    """从MinIO下载文档"""
    try:
        # 创建MinIO客户端
        minio_client = Minio(
            endpoint=MINIO_CONFIG["endpoint"],
            access_key=MINIO_CONFIG["access_key"],
            secret_key=MINIO_CONFIG["secret_key"],
            secure=MINIO_CONFIG["secure"]
        )
        
        # 检查bucket是否存在
        if not minio_client.bucket_exists(bucket):
            print(f"错误: Bucket '{bucket}' 不存在")
            return False
        
        # 下载文件
        print(f"正在从MinIO下载: {bucket}/{object_name} 到 {output_path}")
        minio_client.fget_object(bucket, object_name, output_path)
        print(f"文件已成功下载到: {output_path}")
        return True
    
    except Exception as e:
        print(f"下载文件时出错: {e}")
        return False

def main():
    """主函数"""
    documents = get_all_documents()
    
    if not documents:
        print("未找到任何文档信息")
        return
    
    # 使用tabulate打印表格
    # 动态确定表头
    sample_doc = documents[0]
    headers = ['ID', '文档名', '数据集ID', '大小(字节)', '类型', 'MinIO路径']
    if 'token_count' in sample_doc:
        headers.insert(-1, 'Token数')
    if 'chunk_count' in sample_doc:
        headers.insert(-1, '块数')
    
    # 构建表格数据
    table_data = []
    for doc in documents:
        row = [
            doc['id'], 
            doc['name'], 
            doc['kb_id'], 
            doc['size'], 
            doc['type']
        ]
        
        if 'token_count' in doc:
            row.append(doc['token_count'])
        if 'chunk_count' in doc:
            row.append(doc['chunk_count'])
            
        row.append(doc['minio_path'])
        table_data.append(row)
    
    print(tabulate(table_data, headers=headers, tablefmt="grid"))
    print(f"总计: {len(documents)}个文档")
    
    # 下载第一个文档
    if documents:
        first_doc = documents[0]
        doc_name = first_doc['name']
        bucket = first_doc['storage_bucket']
        object_name = first_doc['storage_location']
        
        # 创建下载目录
        download_dir = "downloads"
        os.makedirs(download_dir, exist_ok=True)
        
        # 构建输出文件路径
        output_path = os.path.join(download_dir, doc_name)
        
        # 下载文件
        print(f"\n 下载文档: {object_name}, {bucket}, {output_path}")
        success = download_document_from_minio(bucket, object_name, output_path)
        if success:
            print(f"\n✅ 已成功下载文档: {doc_name}")
            print(f"文件保存在: {os.path.abspath(output_path)}")
        else:
            print("\n❌ 下载失败，可能原因:")
            print("- Bucket不存在")
            print("- 文件路径不正确")
            print("- 权限不足")
            print("请检查MinIO控制台确认资源是否存在")

if __name__ == "__main__":
    main()
