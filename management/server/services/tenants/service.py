import oracledb
from datetime import datetime
from management.server.database import get_db_connection

def get_tenants_with_pagination(current_page, page_size, username=''):
    """查询租户信息，支持分页和条件筛选"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 构建WHERE子句和参数
        where_clauses = []
        params = []
        
        if username:
            where_clauses.append("""
            EXISTS (
                SELECT 1 FROM user_tenant ut 
                JOIN user u ON ut.user_id = u.id 
                WHERE ut.tenant_id = t.id AND u.nickname LIKE :1
            )
            """)
            params.append(f"%{username}%")
        
        # 组合WHERE子句
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        # 查询总记录数
        count_sql = f"""
        SELECT COUNT(*) as total 
        FROM tenant t 
        WHERE {where_sql}
        """
        cursor.execute(count_sql, params)
        result = cursor.fetchone()
        total = result[0]
        
        # 计算分页偏移量
        offset = (current_page - 1) * page_size
        
        # 执行分页查询
        query = f"""
        SELECT 
            t.id, 
            (SELECT u.nickname FROM user_tenant ut JOIN users u ON ut.user_id = u.id 
             WHERE ut.tenant_id = t.id AND ut.role = 'owner' FETCH FIRST 1 ROWS ONLY) as username,
            t.llm_id as chat_model,
            t.embd_id as embedding_model,
            t.create_date, 
            t.update_date
        FROM 
            tenant t
        WHERE 
            {where_sql}
        ORDER BY 
            t.create_date DESC
        OFFSET :1 ROWS FETCH FIRST :2 ROWS ONLY
        """
        cursor.execute(query, params + [offset,page_size])
        cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))
        results = cursor.fetchall()
        
        # 关闭连接
        cursor.close()
        conn.close()
        
        # 格式化结果
        formatted_tenants = []
        for tenant in results:
            formatted_tenants.append({
                "id": tenant["ID"],
                "username": tenant["USERNAME"] if tenant["USERNAME"] else "未指定",
                "chatModel": tenant["CHAT_MODEL"] if tenant["CHAT_MODEL"] else "",
                "embeddingModel": tenant["EMBEDDING_MODEL"] if tenant["EMBEDDING_MODEL"] else "",
                "createTime": tenant["CREATE_DATE"].strftime("%Y-%m-%d %H:%M:%S") if tenant["CREATE_DATE"] else "",
                "updateTime": tenant["UPDATE_DATE"].strftime("%Y-%m-%d %H:%M:%S") if tenant["UPDATE_DATE"] else ""
            })
        
        return formatted_tenants, total
        
    except oracledb.DatabaseError as err:
        print(f"数据库错误: {err}")
        return [], 0

def update_tenant(tenant_id, tenant_data):
    """更新租户信息"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 更新租户表
        current_datetime = datetime.now()
        update_time = int(current_datetime.timestamp() * 1000)
        current_date = current_datetime.strftime("%Y-%m-%d %H:%M:%S")
        
        query = """
        UPDATE tenant 
        SET update_time = :1, 
            update_date = TO_TIMESTAMP(:3, 'YYYY-MM-DD HH24:MI:SS'), 
            llm_id = :3, 
            embd_id = :4
        WHERE id = :5
        """
        
        cursor.execute(query, (
            update_time,
            current_date,
            tenant_data.get("chatModel", ""),
            tenant_data.get("embeddingModel", ""),
            tenant_id
        ))
        
        affected_rows = cursor.rowcount
        conn.commit()
        
        cursor.close()
        conn.close()
        
        return affected_rows > 0
        
    except oracledb.DatabaseError as err:
        print(f"更新租户错误: {err}")
        return False
