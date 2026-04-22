import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock


def _load_oracle_conn_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "rag" / "utils" / "oracle_conn.py"

    common_module = types.ModuleType("common")
    common_module.settings = SimpleNamespace(ORCLVECTOR=None)

    constants_module = types.ModuleType("common.constants")
    constants_module.PAGERANK_FLD = "pagerank_fea"
    constants_module.TAG_FLD = "tag_feas"

    decorator_module = types.ModuleType("common.decorator")
    decorator_module.singleton = lambda cls: cls

    doc_store_base_module = types.ModuleType("common.doc_store.doc_store_base")
    for name in ["DocStoreConnection", "MatchExpr", "MatchTextExpr", "MatchDenseExpr", "FusionExpr", "OrderByExpr"]:
        setattr(doc_store_base_module, name, type(name, (), {}))

    file_utils_module = types.ModuleType("common.file_utils")
    file_utils_module.get_project_base_directory = lambda: str(repo_root)

    float_utils_module = types.ModuleType("common.float_utils")
    float_utils_module.get_float = float

    doc_store_package = types.ModuleType("common.doc_store")
    doc_store_package.doc_store_base = doc_store_base_module

    sys.modules["common"] = common_module
    sys.modules["common.constants"] = constants_module
    sys.modules["common.decorator"] = decorator_module
    sys.modules["common.doc_store"] = doc_store_package
    sys.modules["common.doc_store.doc_store_base"] = doc_store_base_module
    sys.modules["common.file_utils"] = file_utils_module
    sys.modules["common.float_utils"] = float_utils_module

    spec = importlib.util.spec_from_file_location("test_oracle_conn_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ORACLE_CONN_MODULE = _load_oracle_conn_module()
OracleConnection = ORACLE_CONN_MODULE.OracleConnection


class _ConnContext:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        return False


def _build_connection(side_effect):
    cursor = MagicMock()
    cursor.execute.side_effect = side_effect

    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


def test_create_idx_treats_race_created_table_as_success():
    oracle_conn = OracleConnection.__new__(OracleConnection)
    conn = _build_connection(Exception(SimpleNamespace(code=955)))

    oracle_conn._table_name = lambda index_name, dataset_id=None: index_name
    oracle_conn._get_conn = lambda: _ConnContext(conn)
    oracle_conn._table_exists = MagicMock(side_effect=[False, True])
    oracle_conn._list_object_types = MagicMock(return_value=["TABLE"])
    ensure_vector_column = MagicMock()
    create_regular_index = MagicMock()
    create_text_index = MagicMock()
    oracle_conn._ensure_vector_column = ensure_vector_column
    oracle_conn._create_regular_index = create_regular_index
    oracle_conn._create_text_index = create_text_index

    assert oracle_conn.create_idx("ragflow_demo", "kb1", 1024) is True

    ensure_vector_column.assert_called_once_with("ragflow_demo", 1024)
    assert create_regular_index.call_count == 6
    create_text_index.assert_called_once()


def test_create_idx_raises_clear_error_for_non_table_name_conflict():
    oracle_conn = OracleConnection.__new__(OracleConnection)
    conn = _build_connection(Exception(SimpleNamespace(code=955)))

    oracle_conn._table_name = lambda index_name, dataset_id=None: index_name
    oracle_conn._get_conn = lambda: _ConnContext(conn)
    oracle_conn._table_exists = MagicMock(side_effect=[False, False])
    oracle_conn._list_object_types = MagicMock(return_value=["INDEX"])
    oracle_conn._ensure_vector_column = MagicMock()
    oracle_conn._create_regular_index = MagicMock()
    oracle_conn._create_text_index = MagicMock()

    with unittest.TestCase().assertRaisesRegex(RuntimeError, "existing INDEX prevents table creation"):
        oracle_conn.create_idx("ragflow_demo", "kb1", 1024)
