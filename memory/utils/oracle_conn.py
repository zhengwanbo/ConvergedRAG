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
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from common.decorator import singleton
from common.doc_store.doc_store_base import MatchExpr, MatchTextExpr, MatchDenseExpr, FusionExpr, OrderByExpr
from common.float_utils import get_float
from rag.utils.oracle_conn import _read_lob, _vector_to_param, _normalize_identifier, _quote_identifier
from common import settings


logger = logging.getLogger("ragflow.memory_oracle_conn")
logger.setLevel(logging.DEBUG)
VECTOR_FIELD_PATTERN = re.compile(r"^q_(?P<vector_size>\d+)_vec$")


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


@dataclass
class SearchResult:
    total: int
    messages: list[dict]


@singleton
class OracleConnection:
    # 定制开发：Wanbo 20250415
    def __init__(self):
        self.doc_conn = settings.docStoreConn
        self.conn_pool = self.doc_conn.conn_pool
        logger.debug(
            "MemoryOracleConnection.__init__ doc_conn=%s has_pool=%s",
            type(self.doc_conn).__name__ if self.doc_conn is not None else None,
            self.conn_pool is not None,
        )

    @staticmethod
    def _table_exists(table_name: str) -> bool:
        return settings.docStoreConn.index_exist(table_name, "")

    @staticmethod
    def _column_exists(table_name: str, column_name: str) -> bool:
        return settings.docStoreConn._column_exists(table_name, column_name)

    def db_type(self) -> str:
        return "oracle"

    def health(self) -> dict:
        return self.doc_conn.health()

    def create_idx(self, index_name: str, dataset_id: str, vector_size: int, parser_id: str = None):
        index_name = _normalize_identifier(index_name)
        if self._table_exists(index_name):
            self._ensure_vector_column(index_name, vector_size)
            return True

        create_sql = (
            f'CREATE TABLE {_quote_identifier(index_name)} ('
            f'{_quote_identifier("id")} VARCHAR2(256) PRIMARY KEY, '
            f'{_quote_identifier("message_id")} VARCHAR2(256) NOT NULL, '
            f'{_quote_identifier("message_type_kwd")} VARCHAR2(64), '
            f'{_quote_identifier("source_id")} VARCHAR2(256), '
            f'{_quote_identifier("memory_id")} VARCHAR2(256) NOT NULL, '
            f'{_quote_identifier("user_id")} VARCHAR2(256), '
            f'{_quote_identifier("agent_id")} VARCHAR2(256), '
            f'{_quote_identifier("session_id")} VARCHAR2(256), '
            f'{_quote_identifier("zone_id")} NUMBER(11) DEFAULT 0, '
            f'{_quote_identifier("valid_at")} VARCHAR2(64), '
            f'{_quote_identifier("invalid_at")} VARCHAR2(64), '
            f'{_quote_identifier("forget_at")} VARCHAR2(64), '
            f'{_quote_identifier("status_int")} NUMBER(11) DEFAULT 1, '
            f'{_quote_identifier("content_ltks")} CLOB, '
            f'{_quote_identifier("tokenized_content_ltks")} CLOB'
            ")"
        )
        logger.debug(
            "MemoryOracleConnection.create_idx table=%s vector_size=%s sql=%s",
            index_name,
            vector_size,
            create_sql,
        )
        with self.conn_pool.acquire() as conn:
            cursor = conn.cursor()
            cursor.execute(create_sql)
            conn.commit()
            cursor.close()
        for column_name in ["message_id", "memory_id", "status_int"]:
            settings.docStoreConn._create_regular_index(index_name, column_name)
        settings.docStoreConn._create_text_index(index_name, "content_ltks")
        self._ensure_vector_column(index_name, vector_size)
        return True

    def _ensure_vector_column(self, table_name: str, vector_size: int):
        if vector_size <= 0:
            return
        table_name = _normalize_identifier(table_name)
        column_name = _normalize_identifier(f"q_{vector_size}_vec")
        if self._column_exists(table_name, column_name):
            return
        sql = f'ALTER TABLE {_quote_identifier(table_name)} ADD ({_quote_identifier(column_name)} VECTOR({vector_size}, FLOAT32))'
        logger.debug(
            "MemoryOracleConnection._ensure_vector_column table=%s vector_size=%s sql=%s",
            table_name,
            vector_size,
            sql,
        )
        with self.conn_pool.acquire() as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            conn.commit()
            cursor.close()

    def delete_idx(self, index_name: str, dataset_id: str):
        return settings.docStoreConn.delete_idx(_normalize_identifier(index_name), "")

    def index_exist(self, index_name: str, dataset_id: str) -> bool:
        return self._table_exists(_normalize_identifier(index_name))

    def _normalize_doc(self, document: dict[str, Any]) -> dict[str, Any]:
        from rag.nlp.rag_tokenizer import tokenize, fine_grained_tokenize

        doc = {
            "id": document.get("id"),
            "message_id": str(document["message_id"]),
            "message_type_kwd": document.get("message_type"),
            "source_id": str(document.get("source_id")) if document.get("source_id") is not None else None,
            "memory_id": document["memory_id"],
            "user_id": document.get("user_id"),
            "agent_id": document.get("agent_id"),
            "session_id": document.get("session_id"),
            "zone_id": document.get("zone_id", 0),
            "valid_at": str(document.get("valid_at") or ""),
            "invalid_at": str(document.get("invalid_at") or "") if document.get("invalid_at") is not None else None,
            "forget_at": str(document.get("forget_at") or "") if document.get("forget_at") is not None else None,
            "status_int": 1 if document.get("status") else 0,
            "content_ltks": document.get("content", ""),
            "tokenized_content_ltks": fine_grained_tokenize(tokenize(document.get("content", ""))),
        }
        content_embed = document.get("content_embed") or []
        if content_embed:
            doc[f"q_{len(content_embed)}_vec"] = _vector_to_param(content_embed)
        return doc

    def insert(self, documents: list[dict], index_name: str, dataset_id: str = None) -> list[str]:
        if not documents:
            return []
        index_name = _normalize_identifier(index_name)
        vector_size = len(documents[0].get("content_embed", []) or [])
        if not self._table_exists(index_name):
            self.create_idx(index_name, dataset_id or "", vector_size)
        elif vector_size:
            self._ensure_vector_column(index_name, vector_size)

        docs = [self._normalize_doc(doc) for doc in documents]
        columns = sorted({key for doc in docs for key in doc.keys()})
        source_projection = ", ".join([f':{column} AS {_quote_identifier(column)}' for column in columns])
        update_projection = ", ".join([f't.{_quote_identifier(column)} = s.{_quote_identifier(column)}' for column in columns if column != "id"])
        insert_columns = ", ".join([_quote_identifier(column) for column in columns])
        insert_values = ", ".join([f's.{_quote_identifier(column)}' for column in columns])
        merge_sql = (
            f'MERGE INTO {_quote_identifier(index_name)} t '
            f'USING (SELECT {source_projection} FROM DUAL) s '
            f'ON (t.{_quote_identifier("id")} = s.{_quote_identifier("id")}) '
            f'WHEN MATCHED THEN UPDATE SET {update_projection} '
            f'WHEN NOT MATCHED THEN INSERT ({insert_columns}) '
            f'VALUES ({insert_values})'
        )
        logger.debug(
            "MemoryOracleConnection.insert table=%s rows=%s columns=%s sql=%s",
            index_name,
            len(docs),
            columns,
            merge_sql,
        )
        with self.conn_pool.acquire() as conn:
            cursor = conn.cursor()
            for doc in docs:
                params = {column: doc.get(column) for column in columns}
                logger.debug("MemoryOracleConnection.insert params=%s", _summarize_log_params(params))
                cursor.execute(merge_sql, params)
            conn.commit()
            cursor.close()
        return []

    @staticmethod
    def convert_field_name(field_name: str, use_tokenized_content: bool = False) -> str:
        match field_name:
            case "message_type":
                return "message_type_kwd"
            case "status":
                return "status_int"
            case "content":
                return "tokenized_content_ltks" if use_tokenized_content else "content_ltks"
            case "content_embed":
                return "content_embed"
            case _:
                return field_name

    def _get_vector_column_name(self, table_name: str) -> str | None:
        table_name = _normalize_identifier(table_name)
        with self.conn_pool.acquire() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT column_name
                  FROM user_tab_columns
                 WHERE (table_name = :table_name OR table_name = UPPER(:table_name) OR table_name = LOWER(:table_name))
                   AND REGEXP_LIKE(column_name, '^q_[0-9]+_vec$', 'i')
                """,
                {"table_name": table_name},
            )
            row = cursor.fetchone()
            cursor.close()
            return row[0].lower() if row else None

    def _decode_message_row(self, cursor, row) -> dict[str, Any]:
        columns = [column[0].lower() for column in cursor.description]
        data = {}
        for idx, column in enumerate(columns):
            value = _read_lob(row[idx])
            if VECTOR_FIELD_PATTERN.match(column):
                if hasattr(value, "tolist"):
                    value = value.tolist()
                elif isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except Exception:
                        pass
            data[column] = value
        return {
            "id": data.get("id"),
            "message_id": data.get("message_id"),
            "message_type": data.get("message_type_kwd"),
            "source_id": data.get("source_id"),
            "memory_id": data.get("memory_id"),
            "user_id": data.get("user_id"),
            "agent_id": data.get("agent_id"),
            "session_id": data.get("session_id"),
            "zone_id": data.get("zone_id", 0),
            "valid_at": data.get("valid_at"),
            "invalid_at": data.get("invalid_at"),
            "forget_at": data.get("forget_at"),
            "status": bool(int(data.get("status_int", 0))),
            "content": data.get("content_ltks", ""),
            "content_embed": next((v for k, v in data.items() if VECTOR_FIELD_PATTERN.match(k)), []),
        }

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
        memory_ids: list[str],
        agg_fields: list[str] | None = None,
        rank_feature: dict | None = None,
        hide_forgotten: bool = True,
    ):
        if isinstance(index_names, str):
            index_names = index_names.split(",")
        result = SearchResult(total=0, messages=[])

        for index_name in index_names:
            index_name = _normalize_identifier(index_name)
            if not self._table_exists(index_name):
                continue

            params: dict[str, Any] = {}
            filters = []
            if memory_ids:
                placeholders = []
                for idx, memory_id in enumerate(memory_ids):
                    key = f"memory_id_{idx}"
                    params[key] = memory_id
                    placeholders.append(f":{key}")
                filters.append(f'{_quote_identifier("memory_id")} IN ({", ".join(placeholders)})')
            if hide_forgotten:
                filters.append(f'{_quote_identifier("forget_at")} IS NULL')
            for key, value in (condition or {}).items():
                db_key = self.convert_field_name(key)
                if isinstance(value, list):
                    placeholders = []
                    for idx, item in enumerate(value):
                        param_name = f"{db_key}_{idx}"
                        params[param_name] = item
                        placeholders.append(f":{param_name}")
                    filters.append(f'{_quote_identifier(db_key)} IN ({", ".join(placeholders)})')
                else:
                    param_name = db_key
                    params[param_name] = value
                    filters.append(f'{_quote_identifier(db_key)} = :{param_name}')

            where_sql = " AND ".join(filters) if filters else "1=1"

            score_expr = None
            order_sql = ""
            for expr in match_expressions:
                if isinstance(expr, MatchTextExpr):
                    text_query = expr.matching_text
                    params["text_query"] = text_query
                    where_sql += f' AND CONTAINS({_quote_identifier("content_ltks")}, :text_query, 1) > 0'
                    score_expr = "SCORE(1)"
                elif isinstance(expr, MatchDenseExpr):
                    params["vector_query"] = _vector_to_param(expr.embedding_data)
                    params["vector_threshold"] = expr.extra_options.get("similarity", 0.0)
                    vector_expr = f'VECTOR_DISTANCE({_quote_identifier(expr.vector_column_name)}, :vector_query, COSINE)'
                    where_sql += f" AND (1 - {vector_expr}) >= :vector_threshold"
                    score_expr = f"(1 - {vector_expr})"
                elif isinstance(expr, FusionExpr) and score_expr:
                    weights = (expr.fusion_params or {}).get("weights", "0.5,0.5").split(",")
                    vector_weight = get_float(weights[1]) if len(weights) > 1 else 0.5
                    score_expr = f"({score_expr} * {vector_weight})"

            if order_by and getattr(order_by, "fields", None):
                parts = [f'{_quote_identifier(self.convert_field_name(field))} {"ASC" if order == 0 else "DESC"}' for field, order in order_by.fields]
                order_sql = " ORDER BY " + ", ".join(parts)
            elif score_expr:
                order_sql = " ORDER BY _score DESC"

            count_sql = f'SELECT COUNT(1) FROM {_quote_identifier(index_name)} WHERE {where_sql}'
            logger.debug(
                "MemoryOracleConnection.search count_sql=%s params=%s",
                count_sql,
                _summarize_log_params(params),
            )
            with self.conn_pool.acquire() as conn:
                cursor = conn.cursor()
                cursor.execute(count_sql, params)
                total = cursor.fetchone()[0]
                cursor.close()
            result.total += total
            if not total:
                continue

            actual_fields = []
            vector_column = self._get_vector_column_name(index_name)
            for field in select_fields:
                db_field = self.convert_field_name(field)
                if db_field == "content_embed" and vector_column:
                    actual_fields.append(_quote_identifier(vector_column))
                elif db_field != "content_embed":
                    actual_fields.append(_quote_identifier(db_field))
            if not actual_fields:
                actual_fields = [_quote_identifier("id")]
            if _quote_identifier("id") not in actual_fields:
                actual_fields = [_quote_identifier("id")] + actual_fields
            projection = ", ".join(actual_fields)
            if score_expr:
                projection += f", {score_expr} AS _score"

            query_sql = f'SELECT {projection} FROM {_quote_identifier(index_name)} WHERE {where_sql}{order_sql}'
            if limit:
                params["offset_value"] = offset
                params["limit_value"] = limit
                query_sql += " OFFSET :offset_value ROWS FETCH NEXT :limit_value ROWS ONLY"
            logger.debug(
                "MemoryOracleConnection.search query_sql=%s params=%s",
                query_sql,
                _summarize_log_params(params),
            )

            with self.conn_pool.acquire() as conn:
                cursor = conn.cursor()
                cursor.execute(query_sql, params)
                rows = cursor.fetchall()
                for row in rows:
                    result.messages.append(self._decode_message_row(cursor, row))
                cursor.close()

        return result, result.total

    def get_forgotten_messages(self, select_fields: list[str], index_name: str, memory_id: str, limit: int = 512):
        return self.search(select_fields, [], {"memory_id": memory_id}, [], OrderByExpr().asc("valid_at"), 0, limit, [index_name], [memory_id], hide_forgotten=False)[0]

    def get_missing_field_message(self, select_fields: list[str], index_name: str, memory_id: str, field_name: str, limit: int = 512):
        db_field = self.convert_field_name(field_name)
        result = self.search(select_fields, [], {"memory_id": memory_id}, [], OrderByExpr().asc("valid_at"), 0, limit, [index_name], [memory_id], hide_forgotten=False)[0]
        result.messages = [message for message in result.messages if not message.get(field_name) and not message.get(db_field)]
        result.total = len(result.messages)
        return result

    def get(self, doc_id: str, index_name: str, memory_ids: list[str]) -> dict | None:
        index_name = _normalize_identifier(index_name)
        if not self._table_exists(index_name):
            return None
        params = {"id": doc_id}
        sql = f'SELECT * FROM {_quote_identifier(index_name)} WHERE {_quote_identifier("id")} = :id'
        logger.debug("MemoryOracleConnection.get sql=%s params=%s", sql, _summarize_log_params(params))
        with self.conn_pool.acquire() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            row = cursor.fetchone()
            if not row:
                cursor.close()
                return None
            data = self._decode_message_row(cursor, row)
            cursor.close()
            return data

    def update(self, condition: dict, new_value: dict, index_name: str, memory_id: str) -> bool:
        from rag.nlp.rag_tokenizer import tokenize, fine_grained_tokenize

        index_name = _normalize_identifier(index_name)
        rows, _ = self.search(["id"], [], condition, [], OrderByExpr(), 0, 1024, [index_name], [memory_id], hide_forgotten=False)
        if not rows.messages:
            return True
        with self.conn_pool.acquire() as conn:
            cursor = conn.cursor()
            for row in rows.messages:
                params = {"id": row["id"]}
                assignments = []
                for key, value in new_value.items():
                    db_key = self.convert_field_name(key)
                    if db_key == "content_ltks":
                        params["tokenized_content_ltks"] = fine_grained_tokenize(tokenize(value))
                        assignments.append(f'{_quote_identifier("tokenized_content_ltks")} = :tokenized_content_ltks')
                    params[db_key] = value
                    assignments.append(f'{_quote_identifier(db_key)} = :{db_key}')
                sql = f'UPDATE {_quote_identifier(index_name)} SET {", ".join(assignments)} WHERE {_quote_identifier("id")} = :id'
                logger.debug("MemoryOracleConnection.update sql=%s params=%s", sql, _summarize_log_params(params))
                cursor.execute(sql, params)
            conn.commit()
            cursor.close()
        return True

    def delete(self, condition: dict, index_name: str, memory_id: str) -> int:
        index_name = _normalize_identifier(index_name)
        params = {"memory_id": memory_id}
        filters = [f'{_quote_identifier("memory_id")} = :memory_id']
        for key, value in (condition or {}).items():
            db_key = self.convert_field_name(key)
            param_name = db_key
            params[param_name] = value
            filters.append(f'{_quote_identifier(db_key)} = :{param_name}')
        sql = f'DELETE FROM {_quote_identifier(index_name)} WHERE {" AND ".join(filters)}'
        logger.debug("MemoryOracleConnection.delete sql=%s params=%s", sql, _summarize_log_params(params))
        with self.conn_pool.acquire() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            deleted = cursor.rowcount or 0
            conn.commit()
            cursor.close()
            return int(deleted)

    def get_total(self, res) -> int:
        if isinstance(res, tuple):
            return res[1]
        return getattr(res, "total", 0)

    def get_doc_ids(self, res) -> list[str]:
        if isinstance(res, tuple):
            res = res[0]
        return [row["id"] for row in getattr(res, "messages", []) if row.get("id")]

    def get_fields(self, res, fields: list[str]) -> dict[str, dict]:
        if isinstance(res, tuple):
            res = res[0]
        mapping = {}
        for row in getattr(res, "messages", []):
            row_id = row.get("id")
            if row_id:
                mapping[row_id] = {field: row.get(field) for field in fields if field in row}
        return mapping

    def get_highlight(self, res, keywords: list[str], field_name: str):
        return {}

    def get_aggregation(self, res, field_name: str):
        return []

    def sql(self, sql: str, fetch_size: int, format: str):
        logger.debug(
            "MemoryOracleConnection.sql passthrough_not_supported sql=%s fetch_size=%s format=%s",
            sql,
            fetch_size,
            format,
        )
        return None
