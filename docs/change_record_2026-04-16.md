# Oracle 修改记录 2026-04-16

## 背景

今天的修改主要围绕 Oracle 适配、调试日志补充、参数绑定修复，以及管理端健康检查兼容性问题展开。

## 修改内容

### 1. 补充 Oracle 相关调试日志

为以下模块补充了 `DEBUG` 级别日志，覆盖连接初始化、建表、补充向量列、插入、查询、获取、更新、删除等主要执行路径：

- `api/db/oracle_ext.py`
- `rag/utils/oracle_conn.py`
- `memory/utils/oracle_conn.py`

同时增加了参数摘要输出逻辑，避免长文本和大向量直接刷满日志。

另外去掉了 `api/db/oracle_ext.py` 和 `rag/utils/oracle_conn.py` 中模块级 `logging.basicConfig(...)` 的副作用，避免库代码干扰全局日志初始化。

### 2. 修复 Oracle 分页场景下的参数绑定问题

问题现象：

- Peewee 生成的位置参数会先以序列形式传入；
- `LIMIT/OFFSET` 被重写为 Oracle 语法后，占位符在 SQL 中的出现顺序变化；
- `oracledb` 对序列绑定按“出现顺序”处理，不按 `:1/:2/:3` 数字标签语义处理；
- 导致 `OFFSET` 和 `FETCH NEXT` 参数绑定反转，分页查询结果异常。

修复方式：

- 在 `api/db/oracle_ext.py` 中将序列参数统一改写为命名绑定；
- 把 `:%d` 替换为 `:p1/:p2/:p3...`；
- 把原始参数序列同步转换为字典形式；
- 扩展 `LIMIT/OFFSET` 改写逻辑，使其支持命名占位符。

这样即使 SQL 被改写成：

```sql
OFFSET :p3 ROWS FETCH NEXT :p2 ROWS ONLY
```

绑定仍然保持正确。

### 3. 修正 Oracle 参数日志展示

之前日志里序列参数会显示成：

```text
params={0: ..., 1: ..., 2: ...}
```

这容易误导为 Oracle 实际使用了 `:0/:1/:2` 绑定。

现已调整为更贴近 Oracle 语义的展示方式，例如：

```text
params={':1': ..., ':2': ..., ':3': ...}
```

注意：这项改动仅影响日志展示，不影响执行逻辑。

### 4. 修复 `/api/v1/admin/services` 在 Oracle 下误执行 MySQL 语句

问题现象：

- 管理端服务列表接口会读取元数据库服务状态；
- 原有逻辑默认把元数据库当作 MySQL；
- 在 Oracle 环境下仍执行 `SHOW PROCESSLIST;`；
- 触发 `ORA-00900: invalid SQL statement`。

修复内容：

- 在 `api/utils/health_utils.py` 中新增通用元数据库探活函数 `get_meta_db_status()`，使用 `SELECT 1` 做基础检查；
- `get_mysql_status()` 在非 MySQL 环境下自动回退到通用探活；
- 在 `admin/server/config.py` 中为 `oracle` 增加独立的 `meta_data` 服务配置；
- 在 `admin/server/services.py` 中按 `DB_TYPE` 过滤 `meta_data` 服务，避免 Oracle 环境仍暴露 MySQL 配置项。

## 涉及文件

- `api/db/oracle_ext.py`
- `rag/utils/oracle_conn.py`
- `memory/utils/oracle_conn.py`
- `api/utils/health_utils.py`
- `admin/server/config.py`
- `admin/server/services.py`

## 验证情况

已完成的验证：

- `python -m py_compile api/db/oracle_ext.py`
- `python -m py_compile rag/utils/oracle_conn.py`
- `python -m py_compile memory/utils/oracle_conn.py`
- `python -m py_compile api/utils/health_utils.py admin/server/config.py admin/server/services.py`

未完成的验证：

- 未执行完整业务回归测试；
- 未执行 Oracle 集成测试；
- 未补充自动化单元测试。

## 当前结果

目前已经解决的问题包括：

- Oracle 关键路径缺少调试日志；
- Oracle 分页参数绑定错位；
- Oracle 参数日志展示误导；
- 管理端在 Oracle 下误执行 MySQL 的 `SHOW PROCESSLIST`。
