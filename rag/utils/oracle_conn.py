#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
import copy
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import oracledb

from common import settings
from common.constants import PAGERANK_FLD, TAG_FLD
from common.decorator import singleton
from common.doc_store.doc_store_base import (
    DocStoreConnection,
    MatchExpr,
    MatchTextExpr,
    MatchDenseExpr,
    FusionExpr,
    OrderByExpr,
)
from common.file_utils import get_project_base_directory
from common.float_utils import get_float

logger = logging.getLogger("ragflow.oracle_conn")
logger.setLevel(logging.DEBUG)


STRING_LIST_FIELDS = {"important_kwd", "question_kwd", "tag_kwd", "source_id", "entities_kwd"}
JSON_TEXT_FIELDS = {"tag_feas", "chunk_data", "metadata", "extra"}
JSON_LIST_FIELDS = {"position_int", "page_num_int", "top_int"}
VECTOR_FIELD_PATTERN = re.compile(r"^q_(?P<vector_size>\d+)_vec$")
DEFAULT_FULLTEXT_FIELD = "content_ltks"
SCORE_ALIAS = "_score"
TEXT_FILTER_LABEL = 1


@dataclass
class SearchResult:
    total: int
    chunks: list[dict]


def _read_json_mapping() -> dict[str, dict[str, Any]]:
    # 定制开发：Wanbo 20250415
    mapping_path = os.path.join(get_project_base_directory(), "conf", "oracle_mapping.json")
    with open(mapping_path, "r", encoding="utf-8") as file:
        return json.load(file)


ORACLE_MAPPING = _read_json_mapping()


def _read_lob(value: Any) -> Any:
    if hasattr(value, "read"):
        return value.read()
    return value


def _escape_literal(value: str) -> str:
    return value.replace("'", "''")


def _normalize_identifier(name: str) -> str:
    return str(name).upper()


def _quote_identifier(name: str) -> str:
    return f'"{_normalize_identifier(name)}"'


def _encode_list(values: list[Any]) -> str:
    return "###".join([str(v) for v in values if v is not None and str(v) != ""])


def _decode_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None and str(v) != ""]
    if isinstance(value, str):
        return [v for v in value.split("###") if v]
    return [str(value)]


def _coerce_json_text(value: Any, default: Any):
    value = _read_lob(value)
    if value in (None, ""):
        return copy.deepcopy(default)
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return copy.deepcopy(default)


def _vector_to_param(value: Any) -> str:
    if hasattr(value, "tolist"):
        value = value.tolist()
    return json.dumps(list(value), ensure_ascii=False)


def _oracle_error_code(exc: Exception) -> int | None:
    if getattr(exc, "args", None):
        error = exc.args[0]
        code = getattr(error, "code", None)
        if isinstance(code, int):
            return code

    match = re.search(r"ORA-(\d+)", str(exc))
    if match:
        return int(match.group(1))
    return None


def _summarize_log_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
    if not params:
        return params

    summarized: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, str) and len(value) > 256:
            summarized[key] = f"{value[:256]}...({len(value)} chars)"
        elif isinstance(value, (list, tuple)) and len(value) > 16:
            summarized[key] = f"<{type(value).__name__} len={len(value)}>"
        else:
            summarized[key] = value
    return summarized


def _summarize_rows(rows: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for row in rows[:limit]:
        summary.append(
            {
                "id": row.get("id"),
                "doc_id": row.get("doc_id"),
                "kb_id": row.get("kb_id"),
                "docnm_kwd": row.get("docnm_kwd"),
                "_score": row.get("_score"),
                "doc_type_kwd": row.get("doc_type_kwd"),
                "content_preview": (row.get("content_with_weight") or "")[:120],
            }
        )
    return summary


def _decode_row(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, raw_value in row.items():
        value = _read_lob(raw_value)
        if key in STRING_LIST_FIELDS:
            result[key] = _decode_list(value)
        elif key == "content_with_weight":
            result[key] = value if value is not None else ""
        elif key in JSON_TEXT_FIELDS:
            result[key] = _coerce_json_text(value, {})
        elif key in JSON_LIST_FIELDS:
            result[key] = _coerce_json_text(value, [])
        elif VECTOR_FIELD_PATTERN.match(key):
            if hasattr(value, "tolist"):
                result[key] = value.tolist()
            elif isinstance(value, str):
                try:
                    result[key] = json.loads(value)
                except Exception:
                    result[key] = value
            else:
                result[key] = value
        else:
            result[key] = value
    return result


def _build_metadata_filter_expression(metadata_filtering_conditions: dict, params: dict[str, Any], prefix: str) -> str:
    if not metadata_filtering_conditions:
        return ""

    conditions = metadata_filtering_conditions.get("conditions", [])
    logical_operator = metadata_filtering_conditions.get("logical_operator", "and").upper()
    if not conditions:
        return ""

    expressions: list[str] = []
    for idx, condition in enumerate(conditions):
        name = condition.get("name")
        comparison_operator = condition.get("comparison_operator")
        value = condition.get("value")
        if not name or not comparison_operator:
            continue

        json_expr = f"JSON_VALUE(metadata, '$.{name}' RETURNING VARCHAR2(4000) NULL ON ERROR)"
        param_name = f"{prefix}_meta_{idx}"
        if comparison_operator == "empty":
            expressions.append(f"({json_expr} IS NULL OR {json_expr} = '')")
            continue
        if comparison_operator == "not empty":
            expressions.append(f"({json_expr} IS NOT NULL AND {json_expr} <> '')")
            continue

        params[param_name] = value
        if comparison_operator == "is":
            expressions.append(f"{json_expr} = :{param_name}")
        elif comparison_operator == "is not":
            expressions.append(f"NVL({json_expr}, '__NULL__') <> :{param_name}")
        elif comparison_operator == "contains":
            expressions.append(f"INSTR(LOWER({json_expr}), LOWER(:{param_name})) > 0")
        elif comparison_operator == "not contains":
            expressions.append(f"INSTR(LOWER(NVL({json_expr}, '')), LOWER(:{param_name})) = 0")
        elif comparison_operator == "start with":
            expressions.append(f"{json_expr} LIKE :{param_name} || '%'")
        elif comparison_operator == "end with":
            expressions.append(f"{json_expr} LIKE '%' || :{param_name}")
        elif comparison_operator in {"=", "≠", ">", "<", "≥", "≤"}:
            op_map = {"=": "=", "≠": "<>", ">": ">", "<": "<", "≥": ">=", "≤": "<="}
            expressions.append(
                f"TO_NUMBER(JSON_VALUE(metadata, '$.{name}' RETURNING VARCHAR2(4000) NULL ON ERROR)) {op_map[comparison_operator]} TO_NUMBER(:{param_name})"
            )
        elif comparison_operator == "before":
            expressions.append(
                f"TO_TIMESTAMP(JSON_VALUE(metadata, '$.{name}' RETURNING VARCHAR2(4000) NULL ON ERROR), 'YYYY-MM-DD\"T\"HH24:MI:SS') < TO_TIMESTAMP(:{param_name}, 'YYYY-MM-DD\"T\"HH24:MI:SS')"
            )
        elif comparison_operator == "after":
            expressions.append(
                f"TO_TIMESTAMP(JSON_VALUE(metadata, '$.{name}' RETURNING VARCHAR2(4000) NULL ON ERROR), 'YYYY-MM-DD\"T\"HH24:MI:SS') > TO_TIMESTAMP(:{param_name}, 'YYYY-MM-DD\"T\"HH24:MI:SS')"
            )

    if not expressions:
        return ""
    joiner = " AND " if logical_operator != "OR" else " OR "
    return "(" + joiner.join(expressions) + ")"


def _build_order_expression(field_name: str) -> str:
    quoted_field = _quote_identifier(field_name)
    if field_name in JSON_LIST_FIELDS:
        return (
            "TO_NUMBER("
            f"JSON_VALUE({quoted_field}, '$[0]' RETURNING VARCHAR2(4000) NULL ON ERROR)"
            ")"
        )
    return quoted_field


def _normalize_contains_query(query_text: str) -> str:
    if not query_text:
        return ""
    query_text = query_text.replace("###", " ")
    query_text = re.sub(r"\s+", " ", query_text).strip()
    return query_text


@singleton
class OracleConnection(DocStoreConnection):
    # 定制开发：Wanbo 20250415
    def __init__(self):
        self.info = {}
        self.oracle_config = settings.ORACLE.copy()
        self.vector_config = settings.ORCLVECTOR.copy() if getattr(settings, "ORCLVECTOR", None) else self.oracle_config.copy()
        self.conn_pool = None
        self._init_connection_pool()
        logger.info("Use Oracle %s:%s as the doc engine.", self.vector_config.get("host"), self.vector_config.get("port"))

    def _init_connection_pool(self):
        config = self.vector_config
        logger.debug(
            "OracleConnection._init_connection_pool dsn=%s:%s/%s user=%s max_connections=%s",
            config["host"],
            config["port"],
            config["db"],
            config["user"],
            config.get("max_connections", 16),
        )
        self.conn_pool = oracledb.create_pool(
            user=config["user"],
            password=config["password"],
            dsn=f"{config['host']}:{config['port']}/{config['db']}",
            min=1,
            max=config.get("max_connections", 16),
            increment=1,
        )

    def _get_conn(self):
        return self.conn_pool.acquire()

    @staticmethod
    def _is_doc_meta_table(index_name: str) -> bool:
        return index_name.lower().startswith("ragflow_doc_meta_")

    def _table_name(self, index_name: str, dataset_id: str | None = None) -> str:
        return _normalize_identifier(index_name)

    def _table_exists(self, table_name: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*)
                  FROM user_tables
                 WHERE table_name = UPPER(:table_name)
                """,
                {"table_name": table_name},
            )
            exists = cursor.fetchone()[0] > 0
            cursor.close()
            return exists

    def _list_object_types(self, object_name: str) -> list[str]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT object_type
                  FROM user_objects
                 WHERE object_name = UPPER(:object_name)
                """,
                {"object_name": object_name},
            )
            object_types = [row[0] for row in cursor.fetchall()]
            cursor.close()
            return object_types

    def _column_exists(self, table_name: str, column_name: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*)
                  FROM user_tab_columns
                 WHERE (table_name = UPPER(:table_name))
                   AND (column_name = UPPER(:column_name))
                """,
                {"table_name": table_name, "column_name": column_name},
            )
            exists = cursor.fetchone()[0] > 0
            cursor.close()
            return exists

    def _create_regular_index(self, table_name: str, column_name: str):
        normalized_column_name = _normalize_identifier(column_name)
        index_name = _normalize_identifier(f"IDX_{table_name[:20]}_{normalized_column_name[:20]}")
        sql = f'CREATE INDEX "{index_name}" ON {_quote_identifier(table_name)} ({_quote_identifier(normalized_column_name)})'
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql)
                conn.commit()
            except Exception:
                conn.rollback()
            finally:
                cursor.close()

    def _create_text_index(self, table_name: str, column_name: str):
        normalized_column_name = _normalize_identifier(column_name)
        index_name = _normalize_identifier(f"CTX_{table_name[:20]}_{normalized_column_name[:20]}")
        sql = (
            f'CREATE INDEX "{index_name}" ON {_quote_identifier(table_name)} ({_quote_identifier(normalized_column_name)}) '
            "INDEXTYPE IS CTXSYS.CONTEXT"
        )
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql)
                conn.commit()
            except Exception:
                conn.rollback()
                logger.warning("Skip Oracle Text index creation for %s.%s", table_name, column_name)
            finally:
                cursor.close()

    def _ensure_vector_column(self, table_name: str, vector_size: int):
        if vector_size <= 0:
            return
        column_name = _normalize_identifier(f"q_{vector_size}_vec")
        if self._column_exists(table_name, column_name):
            return
        sql = f'ALTER TABLE {_quote_identifier(table_name)} ADD ({_quote_identifier(column_name)} VECTOR({vector_size}, FLOAT32))'
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql)
                conn.commit()
            except Exception as e:
                conn.rollback()
                if "ORA-01430" not in str(e):
                    raise
                logger.debug("Oracle vector column already exists: %s.%s", table_name, column_name)
            finally:
                cursor.close()

    def db_type(self) -> str:
        return "oracle"

    def health(self) -> dict:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM DUAL")
            row = cursor.fetchone()
            cursor.close()
            return {
                "type": "oracle",
                "status": "green" if row and row[0] == 1 else "red",
                "uri": f"{self.vector_config['host']}:{self.vector_config['port']}/{self.vector_config['db']}",
            }

    def create_idx(self, index_name: str, dataset_id: str, vector_size: int, parser_id: str = None):
        table_name = self._table_name(index_name, dataset_id)
        if self._table_exists(table_name):
            self._ensure_vector_column(table_name, vector_size)
            return True

        schema = copy.deepcopy(ORACLE_MAPPING)
        if vector_size > 0:
            schema[f"q_{vector_size}_vec"] = {"type": f"VECTOR({vector_size}, FLOAT32)"}

        column_sql: list[str] = []
        for column_name, config in schema.items():
            default = config.get("default")
            segment = f'{_quote_identifier(column_name)} {config["type"]}'
            if default is not None:
                if isinstance(default, str):
                    segment += f" DEFAULT '{_escape_literal(default)}'"
                else:
                    segment += f" DEFAULT {default}"
            column_sql.append(segment)

        create_sql = f'CREATE TABLE {_quote_identifier(table_name)} ({", ".join(column_sql)}, PRIMARY KEY ({_quote_identifier("id")}))'
        logger.debug("OracleConnection.create_idx table=%s vector_size=%s sql=%s", table_name, vector_size, create_sql)
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(create_sql)
                conn.commit()
            except Exception as e:
                conn.rollback()
                if _oracle_error_code(e) != 955:
                    raise
                if not self._table_exists(table_name):
                    object_types = ", ".join(self._list_object_types(table_name)) or "unknown object"
                    raise RuntimeError(
                        f'Oracle object name conflict for "{table_name}": existing {object_types} prevents table creation'
                    ) from e
                logger.debug("Oracle index table already exists: %s", table_name)
            finally:
                cursor.close()

        self._ensure_vector_column(table_name, vector_size)

        for column_name in ["kb_id", "doc_id", "available_int", "knowledge_graph_kwd", "entity_type_kwd", "removed_kwd"]:
            self._create_regular_index(table_name, column_name)
        self._create_text_index(table_name, DEFAULT_FULLTEXT_FIELD)
        return True

    def create_doc_meta_idx(self, index_name: str):
        table_name = self._table_name(index_name)
        if self._table_exists(table_name):
            return True
        create_sql = (
            f'CREATE TABLE {_quote_identifier(table_name)} ('
            f'{_quote_identifier("id")} VARCHAR2(256) PRIMARY KEY, '
            f'{_quote_identifier("kb_id")} VARCHAR2(256) NOT NULL, '
            f'{_quote_identifier("meta_fields")} CLOB DEFAULT \'{{}}\''
            ")"
        )
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(create_sql)
                conn.commit()
            except Exception as e:
                conn.rollback()
                if _oracle_error_code(e) != 955:
                    raise
                if not self._table_exists(table_name):
                    object_types = ", ".join(self._list_object_types(table_name)) or "unknown object"
                    raise RuntimeError(
                        f'Oracle object name conflict for "{table_name}": existing {object_types} prevents table creation'
                    ) from e
                logger.debug("Oracle metadata table already exists: %s", table_name)
            finally:
                cursor.close()
        self._create_regular_index(table_name, "kb_id")
        return True

    def delete_idx(self, index_name: str, dataset_id: str):
        table_name = self._table_name(index_name, dataset_id)
        if dataset_id and not self._is_doc_meta_table(index_name):
            return True
        if not self._table_exists(table_name):
            return True
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(f'DROP TABLE {_quote_identifier(table_name)} CASCADE CONSTRAINTS')
            conn.commit()
            cursor.close()
        return True

    def index_exist(self, index_name: str, dataset_id: str = None) -> bool:
        return self._table_exists(self._table_name(index_name, dataset_id))

    def _prepare_doc_for_insert(self, document: dict[str, Any]) -> dict[str, Any]:
        d: dict[str, Any] = {}
        extra = copy.deepcopy(document.get("extra") or {})
        for key, value in document.items():
            if VECTOR_FIELD_PATTERN.match(key):
                d[key] = _vector_to_param(value)
                continue
            if key not in ORACLE_MAPPING:
                extra[key] = value
                continue
            if value is None:
                continue
            if key in STRING_LIST_FIELDS and isinstance(value, list):
                d[key] = _encode_list(value)
            elif key in JSON_TEXT_FIELDS:
                d[key] = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
            elif key in JSON_LIST_FIELDS:
                d[key] = json.dumps(value, ensure_ascii=False)
            elif key == "kb_id" and isinstance(value, list):
                d[key] = value[0] if value else ""
            else:
                d[key] = value

        if extra:
            d["extra"] = json.dumps(extra, ensure_ascii=False)

        metadata = _coerce_json_text(d.get("metadata"), {})
        if d.get("doc_id"):
            d["group_id"] = metadata.get("_group_id") or d.get("doc_id")
            if metadata.get("_title"):
                d["docnm_kwd"] = metadata["_title"]

        return d

    def insert(self, rows: list[dict], index_name: str, dataset_id: str = None) -> list[str]:
        if not rows:
            return []

        table_name = self._table_name(index_name, dataset_id)
        if not self._table_exists(table_name):
            vector_size = 0
            for key in rows[0].keys():
                match = VECTOR_FIELD_PATTERN.match(key)
                if match:
                    vector_size = int(match.group("vector_size"))
                    break
            if self._is_doc_meta_table(index_name):
                self.create_doc_meta_idx(index_name)
            else:
                self.create_idx(index_name, dataset_id or "", vector_size)

        for key in rows[0].keys():
            match = VECTOR_FIELD_PATTERN.match(key)
            if match:
                self._ensure_vector_column(table_name, int(match.group("vector_size")))

        docs = [self._prepare_doc_for_insert(row) for row in rows]
        columns = sorted({key for doc in docs for key in doc.keys()})
        source_projection = ", ".join([f':{column} AS {_quote_identifier(column)}' for column in columns])
        update_projection = ", ".join([f't.{_quote_identifier(column)} = s.{_quote_identifier(column)}' for column in columns if column != "id"])
        insert_columns = ", ".join([_quote_identifier(column) for column in columns])
        insert_values = ", ".join([f's.{_quote_identifier(column)}' for column in columns])
        merge_sql = (
            f'MERGE INTO {_quote_identifier(table_name)} t '
            f'USING (SELECT {source_projection} FROM DUAL) s '
            f'ON (t.{_quote_identifier("id")} = s.{_quote_identifier("id")}) '
            f'WHEN MATCHED THEN UPDATE SET {update_projection} '
            f'WHEN NOT MATCHED THEN INSERT ({insert_columns}) '
            f'VALUES ({insert_values})'
        )
        logger.debug(
            "OracleConnection.insert table=%s rows=%s columns=%s sql=%s",
            table_name,
            len(docs),
            columns,
            merge_sql,
        )

        with self._get_conn() as conn:
            cursor = conn.cursor()
            for doc in docs:
                params = {column: doc.get(column) for column in columns}
                logger.debug("OracleConnection.insert params=%s", _summarize_log_params(params))
                cursor.execute(merge_sql, params)
            conn.commit()
            cursor.close()
        return []

    def _build_filters(self, condition: dict, params: dict[str, Any], prefix: str) -> list[str]:
        filters: list[str] = []
        for key, value in condition.items():
            if value in (None, [], {}, ""):
                continue
            if key == "exists":
                filters.append(f'{_quote_identifier(value)} IS NOT NULL')
                continue
            if key == "must_not" and isinstance(value, dict) and "exists" in value:
                filters.append(f'{_quote_identifier(value["exists"])} IS NULL')
                continue
            if key == "metadata_filtering_conditions":
                metadata_expr = _build_metadata_filter_expression(value, params, prefix)
                if metadata_expr:
                    filters.append(metadata_expr)
                continue

            if key in STRING_LIST_FIELDS:
                values = value if isinstance(value, list) else [value]
                parts: list[str] = []
                for idx, item in enumerate(values):
                    param_name = f"{prefix}_{key}_{idx}"
                    params[param_name] = str(item)
                    parts.append(f"INSTR('###' || NVL({_quote_identifier(key)}, '') || '###', '###' || :{param_name} || '###') > 0")
                filters.append("(" + " OR ".join(parts) + ")")
                continue

            if isinstance(value, list):
                placeholders = []
                for idx, item in enumerate(value):
                    param_name = f"{prefix}_{key}_{idx}"
                    params[param_name] = item
                    placeholders.append(f":{param_name}")
                filters.append(f'{_quote_identifier(key)} IN ({", ".join(placeholders)})')
            else:
                param_name = f"{prefix}_{key}"
                params[param_name] = value
                filters.append(f'{_quote_identifier(key)} = :{param_name}')
        return filters

    def _row_to_dict(self, cursor, row) -> dict[str, Any]:
        columns = [item[0].lower() for item in cursor.description]
        raw = {columns[idx]: row[idx] for idx in range(len(columns))}
        return _decode_row(raw)

    def search(
        self,
        select_fields: list[str],
        highlight_fields: list[str],
        condition: dict,
        match_expressions: list[MatchExpr],
        order_by: OrderByExpr,
        offset: int,
        limit: int,
        index_names: str | list[str],
        dataset_ids: list[str] | None = None,
        agg_fields: list[str] | None = None,
        rank_feature: dict | None = None,
        **kwargs,
    ):
        if dataset_ids is None:
            dataset_ids = kwargs.pop("knowledgebase_ids", None)
        if kwargs:
            raise TypeError(
                f"OracleConnection.search() got unexpected keyword arguments: {', '.join(kwargs.keys())}"
            )
        dataset_ids = dataset_ids or []
        if isinstance(index_names, str):
            index_names = index_names.split(",")
        agg_fields = agg_fields or []
        result = SearchResult(total=0, chunks=[])

        for index_name in index_names:
            table_name = self._table_name(index_name)
            if not self._table_exists(table_name):
                continue

            current_condition = copy.deepcopy(condition or {})
            if not self._is_doc_meta_table(index_name) and dataset_ids and "kb_id" not in current_condition:
                current_condition["kb_id"] = dataset_ids

            params: dict[str, Any] = {}
            filters = self._build_filters(current_condition, params, f"f_{len(result.chunks)}")
            where_sql = " AND ".join(filters) if filters else "1=1"

            output_fields = list(select_fields or [])
            if "*" not in output_fields:
                if "id" not in output_fields:
                    output_fields = ["id"] + output_fields
                for field in highlight_fields or []:
                    if field not in output_fields:
                        output_fields.append(field)
                if any(isinstance(expr, (MatchTextExpr, MatchDenseExpr, FusionExpr)) for expr in match_expressions):
                    if "_score" not in output_fields:
                        output_fields.append("_score")
            select_sql = "*" if "*" in output_fields else ", ".join([_quote_identifier(field) for field in output_fields if field != "_score"])

            text_expr = None
            text_filter_expr = None
            text_score_expr = None
            vector_expr = None
            vector_score_expr = None
            score_expr = None
            order_sql = ""
            vector_similarity_threshold = None
            vector_weight = 0.95
            has_fusion = any(isinstance(expr, FusionExpr) for expr in match_expressions)

            for expr in match_expressions:
                if isinstance(expr, MatchTextExpr):
                    text_query = expr.extra_options.get("original_query") if expr.extra_options else expr.matching_text
                    text_query = _normalize_contains_query(text_query or expr.matching_text)
                    params["text_query"] = text_query.strip() or _normalize_contains_query(expr.matching_text)
                    text_expr = f'CONTAINS({_quote_identifier(DEFAULT_FULLTEXT_FIELD)}, :text_query, {TEXT_FILTER_LABEL})'
                    text_filter_expr = f"{text_expr} > 0"
                    text_score_expr = f"NVL(SCORE({TEXT_FILTER_LABEL}), 0)"
                elif isinstance(expr, MatchDenseExpr):
                    params["vector_query"] = _vector_to_param(expr.embedding_data)
                    vector_similarity_threshold = expr.extra_options.get("similarity", 0.0) if expr.extra_options else 0.0
                    vector_expr = f'VECTOR_DISTANCE({_quote_identifier(expr.vector_column_name)}, :vector_query, COSINE)'
                    vector_score_expr = f"(1 - {vector_expr})"
                elif isinstance(expr, FusionExpr):
                    weights = (expr.fusion_params or {}).get("weights", "0.05,0.95").split(",")
                    vector_weight = get_float(weights[1]) if len(weights) > 1 else 0.95

            where_clauses = [where_sql]
            if text_filter_expr and vector_expr and vector_similarity_threshold is not None and has_fusion:
                params["vector_similarity_threshold"] = vector_similarity_threshold
                where_clauses.append(f"({text_filter_expr} OR {vector_score_expr} >= :vector_similarity_threshold)")
            else:
                if text_filter_expr:
                    where_clauses.append(text_filter_expr)
                if vector_expr and vector_similarity_threshold is not None:
                    where_clauses.append(f"{vector_score_expr} >= :vector_similarity_threshold")
                    params["vector_similarity_threshold"] = vector_similarity_threshold

            if text_expr and vector_expr:
                score_expr = f"({text_score_expr} * {1 - vector_weight} + {vector_score_expr} * {vector_weight} + NVL({_quote_identifier(PAGERANK_FLD)}, 0) / 100)"
                order_sql = f" ORDER BY {_quote_identifier(SCORE_ALIAS)} DESC"
            elif text_expr:
                score_expr = text_score_expr
                order_sql = f" ORDER BY {_quote_identifier(SCORE_ALIAS)} DESC"
            elif vector_expr:
                score_expr = vector_score_expr
                order_sql = f" ORDER BY {_quote_identifier(SCORE_ALIAS)} DESC"
            elif agg_fields:
                agg_field = agg_fields[0]
                sql = (
                    f'SELECT {_quote_identifier(agg_field)}, COUNT(1) AS count FROM {_quote_identifier(table_name)} '
                    f'WHERE {" AND ".join(where_clauses)} '
                    f'GROUP BY {_quote_identifier(agg_field)}'
                )
                with self._get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute(sql, params)
                    rows = cursor.fetchall()
                    cursor.close()
                for value, count in rows:
                    decoded = _decode_list(_read_lob(value)) if agg_field in STRING_LIST_FIELDS else [_read_lob(value)]
                    for item in decoded:
                        if item not in ("", None):
                            result.chunks.append({"value": item, "count": int(count)})
                            result.total += 1
                continue
            elif order_by and getattr(order_by, "fields", None):
                order_parts = [f'{_build_order_expression(field)} {"ASC" if order == 0 else "DESC"}' for field, order in order_by.fields]
                order_sql = " ORDER BY " + ", ".join(order_parts)

            count_sql = f'SELECT COUNT(1) FROM {_quote_identifier(table_name)} WHERE {" AND ".join(where_clauses)}'
            logger.debug(
                "OracleConnection.search count_sql=%s params=%s",
                count_sql,
                _summarize_log_params(params),
            )
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(count_sql, params)
                total = cursor.fetchone()[0]
                cursor.close()
            logger.debug(
                "OracleConnection.search count_result table=%s total=%s",
                table_name,
                total,
            )
            result.total += int(total or 0)
            if not total:
                continue

            projection = select_sql if "*" == select_sql else select_sql
            if score_expr:
                projection = f"{projection}, {score_expr} AS {_quote_identifier(SCORE_ALIAS)}"

            query_sql = f'SELECT {projection} FROM {_quote_identifier(table_name)} WHERE {" AND ".join(where_clauses)}{order_sql}'
            if limit > 0:
                params["offset_value"] = offset
                params["limit_value"] = limit
                query_sql += " OFFSET :offset_value ROWS FETCH NEXT :limit_value ROWS ONLY"
            logger.debug(
                "OracleConnection.search query_sql=%s params=%s",
                query_sql,
                _summarize_log_params(params),
            )

            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(query_sql, params)
                rows = cursor.fetchall()
                decoded_rows: list[dict[str, Any]] = []
                for row in rows:
                    decoded = self._row_to_dict(cursor, row)
                    decoded_rows.append(decoded)
                    result.chunks.append(decoded)
                cursor.close()
            logger.debug(
                "OracleConnection.search rows_result table=%s fetched=%s sample=%s",
                table_name,
                len(decoded_rows),
                _summarize_rows(decoded_rows),
            )

        if result.total == 0:
            result.total = len(result.chunks)
        return result

    def get(self, data_id: str, index_name: str, dataset_ids: list[str] | None = None, **kwargs) -> dict | None:
        if dataset_ids is None:
            dataset_ids = kwargs.pop("knowledgebase_ids", None)
        if kwargs:
            raise TypeError(
                f"OracleConnection.get() got unexpected keyword arguments: {', '.join(kwargs.keys())}"
            )
        dataset_ids = dataset_ids or []
        table_name = self._table_name(index_name)
        if not self._table_exists(table_name):
            return None

        params = {"id": data_id}
        sql = f'SELECT * FROM {_quote_identifier(table_name)} WHERE {_quote_identifier("id")} = :id'
        if dataset_ids and not self._is_doc_meta_table(index_name):
            kb_params = []
            for idx, kb_id in enumerate(dataset_ids):
                key = f"kb_{idx}"
                params[key] = kb_id
                kb_params.append(f":{key}")
            sql += f' AND {_quote_identifier("kb_id")} IN ({", ".join(kb_params)})'
        logger.debug("OracleConnection.get sql=%s params=%s", sql, _summarize_log_params(params))

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            row = cursor.fetchone()
            if not row:
                cursor.close()
                return None
            doc = self._row_to_dict(cursor, row)
            cursor.close()
            return doc

    def update(self, condition: dict, new_value: dict, index_name: str, dataset_id: str) -> bool:
        table_name = self._table_name(index_name)
        if not self._table_exists(table_name):
            return True

        current_condition = copy.deepcopy(condition or {})
        if dataset_id and not self._is_doc_meta_table(index_name):
            current_condition["kb_id"] = dataset_id

        search_res = self.search(["id"] + list(STRING_LIST_FIELDS) + ["metadata", "doc_id", "docnm_kwd"], [], current_condition, [], OrderByExpr(), 0, 2048, index_name, [dataset_id] if dataset_id else [])
        if not search_res.chunks:
            return True

        with self._get_conn() as conn:
            cursor = conn.cursor()
            for row in search_res.chunks:
                updates = copy.deepcopy(new_value)
                if "remove" in updates:
                    for field_name, field_value in updates.pop("remove").items():
                        current_values = _decode_list(row.get(field_name))
                        current_values = [item for item in current_values if item != str(field_value)]
                        updates[field_name] = current_values
                if "add" in updates:
                    for field_name, field_value in updates.pop("add").items():
                        current_values = _decode_list(row.get(field_name))
                        if str(field_value) not in current_values:
                            current_values.append(str(field_value))
                        updates[field_name] = current_values

                if "metadata" in updates and isinstance(updates["metadata"], dict):
                    metadata = updates["metadata"]
                    if metadata.get("_group_id"):
                        updates["group_id"] = metadata["_group_id"]
                    if metadata.get("_title"):
                        updates["docnm_kwd"] = metadata["_title"]

                params = {"id": row["id"]}
                assignments: list[str] = []
                for key, value in updates.items():
                    if key in STRING_LIST_FIELDS and isinstance(value, list):
                        params[key] = _encode_list(value)
                    elif key in JSON_TEXT_FIELDS or key in JSON_LIST_FIELDS:
                        params[key] = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
                    else:
                        params[key] = value
                    assignments.append(f'{_quote_identifier(key)} = :{key}')

                if not assignments:
                    continue

                sql = f'UPDATE {_quote_identifier(table_name)} SET {", ".join(assignments)} WHERE {_quote_identifier("id")} = :id'
                logger.debug("OracleConnection.update sql=%s params=%s", sql, _summarize_log_params(params))
                cursor.execute(sql, params)
            conn.commit()
            cursor.close()
        return True

    def delete(self, condition: dict, index_name: str, dataset_id: str) -> int:
        table_name = self._table_name(index_name)
        if not self._table_exists(table_name):
            return 0
        params: dict[str, Any] = {}
        current_condition = copy.deepcopy(condition or {})
        if dataset_id and not self._is_doc_meta_table(index_name):
            current_condition["kb_id"] = dataset_id
        filters = self._build_filters(current_condition, params, "d")
        sql = f'DELETE FROM {_quote_identifier(table_name)} WHERE {" AND ".join(filters) if filters else "1=1"}'
        logger.debug("OracleConnection.delete sql=%s params=%s", sql, _summarize_log_params(params))
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            deleted = cursor.rowcount or 0
            conn.commit()
            cursor.close()
            return int(deleted)

    def get_total(self, res):
        return res.total if hasattr(res, "total") else 0

    def get_doc_ids(self, res):
        chunks = res.chunks if hasattr(res, "chunks") else []
        return [row["id"] for row in chunks if row.get("id")]

    def get_fields(self, res, fields: list[str]) -> dict[str, dict]:
        chunks = res.chunks if hasattr(res, "chunks") else []
        result: dict[str, dict] = {}
        for row in chunks:
            row_id = row.get("id")
            if not row_id:
                continue
            data = {}
            for field in fields:
                if field == "_score":
                    data[field] = row.get(field, 0)
                elif field in row:
                    data[field] = row[field]
            result[row_id] = data
        return result

    def get_highlight(self, res, keywords: list[str], field_name: str):
        chunks = res.chunks if hasattr(res, "chunks") else []
        answer = {}
        for row in chunks:
            text = row.get(field_name) or ""
            if not isinstance(text, str) or not text:
                continue
            highlighted = text
            for keyword in keywords:
                highlighted = re.sub(
                    re.escape(keyword),
                    lambda match: f"<em>{match.group(0)}</em>",
                    highlighted,
                    flags=re.IGNORECASE,
                )
            if "<em>" in highlighted:
                answer[row["id"]] = highlighted
        return answer

    def get_aggregation(self, res, field_name: str):
        chunks = res.chunks if hasattr(res, "chunks") else []
        counts: dict[str, int] = {}
        for row in chunks:
            value = row.get(field_name)
            values = value if isinstance(value, list) else [value]
            for item in values:
                if item not in (None, ""):
                    key = str(item)
                    counts[key] = counts.get(key, 0) + 1
        return [(key, value) for key, value in counts.items()]

    def sql(self, sql: str, fetch_size: int = 1024, format: str = "json"):
        logger.debug("OracleConnection.sql get sql: %s", sql)

        def normalize_sql(sql_text: str) -> str:
            cleaned = sql_text.strip().rstrip(";")
            cleaned = re.sub(r"[`]+", "", cleaned)
            cleaned = re.sub(
                r"json_extract_string\s*\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)",
                r"JSON_VALUE(\1, \2 RETURNING VARCHAR2(4000) NULL ON ERROR)",
                cleaned,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(
                r"json_extract_isnull\s*\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)",
                r"(JSON_VALUE(\1, \2 RETURNING VARCHAR2(4000) NULL ON ERROR) IS NULL)",
                cleaned,
                flags=re.IGNORECASE,
            )
            return cleaned

        sql_text = normalize_sql(sql)
        if fetch_size and fetch_size > 0 and re.match(r"^(select|with)\b", sql_text.lstrip(), flags=re.IGNORECASE):
            if not re.search(r"\bFETCH\s+NEXT\b|\bFETCH\s+FIRST\b", sql_text, flags=re.IGNORECASE):
                sql_text = f"{sql_text} FETCH FIRST {int(fetch_size)} ROWS ONLY"

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(sql_text)
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            rows_list = [[_read_lob(value) for value in row] for row in rows]
            cursor.close()

        result = {
            "columns": [{"name": col, "type": "text"} for col in columns],
            "rows": rows_list,
        }
        if format == "markdown":
            header = "|" + "|".join(columns) + "|" if columns else ""
            separator = "|" + "|".join(["---" for _ in columns]) + "|" if columns else ""
            body = "\n".join(["|" + "|".join([str(v) for v in row]) + "|" for row in rows_list])
            result["markdown"] = "\n".join([line for line in [header, separator, body] if line])
        return result
