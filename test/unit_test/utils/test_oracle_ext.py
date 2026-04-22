import pytest

from api.db.oracle_ext import OracleDatabase


class TestOracleDatabaseSqlRewrite:
    def test_rewrite_table_aliases_without_as(self):
        sql = 'SELECT COUNT(1) AS "c" FROM "DIALOG" AS "t1" INNER JOIN "USERS" AS "t2" ON ("t1"."TENANT_ID" = "t2"."ID")'

        rewritten = OracleDatabase._rewrite_source_aliases(sql)

        assert 'COUNT(1) AS "c"' in rewritten
        assert 'FROM "DIALOG" "t1"' in rewritten
        assert 'JOIN "USERS" "t2"' in rewritten

    def test_rewrite_wrapped_subquery_alias_without_as(self):
        sql = 'SELECT COUNT(1) FROM (SELECT 1 FROM "DIALOG" AS "t1" INNER JOIN "USERS" AS "t2" ON ("t1"."TENANT_ID" = "t2"."ID") WHERE ("t1"."STATUS" = :1)) AS "_wrapped"'

        rewritten = OracleDatabase._rewrite_source_aliases(sql)

        assert 'FROM (SELECT 1 FROM "DIALOG" "t1" INNER JOIN "USERS" "t2" ON ("t1"."TENANT_ID" = "t2"."ID") WHERE ("t1"."STATUS" = :1)) "_wrapped"' in rewritten
        assert 'FROM "DIALOG" AS "t1"' not in rewritten
        assert 'JOIN "USERS" AS "t2"' not in rewritten
        assert 'AS "_wrapped"' not in rewritten

    def test_rewrite_limit_clause_to_fetch_first(self):
        sql = 'SELECT * FROM "DIALOG" "t1" LIMIT :1'

        rewritten = OracleDatabase._rewrite_limit_clause(sql)

        assert rewritten.endswith("FETCH FIRST :1 ROWS ONLY")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
