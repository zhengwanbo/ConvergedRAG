# Oracle 修改记录 2026-04-20

## 背景

本文档用于补充 `docs/oracle_change_record_2026-04-16.md` 之后的后续修改。

上一份记录已经覆盖的内容包括：

- Oracle 调试日志补充；
- Oracle 分页参数绑定修复；
- Oracle 参数日志展示修正；
- 管理端 `/api/v1/admin/services` 在 Oracle 下误执行 MySQL 语句的问题。

本次主要记录后续新增的 Oracle 适配工作，重点集中在元数据库兼容、文档存储接入、管理接口补充、前后端配置联动，以及相关测试补充。

## 修改内容

### 1. 补充 Oracle 基础配置、依赖和入口能力

为让系统能够完整识别 Oracle 作为元数据库和文档引擎，补充了以下内容：

- 在 `pyproject.toml` 中增加 `oracledb` 依赖；
- 在 `common/settings.py` 中增加 Oracle 相关配置加载逻辑：
  - 增加 `DOC_ENGINE_ORACLE` 标识；
  - 增加 `ORACLE`、`ORCLVECTOR` 配置项；
  - 支持把 Oracle 初始化为文档存储连接和记忆存储连接；
  - 默认 `DB_TYPE` / `DOC_ENGINE` 被切换为 `oracle`；
- 在 `conf/service_conf.yaml` 中新增 `oracle` 和 `orclvector` 配置段；
- 在 `api/apps/canvas_app.py` 中为数据库连通性测试增加 `oracle` 分支；
- 在 `web/src/pages/agent/options.ts` 中把 `oracle` 加入可选数据库类型列表。

这部分修改解决的是“配置已经写了，但应用初始化、前端下拉项和连通性测试路径仍不认识 Oracle”的问题。

### 2. 扩展 Peewee 元数据库层的 Oracle 兼容能力

本轮对 `api/db/db_models.py` 和相关数据库工具做了进一步适配，主要包括：

- 引入 `PooledOracleDatabase` 和 `OracleMigrator`，把 Oracle 纳入统一数据库枚举；
- 为 Oracle 增加带重试能力的连接池封装 `RetryingPooledOracleDatabase`；
- 为 Oracle 增加数据库锁封装 `OracleDatabaseLock`；
- `JSONField.python_value()` 增加 CLOB 读取逻辑，避免 Oracle 下 JSON 文本直接以 LOB 对象参与反序列化；
- 通过 `UpperCaseModelMeta` 统一模型表名和字段名的大写行为，适配 Oracle 更敏感的标识符规则；
- 调整部分模型字段的 `null/default` 行为，以及个别表名映射，降低 Oracle 下建表和插入失败概率；
- 抽出 `_run_migration_step()`，兼容 Oracle 迁移对象的执行方式；
- 在加列迁移时把 `ORA-01430` 视为可跳过的重复列错误。

同时，批量写入路径也补了 Oracle 兼容：

- `api/db/db_utils.py` 中，Oracle 的 `replace_on_conflict` 场景改为逐条插入并忽略唯一键重复；
- `api/db/services/common_service.py` 中，Oracle 批量新增改为逐条 `insert()`，避免 `insert_many()` 在 Oracle 场景下出现兼容性问题；
- `api/db/services/document_service.py` 中，对 `progress_msg` 增加空值保护，避免 Oracle 下读到空值后直接 `.strip()` 报错。

### 3. 接入 Oracle 文档存储和记忆存储实现

新增并接入了 Oracle 版文档存储实现：

- `rag/utils/oracle_conn.py`
- `memory/utils/oracle_conn.py`
- `conf/oracle_mapping.json`

这部分能力包括：

- 建表、建索引、检查索引是否存在；
- 向量列按需补充；
- 文本、JSON、列表、向量字段的编码与解码；
- 元数据过滤条件拼装；
- Oracle 下的检索、写入和健康检查；
- 记忆存储表的建表、插入、更新和向量字段管理。

为了让上层业务走通，还同步补了几个调用点：

- `rag/app/table.py` 中把 Oracle 纳入 `chunk_data` JSON 存储分支；
- `api/db/services/dialog_service.py` 中把 Oracle 纳入 SQL 生成与重试提示逻辑，按与 OceanBase 类似的 JSON 字段方式构造提示；
- `api/db/services/doc_metadata_service.py` 中新增 `_supports_native_es_metadata_ops()`，避免 Oracle 文档引擎仍误走原生 ES API；
- 元数据计数逻辑在非 ES/OS 场景下回退到搜索方案，而不是直接调用 `settings.docStoreConn.es`。

### 4. 补充 Oracle 管理端健康检查和状态接口

在管理侧继续补齐了 Oracle 相关服务可见性和状态检查能力：

- `api/utils/health_utils.py`
  - 新增 `get_oracle_status()`；
  - 新增通用元数据库探活 `get_meta_db_status()`；
  - `get_mysql_status()` 在非 MySQL 场景下自动回退；
- `api/apps/system_app.py`
  - 新增 `/oracle/status` 接口；
- `admin/server/config.py`
  - 新增 `OracleConfig`；
  - 加载服务配置时支持 `oracle` 类型的 `meta_data` 服务；
- `admin/server/services.py`
  - 在服务列表和服务详情中按 `DB_TYPE` 过滤 `meta_data` 服务，避免混出当前数据库类型不匹配的配置。

这部分和 2026-04-16 的修复相衔接，进一步把 Oracle 从“避免报错”推进到“可以在管理端正常识别和查看状态”。

### 5. 补充 Oracle SQL 改写相关单元测试

新增测试文件：

- `test/unit_test/utils/test_oracle_ext.py`

当前补充的用例主要覆盖：

- `FROM/JOIN ... AS alias` 改写为 Oracle 可接受的别名形式；
- 子查询外层别名去掉 `AS`；
- `LIMIT` 改写为 `FETCH FIRST` 语法。

这些测试主要用于保护 `api/db/oracle_ext.py` 中已经做过的 SQL 兼容改写逻辑，避免后续回归。

## 涉及文件

- `pyproject.toml`
- `common/settings.py`
- `conf/service_conf.yaml`
- `conf/oracle_mapping.json`
- `api/apps/canvas_app.py`
- `api/apps/system_app.py`
- `api/db/db_models.py`
- `api/db/db_utils.py`
- `api/db/services/common_service.py`
- `api/db/services/dialog_service.py`
- `api/db/services/doc_metadata_service.py`
- `api/db/services/document_service.py`
- `api/utils/health_utils.py`
- `rag/app/table.py`
- `rag/utils/oracle_conn.py`
- `memory/utils/oracle_conn.py`
- `web/src/pages/agent/options.ts`
- `test/unit_test/utils/test_oracle_ext.py`

## 验证情况

已完成的验证：

- `python -m py_compile api/db/db_models.py`
- `python -m py_compile api/db/db_utils.py`
- `python -m py_compile api/utils/health_utils.py`
- `python -m py_compile api/apps/canvas_app.py`
- `python -m py_compile api/apps/system_app.py`
- `python -m py_compile api/db/services/common_service.py`
- `python -m py_compile api/db/services/dialog_service.py`
- `python -m py_compile api/db/services/doc_metadata_service.py`
- `python -m py_compile api/db/services/document_service.py`
- `python -m py_compile common/settings.py`
- `python -m py_compile rag/app/table.py`

未完成的验证：

- 未执行完整 Oracle 集成测试；
- 未执行文档存储与向量检索联调；
- 未执行前端回归测试；
- `uv run python -m pytest test/unit_test/utils/test_oracle_ext.py` 无法执行，当前环境缺少 `pytest` 模块。

## 当前结果

截至目前，Oracle 适配已经从“局部 SQL 和管理端兼容”进一步扩展到以下范围：

- 应用配置层可以识别 Oracle 元数据库和 Oracle 文档引擎；
- Peewee 模型、迁移、批量写入和部分字段反序列化已经补上 Oracle 兼容逻辑；
- 文档存储、记忆存储、元数据管理和 SQL 查询提示链路已经接入 Oracle；
- 管理端和系统接口可以暴露 Oracle 状态信息；
- 已补充一组针对 Oracle SQL 改写逻辑的单元测试样例。

