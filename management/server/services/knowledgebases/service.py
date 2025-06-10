import oracledb
import json
import threading 
import requests
import traceback
import time
from datetime import datetime
from management.server.utils import generate_uuid
from management.server.database import get_db_connection
# 解析相关模块
from .document_parser import perform_parse, _update_document_progress
import logging

# 配置日志（通常在应用启动时设置）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
# 用于存储进行中的顺序批量任务状态
# 结构: { kb_id: {"status": "running/completed/failed", "total": N, "current": M, "message": "...", "start_time": timestamp} }
SEQUENTIAL_BATCH_TASKS = {}

class KnowledgebaseService:

    @classmethod
    def get_knowledgebase_list(cls, page=1, size=10, name="", sort_by="create_time", sort_order="desc"):
        """获取知识库列表"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # 验证排序字段
            valid_sort_fields = ["name", "create_time", "create_date"]
            if sort_by not in valid_sort_fields:
                sort_by = "create_time"

            # 构建排序子句
            sort_clause = f"ORDER BY k.{sort_by} {sort_order.upper()}"

            query = """
                SELECT 
                    k.id, 
                    k.name, 
                    k.description, 
                    k.create_date,
                    k.update_date,
                    k.doc_num,
                    k.language,
                    k.permission
                FROM knowledgebase k
            """
            params = {}

            if name:
                query += " WHERE k.name LIKE :search_name"
                params["name"] = f"%{name}%"  # 直接使用参数名作为键

            query += " OFFSET :page_offset ROWS FETCH FIRST :page_size ROWS ONLY"
            params["page_offset"] = (page - 1) * size
            params["page_size"] = size

            # 日志记录（明确参数名和值）
            logger.info("get_knowledgebase_list SQL: %s", query)
            logger.info("get_knowledgebase_list params: %s", params)

            # 使用命名参数执行
            cursor.execute(query, params)
            cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))
            results = cursor.fetchall()

            logger.info("get_knowledgebase_list results: %s", results)
            # results
            formatted_km = [{k.lower(): v for k, v in item.items()} for item in results]
            for result in formatted_km:
                # 处理空描述
                # 确保使用正确的列名（如 "DESCRIPTION"）
                if not result.get("description"):  # 使用 get() 避免 KeyError
                    result["description"] = "暂无描述"
                if result.get("create_date"):
                    result["create_date"] = result["create_date"].strftime("%Y-%m-%d %H:%M:%S")

            # 获取总数
            count_query = "SELECT COUNT(*) as total FROM knowledgebase"
            if name:
                count_query += " WHERE name LIKE :name"
            cursor.execute(count_query, {'name': f"%{name}%"} if name else {})
            total = cursor.fetchone()[0]

            cursor.close()
            conn.close()

            logger.info("get_knowledgebase_list results: %s", formatted_km)
            return {
                'list': formatted_km,
                'total': total
            }

        except oracledb.DatabaseError as err:
            logger.error("查询知识库列表错误: %s", err)
            print(f"查询知识库列表错误: {err}")
            return False

    @classmethod
    def get_knowledgebase_detail(cls, kb_id):
        """获取知识库详情"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            query = """
                SELECT 
                    k.id, 
                    k.name, 
                    k.description, 
                    k.create_date,
                    k.update_date,
                    k.doc_num
                FROM knowledgebase k
                WHERE k.id = :id
            """
            cursor.execute(query, {'id': kb_id})
            result = cursor.fetchone()
            formatted_km = []

            if result:
                # 处理空描述
                if not result.get('DESCRIPTION'):
                    result['DESCRIPTION'] = "暂无描述"
                # 处理时间格式
                # if result.get('CREATE_DATE'):
                #     if isinstance(result['CREATE_DATE'], datetime):
                #         result['CREATE_DATE'] = result['CREATE_DATE'].strftime('%Y-%m-%d %H:%M:%S')
                #     elif isinstance(result['CREATE_DATE'], str):
                #         try:
                #             datetime.strptime(result['CREATE_DATE'], '%Y-%m-%d %H:%M:%S')
                #         except ValueError:
                #             result['CREATE_DATE'] = ""

                formatted_km.append({
                    "id": result["ID"],
                    "name": result["NAME"],
                    "description": result["DESCRIPTION"],
                    "create_date": result["CREATE_DATE"].strftime("%Y-%m-%d %H:%M:%S") if result["CREATE_DATE"] else "",
                    "update_date": result["UPDATE_DATE"].strftime("%Y-%m-%d %H:%M:%S") if result["UPDATE_DATE"] else "",
                    "doc_num": result["DOC_NUM"]
                })

            cursor.close()
            conn.close()

            return formatted_km

        except oracledb.DatabaseError as err:
            logger.error("查询知识库列表错误: %s", err)
            print(f"查询知识库列表错误: {err}")
            return False

    @classmethod
    def _check_name_exists(cls, name):
        """检查知识库名称是否已存在"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = """
            SELECT COUNT(*) as count 
            FROM knowledgebase 
            WHERE name = :1
        """
        cursor.execute(query, (name,))
        result = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        return result[0] > 0

    @classmethod
    def create_knowledgebase(cls, **data):
        """创建知识库"""
        try:
            # 检查知识库名称是否已存在
            exists = cls._check_name_exists(data['name'])
            if exists:
                raise Exception("知识库名称已存在")
    
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # 获取最早的用户ID作为tenant_id和created_by
            tenant_id = data.get("creator_id")
            created_by = data.get("creator_id")

            if not tenant_id:
                # 如果没有提供 creator_id，则使用默认值
                print("未提供 creator_id，尝试获取最早用户 ID")
                try:
                    query_earliest_user = """
                    SELECT id FROM users
                    WHERE create_time = (SELECT MIN(create_time) FROM users)
                    FETCH FIRST 1 ROWS ONLY
                    """
                    cursor.execute(query_earliest_user)
                    cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))
                    earliest_user = cursor.fetchone()

                    if earliest_user:
                        tenant_id = earliest_user['ID']
                        created_by = earliest_user['ID']  # 使用最早用户ID作为created_by
                        print(f"使用创建时间最早的用户ID作为tenant_id和created_by: {tenant_id}")
                    else:
                        # 如果找不到用户，使用默认值
                        tenant_id = "system"
                        created_by = "system"
                        print(f"未找到用户, 使用默认值作为tenant_id和created_by: {tenant_id}")
                except Exception as e:
                    print(f"获取用户ID失败: {str(e)}，使用默认值")
                    tenant_id = "system"
                    created_by = "system"
            else:
                print(f"使用传入的 creator_id 作为 tenant_id 和 created_by: {tenant_id}")

            # --- 获取动态 embd_id ---
            dynamic_embd_id = None
            default_embd_id = 'bge-m3___VLLM@VLLM' # Fallback default
            try:
                query_embedding_model = """
                    SELECT llm_name
                    FROM tenant_llm
                    WHERE model_type = 'embedding'
                    ORDER BY create_time ASC
                    FETCH FIRST 1 ROWS ONLY
                """
                cursor.execute(query_embedding_model)
                cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))
                embedding_model = cursor.fetchone()

                if embedding_model and embedding_model.get('LLM_NAME'):
                    dynamic_embd_id = embedding_model['LLM_NAME']
                    print(f"动态获取到的 embedding 模型 ID: {dynamic_embd_id}")
                else:
                    dynamic_embd_id = default_embd_id
                    print(f"未在 tenant_llm 表中找到 embedding 模型, 使用默认值: {dynamic_embd_id}")
            except Exception as e:
                dynamic_embd_id = default_embd_id
                print(f"查询 embedding 模型失败: {str(e)}，使用默认值: {dynamic_embd_id}")
                traceback.print_exc()  # Log the full traceback for debugging

            current_time = datetime.now()
            create_date = current_time.strftime("%Y-%m-%d %H:%M:%S")
            create_time = int(current_time.timestamp() * 1000)  # 毫秒级时间戳
            update_date = create_date
            update_time = create_time
            
            # 完整的字段列表
            query = """
            INSERT INTO knowledgebase (
                id, create_time, create_date, update_time, update_date,
                avatar, tenant_id, name, language, description,
                embd_id, permission, created_by, doc_num, token_num,
                chunk_num, similarity_threshold, vector_similarity_weight, parser_id, parser_config,
                pagerank, status
            ) VALUES (
                TO_CHAR(:1),
                :2,
                TO_TIMESTAMP(:3, 'YYYY-MM-DD HH24:MI:SS'),
                :4,
                TO_TIMESTAMP(:5, 'YYYY-MM-DD HH24:MI:SS'),
                :6, :7, :8, :9, :10,
                :11, :12, :13, :14, :15,
                :16, :17, :18, :19, :20,
                :21, :22
            )
            """
            
            # 设置默认值
            default_parser_config = json.dumps({
                "layout_recognize": "MinerU", 
                "chunk_token_num": 512, 
                "delimiter": "\n!?;。；！？", 
                "auto_keywords": 0, 
                "auto_questions": 0, 
                "html4excel": False, 
                "raptor": {"use_raptor": False}, 
                "graphrag": {"use_graphrag": False}
            })
            
            kb_id = generate_uuid()
            cursor.execute(query, (
                kb_id,                                      # id
                create_time,                                # create_time
                create_date,                                # create_date
                update_time,                                # update_time
                update_date,                                # update_date
                None,                                       # avatar
                tenant_id,                                  # tenant_id
                data['name'],                               # name
                data['language'],            # language
                data['description'],                # description
                dynamic_embd_id,                            # embd_id
                data['permission'],               # permission
                created_by,                                 # created_by - 使用内部获取的值
                0,                                          # doc_num
                0,                                          # token_num
                0,                                          # chunk_num
                0.7,                                        # similarity_threshold
                0.3,                                        # vector_similarity_weight
                'naive',                                    # parser_id
                default_parser_config,                      # parser_config
                0,                                          # pagerank
                '1'                                         # status
            ))
            conn.commit()
            
            cursor.close()
            conn.close()
            
            # 返回创建后的知识库详情
            return cls.get_knowledgebase_detail(kb_id)
            
        except Exception as e:
            print(f"创建知识库失败: {str(e)}")
            raise Exception(f"创建知识库失败: {str(e)}")

    @classmethod
    def update_knowledgebase(cls, kb_id, **data):
        """更新知识库"""
        try:
            # 直接通过ID检查知识库是否存在
            kb = cls.get_knowledgebase_detail(kb_id)
            if not kb:
                return None
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # 如果要更新名称，先检查名称是否已存在
            if data.get('name') and data['name'] != kb['NAME']:
                exists = cls._check_name_exists(data['name'])
                if exists:
                    raise Exception("知识库名称已存在")
            
            # 构建更新语句
            update_fields = []
            params = {'id': kb_id}
            
            if data.get('name'):
                update_fields.append("name = :name")
                params['name'] = data['name']
                
            if 'description' in data:
                update_fields.append("description = :description")
                params['description'] = data['description']
            
            # 更新时间
            current_time = datetime.now()
            update_date = current_time.strftime('%Y-%m-%d %H:%M:%S')
            update_fields.append("update_date = :update_date")
            params['update_date'] = update_date
            
            # 如果没有要更新的字段，直接返回
            if not update_fields:
                return kb_id
                
            # 构建并执行更新语句
            query = f"""
                UPDATE knowledgebase 
                SET {", ".join(update_fields)}
                WHERE id = :id
            """

            cursor.execute(query, params)
            conn.commit()
            
            cursor.close()
            conn.close()
            
            # 返回更新后的知识库详情
            return cls.get_knowledgebase_detail(kb_id)
            
        except Exception as e:
            print(f"更新知识库失败: {str(e)}")
            raise Exception(f"更新知识库失败: {str(e)}")

    @classmethod
    def delete_knowledgebase(cls, kb_id):
        """删除知识库"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # 先检查知识库是否存在
            check_query = "SELECT id FROM knowledgebase WHERE id = :id"
            cursor.execute(check_query, {'id': kb_id})
            if not cursor.fetchone():
                raise Exception("知识库不存在")
            
            # 执行删除
            delete_query = "DELETE FROM knowledgebase WHERE id = :id"
            cursor.execute(delete_query, {'id': kb_id})
            conn.commit()
            
            cursor.close()
            conn.close()
            
            return True
        except Exception as e:
            print(f"删除知识库失败: {str(e)}")
            raise Exception(f"删除知识库失败: {str(e)}")

    @classmethod
    def batch_delete_knowledgebase(cls, kb_ids):
        """批量删除知识库"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # 检查所有ID是否存在
            placeholders = ', '.join([f':id_{i}' for i in range(len(kb_ids))])
            check_query = f"SELECT id FROM knowledgebase WHERE id IN ({placeholders})"
            params = {f'id_{i}': kb_id for i, kb_id in enumerate(kb_ids)}
            cursor.execute(check_query, params)
            existing_ids = [row[0] for row in cursor.fetchall()]

            if len(existing_ids) != len(kb_ids):
                missing_ids = set(kb_ids) - set(existing_ids)
                raise Exception(f"以下知识库不存在: {', '.join(missing_ids)}")

            # 执行批量删除
            delete_query = f"DELETE FROM knowledgebase WHERE id IN ({placeholders})"
            cursor.execute(delete_query, params)
            conn.commit()
            
            cursor.close()
            conn.close()
            
            return len(kb_ids)
        except Exception as e:
            print(f"批量删除知识库失败: {str(e)}")
            raise Exception(f"批量删除知识库失败: {str(e)}")

    @classmethod
    def get_knowledgebase_documents(cls, kb_id, page=1, size=10, name="", sort_by="create_time", sort_order="desc"):
        """获取知识库下的文档列表"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # 先检查知识库是否存在
            check_query = "SELECT id FROM knowledgebase WHERE id = :id"
            cursor.execute(check_query, {'id': kb_id})
            if not cursor.fetchone():
                raise Exception("知识库不存在")

            # 验证排序字段
            valid_sort_fields = ["name", "size", "create_time", "create_date"]
            if sort_by not in valid_sort_fields:
                sort_by = "create_time"

            # 构建排序子句
            sort_clause = f"ORDER BY d.{sort_by} {sort_order.upper()}"

            # 查询文档列表
            query = """
                SELECT 
                    d.id, 
                    d.name, 
                    d.chunk_num,
                    d.create_date,
                    d.status,
                    d.run,
                    d.progress
                FROM document d
               WHERE d.kb_id = :kb_id
            """
            params = {'kb_id': kb_id}
            
            if name:
                query += " AND d.name LIKE :name"
                params['name'] = f"%{name}%"

            # 添加查询排序条件
            query += f" {sort_clause}"

            query += " OFFSET :offset ROWS FETCH NEXT :fetch_size ROWS ONLY"
            params['offset'] = (page-1)*size
            params['fetch_size'] = size

            logger.info("get_knowledgebase_documents SQL: %s", query)
            logger.info("get_knowledgebase_documents params: %s", params)

            cursor.execute(query, params)
            cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))
            results = cursor.fetchall()
            low_results = [{k.lower(): v for k, v in item.items()} for item in results]

            for result in low_results:
                # 处理空描述
                if result.get("create_date"):
                    result["create_date"] = result["create_date"].strftime("%Y-%m-%d %H:%M:%S")

            logger.info("执行结果 low_results: %s", low_results)

            # 获取总数
            count_query = "SELECT COUNT(*) as total FROM document WHERE kb_id = :kb_id"
            count_params = {'kb_id': kb_id}
            if name:
                count_query += " AND name LIKE :name"
                count_params['name'] = f"%{name}%"

            logger.info("get_knowledgebase_documents count_query: %s", count_query)
            logger.info("get_knowledgebase_documents count_query: %s", count_params)

            cursor.execute(count_query, count_params)
            result = cursor.fetchone()
            if result:
                total = result[0]
            else:
                total = 0  # 或根据业务逻辑处理

            logger.info("get_knowledgebase_documents total: %s", total)
            cursor.close()
            conn.close()
            
            return {
                'list': low_results,
                'total': total
            }
        except Exception as e:
            print(f"获取知识库文档列表失败: {str(e)}")
            raise Exception(f"获取知识库文档列表失败: {str(e)}")

    @classmethod
    def add_documents_to_knowledgebase(cls, kb_id, file_ids, created_by=None):
        """添加文档到知识库"""
        try:
            print(f"[DEBUG] 开始添加文档，参数: kb_id={kb_id}, file_ids={file_ids}")
            
            # 如果没有传入created_by，则获取最早的用户ID
            if created_by is None:
                conn = get_db_connection()
                cursor = conn.cursor()
                
                # 查询创建时间最早的用户ID
                query_earliest_user = """
                SELECT id FROM users 
                WHERE create_time = (SELECT MIN(create_time) FROM users)
                FETCH FIRST 1 ROWS ONLY
                """
                cursor.execute(query_earliest_user)
                cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))
                earliest_user = cursor.fetchone()
                
                if earliest_user:
                    created_by = earliest_user[0]
                    print(f"使用创建时间最早的用户ID: {created_by}")
                else:
                    created_by = 'system'
                    print("未找到用户, 使用默认用户ID: system")
                    
                cursor.close()
                conn.close()
            
            # 检查知识库是否存在
            kb = cls.get_knowledgebase_detail(kb_id)
            print(f"[DEBUG] 知识库检查结果: {kb}")
            if not kb:
                print(f"[ERROR] 知识库不存在: {kb_id}")
                raise Exception("知识库不存在")
            
            conn = get_db_connection()
            cursor = conn.cursor()

            # 获取文件信息
            file_placeholders = ', '.join([f':id_{i}' for i in range(len(file_ids))])
            file_query = f"""
                SELECT id, name, location, size, type 
                FROM file 
                WHERE id IN ({file_placeholders})
            """
            file_params = {f'id_{i}': file_id for i, file_id in enumerate(file_ids)}

            print(f"[DEBUG] 执行文件查询SQL: {file_query}")
            print(f"[DEBUG] 查询参数: {file_params}")
            
            try:
                cursor.execute(file_query, file_params)
                cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))
                files = cursor.fetchall()
                print(f"[DEBUG] 查询到的文件数据: {files}")
            except Exception as e:
                print(f"[ERROR] 文件查询失败: {str(e)}")
                raise
            
            if len(files) != len(file_ids):
                print(f"部分文件不存在: 期望={len(file_ids)}, 实际={len(files)}")
                raise Exception("部分文件不存在")

            # 添加文档记录
            added_count = 0
            current_datetime = datetime.now()
            create_time = int(current_datetime.timestamp() * 1000)
            current_date = current_datetime.strftime("%Y-%m-%d %H:%M:%S")

            for file in files:
                file_id = file[0]
                file_name = file[1]
                print(f"处理文件: id={file_id}, name={file_name}")

                file_location = file[2]
                file_size = file[3]
                file_type = file[4]

                # 检查文档是否已存在于知识库
                check_query = """
                    SELECT COUNT(*) 
                    FROM document d
                    JOIN file2document f2d ON d.id = f2d.document_id
                    WHERE d.kb_id = :kb_id AND f2d.file_id = :file_id
                """
                cursor.execute(check_query, {'kb_id': kb_id, 'file_id': file_id})
                cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))
                exists = cursor.fetchone()[0] > 0
                
                if exists:
                    continue  # 跳过已存在的文档
                
                # 创建文档记录
                doc_id = generate_uuid()
                current_datetime = datetime.now()
                create_time = int(current_datetime.timestamp() * 1000)  # 毫秒级时间戳
                current_date = current_datetime.strftime("%Y-%m-%d %H:%M:%S")  # 格式化日期字符串
                
                # 设置默认值
                default_parser_id = "naive"
                default_parser_config = json.dumps({
                    "layout_recognize": "MinerU",
                    "chunk_token_num": 512,
                    "delimiter": "\n!?;。；！？",
                    "auto_keywords": 0,
                    "auto_questions": 0,
                    "html4excel": False,
                    "raptor": {
                        "use_raptor": False
                    },
                    "graphrag": {
                        "use_graphrag": False
                    }
                })
                default_source_type = "local"

                # 插入document表
                doc_query = """
                    INSERT INTO document (
                        id, create_time, create_date, update_time, update_date,
                        thumbnail, kb_id, parser_id, parser_config, source_type,
                        type, created_by, name, location, size,
                        token_num, chunk_num, progress, progress_msg, process_begin_at,
                        process_duation, meta_fields, run, status
                    ) VALUES (
                        :id, :create_time, :create_date, :update_time, :update_date,
                        :thumbnail, :kb_id, :parser_id, :parser_config, :source_type,
                        :type, :created_by, :name, :location, :size,
                        :token_num, :chunk_num, :progress, :progress_msg, :process_begin_at,
                        :process_duation, :meta_fields, :run, :status
                    )
                """

                doc_params = {
                    'id': doc_id,
                    'create_time': create_time,
                    'create_date': current_date,
                    'update_time': create_time,
                    'update_date': current_date,
                    'thumbnail': None,
                    'kb_id': kb_id,
                    'parser_id': default_parser_id,
                    'parser_config': default_parser_config,
                    'source_type': default_source_type,
                    'type': file_type,
                    'created_by': created_by,
                    'name': file_name,
                    'location': file_location,
                    'size': file_size,
                    'token_num': 0,
                    'chunk_num': 0,
                    'progress': 0.0,
                    'progress_msg': None,
                    'process_begin_at': None,
                    'process_duation': 0.0,
                    'meta_fields': None,
                    'run': '0',
                    'status': '1'
                }

                cursor.execute(doc_query, doc_params)
                cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))

                # 创建文件到文档的映射
                f2d_id = generate_uuid()
                f2d_query = """
                     INSERT INTO file2document (
                         id, create_time, create_date, update_time, update_date,
                         file_id, document_id
                     ) VALUES (
                         :id, :create_time, :create_date, :update_time, :update_date,
                         :file_id, :document_id
                     )
                 """

                f2d_params = {
                    'id': f2d_id,
                    'create_time': create_time,
                    'create_date': current_date,
                    'update_time': create_time,
                    'update_date': current_date,
                    'file_id': file_id,
                    'document_id': doc_id
                }

                cursor.execute(f2d_query, f2d_params)
                cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))
                added_count += 1

            # 更新知识库文档数量
            if added_count > 0:
                try:
                    update_query = """
                        UPDATE knowledgebase 
                        SET doc_num = doc_num + :added_count,
                            update_date = :update_date
                        WHERE id = :kb_id
                    """
                    cursor.execute(update_query, {
                        'added_count': added_count,
                        'update_date': current_date,
                        'kb_id': kb_id
                    })
                    conn.commit()
                except Exception as e:
                    print(f"[WARNING] 更新知识库文档数量失败，但文档已添加: {str(e)}")

            cursor.close()
            conn.close()
            
            return {
                "added_count": added_count
            }
            
        except Exception as e:
            print(f"[ERROR] 添加文档失败: {str(e)}")
            print(f"[ERROR] 错误类型: {type(e)}")
            import traceback
            print(f"[ERROR] 堆栈信息: {traceback.format_exc()}")
            raise Exception(f"添加文档到知识库失败: {str(e)}")

    @classmethod
    def delete_document(cls, doc_id):
        """删除文档"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # 先检查文档是否存在
            check_query = "SELECT kb_id FROM document WHERE id = :id"
            cursor.execute(check_query, {'id': doc_id})
            result = cursor.fetchone()
            
            if not result:
                raise Exception("文档不存在")
                
            kb_id = result[0]

            # 删除文件到文档的映射
            f2d_query = "DELETE FROM file2document WHERE document_id = :document_id"
            cursor.execute(f2d_query, {'document_id': doc_id})

            # 删除文档
            doc_query = "DELETE FROM document WHERE id = :id"
            cursor.execute(doc_query, {'id': doc_id})

            # 更新知识库文档数量
            update_query = """
                UPDATE knowledgebase 
                SET doc_num = doc_num - 1,
                    update_date = :update_date
                WHERE id = :kb_id
            """
            current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(update_query, {
                'update_date': current_date,
                'kb_id': kb_id
            })

            conn.commit()
            cursor.close()
            conn.close()
            
            return True
            
        except Exception as e:
            print(f"[ERROR] 删除文档失败: {str(e)}")
            raise Exception(f"删除文档失败: {str(e)}")

    @classmethod
    def parse_document(cls, doc_id):
        """解析文档（调用解析逻辑）"""
        conn = None
        cursor = None
        try:
            # 1. 获取文档和文件信息
            conn = get_db_connection()
            cursor = conn.cursor()

            # 查询文档信息
            doc_query = """
                SELECT d.id, d.name, d.location, d.type, d.kb_id, d.parser_id, d.parser_config, d.created_by
                FROM document d
                WHERE d.id = %s
            """
            cursor.execute(doc_query, (doc_id,))
            doc_info = cursor.fetchone()

            if not doc_info:
                raise Exception("文档不存在")

            # 获取关联的文件信息 (主要是 parent_id 作为 bucket_name)
            f2d_query = "SELECT file_id FROM file2document WHERE document_id = :1"
            cursor.execute(f2d_query, (doc_id,))
            f2d_result = cursor.fetchone()
            if not f2d_result:
                raise Exception("无法找到文件到文档的映射关系")
            file_id = f2d_result['file_id']

            file_query = "SELECT parent_id FROM file WHERE id = :1"
            cursor.execute(file_query, (file_id,))
            file_info = cursor.fetchone()
            if not file_info:
                raise Exception("无法找到文件记录")

            # 获取知识库创建人信息
            # 根据doc_id查询document这张表，得到kb_id
            kb_id_query = "SELECT kb_id FROM document WHERE id = :1"
            cursor.execute(kb_id_query, (doc_id,))
            kb_id = cursor.fetchone()
            # 根据kb_id查询knowledgebase这张表，得到created_by
            kb_query = "SELECT created_by FROM knowledgebase WHERE id = :1"
            cursor.execute(kb_query, (kb_id["kb_id"],))
            kb_info = cursor.fetchone()

            cursor.close()
            conn.close()
            conn = None # 确保连接已关闭

            # 2. 更新文档状态为处理中 (使用 parser 模块的函数)
            _update_document_progress(doc_id, status='2', run='1', progress=0.0, message='开始解析')

            # 3. 调用后台解析函数
            embedding_config = cls.get_system_embedding_config()
            parse_result = perform_parse(doc_id, doc_info, file_info, embedding_config)

            # 4. 返回解析结果
            return parse_result

        except Exception as e:
            print(f"文档解析启动或执行过程中出错 (Doc ID: {doc_id}): {str(e)}")
            # 确保在异常时更新状态为失败
            try:
                 _update_document_progress(doc_id, status='1', run='0', message=f"解析失败: {str(e)}")
            except Exception as update_err:
                 print(f"更新文档失败状态时出错 (Doc ID: {doc_id}): {str(update_err)}")
            # raise Exception(f"文档解析失败: {str(e)}")
            return {"success": False, "error": f"文档解析失败: {str(e)}"}

        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    @classmethod
    def async_parse_document(cls, doc_id):
        """异步解析文档"""
        try:
            # 启动后台线程执行同步的 parse_document 方法
            thread = threading.Thread(target=cls.parse_document, args=(doc_id,))
            thread.daemon = True # 设置为守护线程，主程序退出时线程也退出
            thread.start()

            # 立即返回，表示任务已提交
            return {
                "task_id": doc_id, # 使用 doc_id 作为任务标识符
                "status": "processing",
                "message": "文档解析任务已提交到后台处理"
            }
        except Exception as e:
            print(f"启动异步解析任务失败 (Doc ID: {doc_id}): {str(e)}")
            # 可以在这里尝试更新文档状态为失败
            try:
                 _update_document_progress(doc_id, status='1', run='0', message=f"启动解析失败: {str(e)}")
            except Exception as update_err:
                 print(f"更新文档启动失败状态时出错 (Doc ID: {doc_id}): {str(update_err)}")
            raise Exception(f"启动异步解析任务失败: {str(e)}")

    @classmethod    
    def get_document_parse_progress(cls, doc_id):
        """获取文档解析进度"""
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            query = """
                SELECT progress, progress_msg, status, run
                FROM document
                WHERE id = :doc_id
            """
            cursor.execute(query, {'doc_id': doc_id})
            result = cursor.fetchone()

            if not result:
                return {"error": "文档不存在"}

            # 确保 progress 是浮点数
            progress_value = 0.0
            if result.get("progress") is not None:
                try:
                    progress_value = float(result["progress"])
                except (ValueError, TypeError):
                    progress_value = 0.0  # 或记录错误

            return {
                "progress": progress_value,
                "message": result.get("progress_msg", ""),
                "status": result.get("status", "0"),
                "running": result.get("run", "0"),
            }

        except Exception as e:
            print(f"获取文档进度失败 (Doc ID: {doc_id}): {str(e)}")
            return {"error": f"获取进度失败: {str(e)}"}
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    # --- 获取最早用户 ID ---
    @classmethod
    def _get_earliest_user_tenant_id(cls):
        """获取创建时间最早的用户的 ID (作为 tenant_id)"""
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            query = """
                SELECT id FROM users 
                ORDER BY create_time ASC 
                FETCH FIRST 1 ROWS ONLY
            """
            cursor.execute(query)
            result = cursor.fetchone()
            if result:
                return result[0]  # 返回用户 ID
            else:
                print("警告: 数据库中没有用户！")
                return None
        except Exception as e:
            print(f"查询最早用户时出错: {e}")
            traceback.print_exc()
            return None
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    # ---  测试 Embedding 连接 ---
    @classmethod
    def _test_embedding_connection(cls, base_url, model_name, api_key):
        """
        测试与自定义 Embedding 模型的连接 (使用 requests)。
        """
        print(f"开始测试连接: base_url={base_url}, model_name={model_name}")
        try:
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            payload = {"input": ["Test connection"], "model": model_name}

            if not base_url.startswith(("http://", "https://")):
                base_url = "http://" + base_url
            if not base_url.endswith("/"):
                base_url += "/"

            # --- URL 拼接优化 ---
            endpoint_segment = "embeddings"
            full_endpoint_path = "v1/embeddings"
            # 移除末尾斜杠以方便判断
            normalized_base_url = base_url.rstrip("/")

            if normalized_base_url.endswith("/v1"):
                # 如果 base_url 已经是 http://host/v1 形式
                current_test_url = normalized_base_url + "/" + endpoint_segment
            elif normalized_base_url.endswith("/embeddings"):
                # 如果 base_url 已经是 http://host/embeddings 形式(比如硅基流动API，无需再进行处理)
                current_test_url = normalized_base_url
            else:
                # 如果 base_url 是 http://host 或 http://host/api 形式
                current_test_url = normalized_base_url + "/" + full_endpoint_path

            # --- 结束 URL 拼接优化 ---
            print(f"尝试请求 URL: {current_test_url}")
            try:
                response = requests.post(current_test_url, headers=headers, json=payload, timeout=15)
                print(f"请求 {current_test_url} 返回状态码: {response.status_code}")

                if response.status_code == 200:
                    res_json = response.json()
                    if (
                        "data" in res_json and isinstance(res_json["data"], list) and len(res_json["data"]) > 0 and "embedding" in res_json["data"][0] and len(res_json["data"][0]["embedding"]) > 0
                    ) or (isinstance(res_json, list) and len(res_json) > 0 and isinstance(res_json[0], list) and len(res_json[0]) > 0):
                        print(f"连接测试成功: {current_test_url}")
                        return True, "连接成功"
                    else:
                        print(f"连接成功但响应格式不正确于 {current_test_url}")

            except Exception as json_e:
                print(f"解析 JSON 响应失败于 {current_test_url}: {json_e}")

            return False, "连接失败: 响应错误"

        except Exception as e:
            print(f"连接测试发生未知错误: {str(e)}")
            traceback.print_exc()
            return False, f"测试时发生未知错误: {str(e)}"

    # --- 获取系统 Embedding 配置 ---
    @classmethod
    def get_system_embedding_config(cls):
        """获取系统级（最早用户）的 Embedding 配置"""
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor() # 使用字典游标方便访问列名

            # 1. 找到最早创建的用户ID
            query_earliest_user = """
                SELECT id FROM users
                ORDER BY create_time ASC
                FETCH FIRST 1 ROWS ONLY
            """
            cursor.execute(query_earliest_user)
            earliest_user = cursor.fetchone()

            if not earliest_user:
                # 如果没有用户，返回空配置
                return {
                     "llm_name": "",
                     "api_key": "",
                     "api_base": ""
                }

            earliest_user_id = earliest_user[0]

            # 2. 根据最早用户ID查询 tenant_llm 表中 model_type 为 embedding 的配置
            query_embedding_config = """
                    SELECT llm_name, api_key, api_base
                    FROM tenant_llm
                    WHERE tenant_id = :tenant_id AND model_type = 'embedding'
                    ORDER BY create_time DESC
                    FETCH FIRST 1 ROWS ONLY
                """
            cursor.execute(query_embedding_config, {'tenant_id': earliest_user_id} )
            cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))
            config = cursor.fetchone()
            # 日志记录（明确参数名和值）
            logger.info("query_embedding_config config: %s", config)

            if config:
                llm_name = config.get("LLM_NAME", "")
                api_key = config.get("API_KEY", "")
                api_base = config.get("API_BASE", "")
                # 对模型名称进行处理 (可选，根据需要保留或移除)
                if llm_name and "___" in llm_name:
                    llm_name = llm_name.split("___")[0]

                # (对硅基流动平台进行特异性处理)
                if llm_name == "netease-youdao/bce-embedding-base_v1":
                    llm_name = "BAAI/bge-m3"

                # 如果 API 基础地址为空字符串，设置为硅基流动嵌入模型的 API 地址
                if api_base == "":
                    api_base = "https://api.siliconflow.cn/v1/embeddings"

                # 如果有配置，返回
                return {"llm_name": llm_name, "api_key": api_key, "api_base": api_base}
            else:
                # 如果最早的用户没有 embedding 配置，返回空
                return {"llm_name": "", "api_key": "", "api_base": ""}
        except Exception as e:
            print(f"获取系统 Embedding 配置时出错: {e}")
            traceback.print_exc()
            # 保持原有的异常处理逻辑，向上抛出，让调用者处理
            raise Exception(f"获取配置时数据库出错: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
                
    # --- 设置系统 Embedding 配置 ---
    @classmethod
    def set_system_embedding_config(cls, llm_name, api_base, api_key):
        """设置系统级（最早用户）的 Embedding 配置"""
        tenant_id = cls._get_earliest_user_tenant_id()
        if not tenant_id:
            raise Exception("无法找到系统基础用户")

        print(f"开始设置系统 Embedding 配置: {llm_name}, {api_base}, {api_key}")
        # 执行连接测试
        is_connected, message = cls._test_embedding_connection(base_url=api_base, model_name=llm_name, api_key=api_key)

        if not is_connected:
            # 返回具体的测试失败原因给调用者（路由层）处理
            return False, f"连接测试失败: {message}"

        return True, f"连接成功: {message}"

    # 顺序批量解析 (核心逻辑，在后台线程运行)
    @classmethod
    def _run_sequential_batch_parse(cls, kb_id):
        """顺序执行批量解析，并在 SEQUENTIAL_BATCH_TASKS 中更新状态"""
        global SEQUENTIAL_BATCH_TASKS
        task_info = SEQUENTIAL_BATCH_TASKS.get(kb_id)
        if not task_info:
            print(f"[Seq Batch ERROR] Task info for KB {kb_id} not found at start.")
            return  # 理论上不应发生

        conn = None
        cursor = None
        parsed_count = 0
        failed_count = 0
        total_count = 0

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # 查询需要解析的文档
            # 注意：这里的条件要和前端期望的一致
            query = """
                SELECT id, name FROM document
                WHERE kb_id = :kb_id AND run != '3'
            """
            cursor.execute(query, {'kb_id': kb_id})

            documents_to_parse = cursor.fetchall()
            total_count = len(documents_to_parse)

            # 更新任务总数
            task_info["total"] = total_count
            task_info["status"] = "running"
            task_info["message"] = f"共找到 {total_count} 个文档待解析。"
            task_info["start_time"] = time.time()
            start_time = time.time()
            SEQUENTIAL_BATCH_TASKS[kb_id] = task_info # 更新字典

            if not documents_to_parse:
                task_info["status"] = "completed"
                task_info["message"] = "没有需要解析的文档。"
                SEQUENTIAL_BATCH_TASKS[kb_id] = task_info
                print(f"[Seq Batch] KB {kb_id}: 没有需要解析的文档。")
                return

            print(f"[Seq Batch] KB {kb_id}: 开始顺序解析 {total_count} 个文档...")

            # 按顺序解析每个文档
            for i, doc in enumerate(documents_to_parse):
                doc_id = doc['ID']
                doc_name = doc['NAME']

                # 更新当前进度
                task_info["current"] = i + 1
                task_info["message"] = f"正在解析: {doc_name} ({i+1}/{total_count})"
                SEQUENTIAL_BATCH_TASKS[kb_id] = task_info
                print(f"[Seq Batch] KB {kb_id}: ({i+1}/{total_count}) Parsing {doc_name} (ID: {doc_id})...")

                try:
                    # 调用同步的 parse_document 方法
                    # 这个方法内部会处理单个文档的状态更新 (run, status)
                    result = cls.parse_document(doc_id)
                    if result and result.get("success"):
                        parsed_count += 1
                        print(f"[Seq Batch] KB {kb_id}: Document {doc_id} parsed successfully.")
                    else:
                        failed_count += 1
                        error_msg = result.get("message", "未知错误") if result else "未知错误"
                        print(f"[Seq Batch] KB {kb_id}: Document {doc_id} parsing failed: {error_msg}")
                        # 即使单个失败，也继续处理下一个
                except Exception as e:
                    failed_count += 1
                    print(f"[Seq Batch ERROR] KB {kb_id}: Error calling parse_document for {doc_id}: {str(e)}")
                    traceback.print_exc()
                    # 尝试更新文档状态为失败，以防 parse_document 内部未处理
                    try:
                        _update_document_progress(doc_id, status="1", run="0", progress=0.0, message=f"批量任务中解析失败: {str(e)[:255]}")
                    except Exception as update_err:
                        print(f"[Service-ERROR] 更新文档 {doc_id} 失败状态时出错: {str(update_err)}")

            # 任务完成
            end_time = time.time()
            duration = round(end_time - task_info.get("start_time", start_time), 2)
            final_message = f"批量顺序解析完成。总计 {total_count} 个，成功 {parsed_count} 个，失败 {failed_count} 个。耗时 {duration} 秒。"
            task_info["status"] = "completed"
            task_info["message"] = final_message
            task_info["current"] = total_count
            SEQUENTIAL_BATCH_TASKS[kb_id] = task_info
            print(f"[Seq Batch] KB {kb_id}: {final_message}")

        except Exception as e:
            # 任务执行中发生严重错误
            error_message = f"批量顺序解析过程中发生严重错误: {str(e)}"
            print(f"[Seq Batch ERROR] KB {kb_id}: {error_message}")
            traceback.print_exc()
            task_info["status"] = "failed"
            task_info["message"] = error_message
            SEQUENTIAL_BATCH_TASKS[kb_id] = task_info
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    # 启动顺序批量解析 (异步请求)
    @classmethod
    def start_sequential_batch_parse_async(cls, kb_id):
        """异步启动知识库的顺序批量解析任务"""
        global SEQUENTIAL_BATCH_TASKS
        if kb_id in SEQUENTIAL_BATCH_TASKS and SEQUENTIAL_BATCH_TASKS[kb_id].get("status") == "running":
            return {"success": False, "message": "该知识库的批量解析任务已在运行中。"}

        # 初始化任务状态
        start_time = time.time()
        SEQUENTIAL_BATCH_TASKS[kb_id] = {
            "status": "starting",
            "total": 0,
            "current": 0,
            "message": "任务准备启动...",
            "start_time": start_time
        }

        try:
            # 启动后台线程执行顺序解析逻辑
            thread = threading.Thread(target=cls._run_sequential_batch_parse, args=(kb_id,))
            thread.daemon = True
            thread.start()
            print(f"[Seq Batch] KB {kb_id}: 已启动后台顺序解析线程。")

            return {"success": True, "message": "顺序批量解析任务已启动。"}

        except Exception as e:
            error_message = f"启动顺序批量解析任务失败: {str(e)}"
            print(f"[Seq Batch ERROR] KB {kb_id}: {error_message}")
            traceback.print_exc()
            # 更新任务状态为失败
            SEQUENTIAL_BATCH_TASKS[kb_id] = {
                "status": "failed",
                "total": 0,
                "current": 0,
                "message": error_message,
                "start_time": start_time
            }
            return {"success": False, "message": error_message}

    # 获取顺序批量解析进度
    @classmethod
    def get_sequential_batch_parse_progress(cls, kb_id):
        """获取指定知识库的顺序批量解析任务进度"""
        global SEQUENTIAL_BATCH_TASKS
        task_info = SEQUENTIAL_BATCH_TASKS.get(kb_id)

        if not task_info:
            return {"status": "not_found", "message": "未找到该知识库的批量解析任务记录。"}

        # 返回当前任务状态
        return task_info

    # 获取知识库所有文档状态 (用于刷新列表)
    @classmethod
    def get_knowledgebase_parse_progress(cls, kb_id):
        """获取指定知识库下所有文档的解析进度和状态 (保持不变)"""
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            query = """
                    SELECT id, name, progress, progress_msg, status, run
                    FROM document
                    WHERE kb_id = :kb_id
                    ORDER BY create_date DESC
                """
            cursor.execute(query, {'kb_id': kb_id})
            cursor.rowfactory = lambda *args: dict(zip([d[0] for d in cursor.description], args))
            documents = []
            for row in cursor:
                documents.append({
                    "id": row['ID'],
                    "name": row['NAME'],
                    "progress": float(row['PROGRESS']) if row['PROGRESS'] is not None else 0.0,
                    "progress_msg": row['PROGRESS_MSG'] if row['PROGRESS_MSG'] else "",
                    "status": row['STATUS'] if row['STATUS'] else "0",
                    "running": row['RUN'] if row['RUN'] else "0"
                })

            return {"documents": documents}
        except oracledb.DatabaseError as e:
            error, = e.args
            print(f"获取文档状态失败: [Code: {error.code}] {error.message}")
            return {"error": f"获取状态失败: {error.message}"}
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
