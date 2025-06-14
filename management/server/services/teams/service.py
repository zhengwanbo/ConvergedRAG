import oracledb
from datetime import datetime
from management.server.utils import generate_uuid
from management.server.database import get_db_connection
import logging
# 配置日志（通常在应用启动时设置）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
def get_teams_with_pagination(current_page, page_size, name='', sort_by="create_time",sort_order="desc"):
    """查询团队信息，支持分页和条件筛选"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 构建WHERE子句和参数
        where_clauses = []
        params = []
        
        if name:
            where_clauses.append("t.name LIKE :1")
            params.append(f"%{name}%")
        
        # 组合WHERE子句
        where_sql = "WHERE " + (" AND ".join(where_clauses) if where_clauses else "1=1")

        # 验证排序字段
        valid_sort_fields = ["name", "create_time", "create_date"]
        if sort_by not in valid_sort_fields:
            sort_by = "create_time"

        # 构建排序子句
        sort_clause = f"ORDER BY {sort_by} {sort_order.upper()}"

        # 查询总记录数
        count_sql = f"SELECT COUNT(*) as total FROM tenant t {where_sql}"
        logger.info("total: %s", count_sql)

        cursor.execute(count_sql, params)
        result = cursor.fetchone()
        total = result[0]
        logger.info("total: %s", total)

        # 计算分页偏移量
        offset = (current_page - 1) * page_size
        
        # 执行分页查询，包含负责人信息和成员数量
        query = f"""
        SELECT 
            t.id, 
            t.name, 
            t.create_date, 
            t.update_date, 
            t.status,
            (SELECT u.nickname FROM user_tenant ut JOIN users u ON ut.user_id = u.id 
            WHERE ut.tenant_id = t.id AND ut.role = 'owner' FETCH FIRST 1 ROWS ONLY) as owner_name,
            (SELECT COUNT(*) FROM user_tenant ut WHERE ut.tenant_id = t.id AND ut.status = 1) as member_count
        FROM 
            tenant t
        {where_sql}
        {sort_clause}
        OFFSET :1 ROWS FETCH FIRST :2 ROWS ONLY
        """
        logger.info("执行SQL: %s", query)
        logger.info("SQL参数: %s", params + [offset, page_size])

        cursor.execute(query, params + [offset, page_size])
        cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))
        results = cursor.fetchall()

        logger.info("执行结果: %s", results)
        # 关闭连接
        cursor.close()
        conn.close()
        
        # 格式化结果
        formatted_teams = []
        for team in results:
            owner_name = team["OWNER_NAME"] if team["OWNER_NAME"] else "未指定"
            formatted_teams.append({
                "id": team["ID"],
                "name": f"{owner_name}的团队",
                "ownerName": owner_name,
                "memberCount": team["MEMBER_COUNT"],
                "createTime": team["CREATE_DATE"].strftime("%Y-%m-%d %H:%M:%S") if team["CREATE_DATE"] else "",
                "updateTime": team["UPDATE_DATE"].strftime("%Y-%m-%d %H:%M:%S") if team["UPDATE_DATE"] else "",
                "status": team["STATUS"]
            })
        
        return formatted_teams, total
        
    except oracledb.DatabaseError as err: 
        logger.info("数据库错误: err")
        return [], 0


def get_team_by_id(team_id):
    """根据ID获取团队详情"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = """
        SELECT id, name, create_date, update_date, status, credit
        FROM tenant
        WHERE id = :1
        """
        cursor.execute(query, (team_id,))
        cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))
        results = cursor.fetchone()

        team = [{k.lower(): v for k, v in item.items()} for item in results]

        cursor.close()
        conn.close()
        
        if team:
            return team
            # return {
            #     "id": team["ID"],
            #     "name": team["NAME"],
            #     "create_date": team["CREATE_DATE"].strftime("%Y-%m-%d %H:%M:%S") if team["CREATE_DATE"] else "",
            #     "update_date": team["UPDATE_DATE"].strftime("%Y-%m-%d %H:%M:%S") if team["UPDATE_DATE"] else "",
            #     "status": team["STATUS"],
            #     "credit": team["CREDIT"]
            # }
        return None
        
    except oracledb.DatabaseError as err:
        logger.info("数据库错误: err")
        return None

def delete_team(team_id):
    """删除指定ID的团队"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 删除团队成员关联
        member_query = "DELETE FROM user_tenant WHERE tenant_id = :1"
        cursor.execute(member_query, (team_id,))
        
        # 删除团队
        team_query = "DELETE FROM tenant WHERE id = :1"
        cursor.execute(team_query, (team_id,))
        
        affected_rows = cursor.rowcount
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return affected_rows > 0
        
    except oracledb.DatabaseError as err: 
        logger.info("删除团队错误: err")
        print(f"删除团队错误: {err}")
        return False

def get_team_members(team_id):
    """获取团队成员列表"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = """
        SELECT ut.user_id, u.nickname, u.email, ut.role, ut.create_date
        FROM user_tenant ut
        JOIN users u ON ut.user_id = u.id
        WHERE ut.tenant_id = :1 AND ut.status = 1
        ORDER BY ut.create_date DESC
        """
        logger.info("执行SQL: %s", query)
        logger.info("SQL参数: %s", (team_id,))

        cursor.execute(query, (team_id,))
        cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))
        results = cursor.fetchall()
        logger.info("执行结果: %s", results)

        cursor.close()
        conn.close()
        
        # 格式化结果
        formatted_members = []
        for member in results:
            # 将 role 转换为前端需要的格式
            role = "管理员" if member["ROLE"] == "owner" else "普通成员"
            formatted_members.append({
                "userId": member["USER_ID"],
                "username": member["NICKNAME"],
                "role": member["ROLE"],  # 保持原始角色值 "owner" 或 "normal"
                "joinTime": member["CREATE_DATE"].strftime("%Y-%m-%d %H:%M:%S") if member["CREATE_DATE"] else ""
            })
        
        return formatted_members
        
    except oracledb.DatabaseError as err: 
        logger.error("获取团队成员错误: %s", err)
        return []

def add_team_member(team_id, user_id, role="member"):
    """添加团队成员"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 检查用户是否已经是团队成员
        check_query = """
        SELECT id FROM user_tenant 
        WHERE tenant_id = :1 AND user_id = :2
        """
        cursor.execute(check_query, (team_id, user_id))
        existing = cursor.fetchone()
        
        if existing:
            # 如果已经是成员，更新角色
            update_query = """
            UPDATE user_tenant SET role = :1, status = 1
            WHERE tenant_id = :2 AND user_id = :3
            """
            cursor.execute(update_query, (role, team_id, user_id))
        else:
            # 如果不是成员，添加新记录
            current_datetime = datetime.now()
            create_time = int(current_datetime.timestamp() * 1000)
            current_date = current_datetime.strftime("%Y-%m-%d %H:%M:%S")
            
            insert_query = """
            INSERT INTO user_tenant (
                id, create_time, create_date, update_time, update_date, user_id,
                tenant_id, role, invited_by, status
            ) VALUES (
                TO_CHAR(:1),
                :2,
                TO_TIMESTAMP(:3, 'YYYY-MM-DD HH24:MI:SS'),
                :4,
                TO_TIMESTAMP(:5, 'YYYY-MM-DD HH24:MI:SS'),
                :6, :7, :8, :9, :10
            )
            """
            # 假设邀请者是系统管理员
            invited_by = "system"
            
            user_tenant_data = (
                generate_uuid(), create_time, current_date, create_time, current_date, user_id,
                team_id, role, invited_by, 1
            )
            cursor.execute(insert_query, user_tenant_data)
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return True
        
    except oracledb.DatabaseError as err: 
        logger.error("添加团队成员错误: %s", err)
        print(f"添加团队成员错误: {err}")
        return False

def remove_team_member(team_id, user_id):
    """移除团队成员"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 检查是否是团队的唯一所有者
        check_owner_query = """
        SELECT COUNT(*) as owner_count FROM user_tenant 
        WHERE tenant_id = :1 AND role = 'owner'
        """
        cursor.execute(check_owner_query, (team_id,))
        owner_count = cursor.fetchone()[0]
        
        # 检查当前用户是否是所有者
        check_user_role_query = """
        SELECT role FROM user_tenant 
        WHERE tenant_id = :1 AND user_id = :2
        """
        cursor.execute(check_user_role_query, (team_id, user_id))
        user_role = cursor.fetchone()
        
        # 如果是唯一所有者，不允许移除
        if owner_count == 1 and user_role and user_role[0] == 'owner':
            return False
        
        # 移除成员
        delete_query = """
        DELETE FROM user_tenant 
        WHERE tenant_id = :1 AND user_id = :2
        """
        cursor.execute(delete_query, (team_id, user_id))
        affected_rows = cursor.rowcount
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return affected_rows > 0
        
    except oracledb.DatabaseError as err: 
        logger.error("移除团队成员错误: %s", err)
        return False
