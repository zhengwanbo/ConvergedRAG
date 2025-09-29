
# 创建元数据库用户


```
sqlplus / as sysdba
show pdbs;

ALTER SYSTEM SET PROCESSES=500 SCOPE=SPFILE;
alter session set container=freepdb1;

create user conrag identified by conrag DEFAULT TABLESPACE users quota unlimited on users;
grant DB_DEVELOPER_ROLE to conrag;

```

# 创建向量数据库用户

```
sqlplus / as sysdba
show pdbs;
alter session set container=freepdb1;

create user ragvector identified by ragvector DEFAULT TABLESPACE users quota unlimited on users;
grant DB_DEVELOPER_ROLE to ragvector;


-- 验证文本检索index是否可以成功

sqlplus ragvector/ragvector@freepdb1

BEGIN
	CTX_DDL.CREATE_PREFERENCE('my_chinese_vgram_lexer', 'CHINESE_VGRAM_LEXER');
END;
/

BEGIN 
   CTX_DDL.CREATE_PREFERENCE('ragvector.world_lexer','WORLD_LEXER');
   END;
/

CREATE TABLE IF NOT EXISTS ttt (
    id varchar2(100)
    ,text CLOB
    ,meta JSON
    ,q_1024_vec vector NOT NULL
);


CREATE INDEX idx_docs_ttt ON ttt(text) INDEXTYPE IS CTXSYS.CONTEXT PARAMETERS ('LEXER sys.my_chinese_vgram_lexer');
```

# 检查配置文件

检查配置，根据配置修改 oracle IP和端口等信息。
```
ragflow:
host: 0.0.0.0
http_port: 9380

oracle:
name: 'rag_flow'
user: 'conrag'
password: 'conrag'
db: 'freepdb1'
host: 'localhost'
port: 1521
max_connections: 100
stale_timeout: 30

orclvector:
name: 'rag_vector'
user: 'ragvector'
password: 'ragvector'
db: 'freepdb1'
host: 'localhost'
port: 1521
max_connections: 100
stale_timeout: 30

minio:
user: 'rag_flow'
password: 'infini_rag_flow'
host: 'localhost:9000'

redis:
db: 1
password: 'infini_rag_flow'
host: 'localhost:6379'
```
