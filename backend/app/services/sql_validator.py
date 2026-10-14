"""Static SQL validation - the first safety gate.

Model-generated SQL is untrusted input. Before any query reaches the database,
it is *parsed* into a syntax tree with sqlglot (not matched with regexes) and
checked against these rules:

1. Exactly one statement.                       -> else SECURITY
2. The statement is a read-only query: SELECT, a set operation
   (UNION / INTERSECT / EXCEPT), optionally with CTEs (WITH ...). -> else SECURITY
3. No write/DDL/admin node anywhere in the tree (INSERT, UPDATE, DELETE, DROP,
   CREATE, ALTER, PRAGMA, ATTACH, SELECT ... INTO, ...).  -> else SECURITY
4. No dangerous functions (load_extension, readfile, pragma_* ...). -> SECURITY
5. Every table is an approved table (or a CTE defined in the query).
   - internal / unapproved tables  -> SECURITY
   - a name that does not exist    -> RECOVERABLE (the LLM probably typo'd it)
6. Every column referenced exists in a referenced table (or is an alias /
   CTE output).                    -> RECOVERABLE
7. String literals compared with a categorical column (`status = 'Completed'`)
   must be one of that column's real values. The schema inspector knows the
   complete value set for small text columns, so a typo or wrong casing would
   otherwise run "successfully" and silently return zero rows.
                                   -> RECOVERABLE

The validated tree is then re-rendered by sqlglot. QueryPilot executes *that*
canonical SQL, so what runs is exactly what was checked (comments and other
tricks in the raw text are dropped).

Runtime layers in `query_executor` (read-only connection, SQLite authorizer,
timeout, row cap) back this up in case the parser and SQLite ever disagree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from app.core.errors import ErrorCategory, SQLValidationError
from app.services.schema_service import DatabaseSchema

ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)

FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    getattr(exp, name)
    for name in (
        "Insert", "Update", "Delete", "Merge", "Drop", "Create", "Alter", "TruncateTable",
        "Command", "Pragma", "Attach", "Detach", "Transaction", "Commit", "Rollback",
        "Set", "Use", "Into", "Copy", "Analyze", "Replace", "LoadData",
    )
    if hasattr(exp, name)
)

FORBIDDEN_FUNCTIONS = {
    "load_extension", "readfile", "writefile", "edit", "fts3_tokenizer", "zeroblob",
    "randomblob", "sqlite_compileoption_get", "sqlite_compileoption_used", "sqlite_offset",
    "sqlite_source_id", "sqlite_version",
    "current_version",  # sqlglot's normalised name for sqlite_version()
}
FORBIDDEN_FUNCTION_PREFIXES = ("pragma_", "sqlite_")
INTERNAL_TABLE_PREFIXES = ("sqlite_", "pragma_")


@dataclass(frozen=True)
class ValidatedSQL:
    sql: str  # canonical SQL that will actually be executed
    tables: list[str]
    cte_names: frozenset[str] = frozenset()


def _security(message: str, code: str) -> SQLValidationError:
    return SQLValidationError(message, category=ErrorCategory.SECURITY, code=code)


def _recoverable(message: str, code: str) -> SQLValidationError:
    return SQLValidationError(message, category=ErrorCategory.RECOVERABLE, code=code)


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def validate_sql(sql: str, schema: DatabaseSchema, dialect: str = "sqlite") -> ValidatedSQL:
    if not sql or not sql.strip():
        raise _recoverable("The generated SQL was empty.", "empty_sql")

    # 1. Parse. A parse failure is a syntax problem the LLM can usually fix.
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except (ParseError, TokenError) as exc:
        first_line = re.sub(r"\s*for <class '[^']+'>", "", str(exc).splitlines()[0])[:200]
        raise _recoverable(f"SQL syntax error: {first_line}", "sql_syntax_error") from None

    if len(statements) != 1:
        raise _security(
            f"Exactly one SQL statement is allowed, found {len(statements)}.",
            "multiple_statements",
        )
    tree = statements[0]

    # 2. Root must be a read-only query.
    if not isinstance(tree, ALLOWED_ROOTS):
        raise _security(
            f"Only read-only SELECT queries are allowed (got {tree.key.upper()}).",
            "forbidden_statement",
        )

    # 3. No write / DDL / admin node anywhere (e.g. inside a CTE).
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise _security(
                f"Forbidden SQL operation: {node.key.upper()}.", "forbidden_statement"
            )

    # 4. Dangerous functions.
    for func in tree.find_all(exp.Func):
        name = _function_name(func)
        if name in FORBIDDEN_FUNCTIONS or name.startswith(FORBIDDEN_FUNCTION_PREFIXES):
            raise _security(f"Function '{name}' is not allowed.", "forbidden_function")

    # 5. Tables.
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    alias_to_table: dict[str, str] = {}
    used_tables: list[str] = []
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if not name:  # e.g. table-valued function used in FROM
            raise _security("Table-valued functions are not allowed.", "forbidden_function")
        if table.args.get("db") or table.args.get("catalog"):
            raise _security(
                "Schema-qualified table names are not allowed.", "table_not_allowed"
            )
        if name in cte_names:
            continue
        if name not in schema.table_names:
            if name.startswith(INTERNAL_TABLE_PREFIXES) or name in schema.hidden_table_names:
                raise _security(f"Table '{table.name}' is not permitted.", "table_not_allowed")
            raise _recoverable(
                f"Unknown table '{table.name}'. Available tables: "
                + ", ".join(sorted(t.name for t in schema.tables)),
                "unknown_table",
            )
        alias_to_table[table.alias_or_name.lower()] = name
        if name not in used_tables:
            used_tables.append(name)

    # 6. Columns.
    _validate_columns(tree, schema, alias_to_table, cte_names)

    # 7. Values compared with categorical columns.
    _validate_categorical_literals(tree, schema, alias_to_table)

    return ValidatedSQL(
        sql=tree.sql(dialect=dialect, pretty=True),
        tables=used_tables,
        cte_names=frozenset(cte_names),
    )


def _validate_columns(
    tree: exp.Expression,
    schema: DatabaseSchema,
    alias_to_table: dict[str, str],
    cte_names: set[str],
) -> None:
    referenced_columns: set[str] = set()
    for table_name in set(alias_to_table.values()):
        referenced_columns |= schema.columns_of(table_name)

    # Names introduced by the query itself: `AS revenue`, CTE column lists,
    # derived-table aliases. Unqualified references to them are fine.
    output_names = {a.alias.lower() for a in tree.find_all(exp.Alias) if a.alias}
    for cte in tree.find_all(exp.CTE):
        for col in cte.args.get("alias", exp.TableAlias()).columns or []:
            output_names.add(col.name.lower())
    derived_aliases = {
        sub.alias_or_name.lower() for sub in tree.find_all(exp.Subquery) if sub.alias_or_name
    } | cte_names

    for column in tree.find_all(exp.Column):
        name = column.name.lower()
        if not name or name == "*":
            continue
        qualifier = column.table.lower() if column.table else ""
        if qualifier:
            if qualifier in alias_to_table:
                table_name = alias_to_table[qualifier]
                if name not in schema.columns_of(table_name):
                    raise _recoverable(
                        f"Unknown column '{column.table}.{column.name}'. Columns of "
                        f"{table_name}: {', '.join(sorted(schema.columns_of(table_name)))}",
                        "unknown_column",
                    )
            elif qualifier not in derived_aliases:
                raise _recoverable(
                    f"Unknown table or alias '{column.table}' in '{column.sql()}'.",
                    "unknown_column",
                )
            continue
        if name not in referenced_columns and name not in output_names:
            raise _recoverable(
                f"Unknown column '{column.name}'. It does not exist in the tables "
                f"used by the query ({', '.join(sorted(set(alias_to_table.values()))) or 'none'}).",
                "unknown_column",
            )


def _resolve_column_table(column: exp.Column, alias_to_table: dict[str, str],
                          schema: DatabaseSchema) -> str | None:
    """Real table a column belongs to, or None if it can't be pinned down."""
    if column.table:
        return alias_to_table.get(column.table.lower())  # None for CTE / subquery
    owners = [t for t in set(alias_to_table.values()) if column.name.lower() in schema.columns_of(t)]
    return owners[0] if len(owners) == 1 else None


def _validate_categorical_literals(tree: exp.Expression, schema: DatabaseSchema,
                                   alias_to_table: dict[str, str]) -> None:
    for node in tree.find_all(exp.EQ, exp.NEQ, exp.In):
        if isinstance(node, exp.In):
            column, literals = node.this, list(node.expressions)
        else:
            left, right = node.this, node.expression
            column, literals = (left, [right]) if isinstance(left, exp.Column) else (right, [left])
        if not isinstance(column, exp.Column):
            continue
        table = _resolve_column_table(column, alias_to_table, schema)
        info = schema.column(table, column.name) if table else None
        if not info or not info.sample_values:  # only columns whose full value set is known
            continue
        allowed = set(info.sample_values)
        for literal in literals:
            if not (isinstance(literal, exp.Literal) and literal.is_string):
                continue
            value = literal.this
            if value in allowed:
                continue
            close = [v for v in info.sample_values if v.lower() == value.lower()]
            hint = f" Did you mean '{close[0]}'?" if close else ""
            raise _recoverable(
                f"Value '{value}' never occurs in {table}.{info.name}.{hint} Valid values: "
                + ", ".join(f"'{v}'" for v in info.sample_values)
                + ". Use the exact spelling; if the question really asks about a value that "
                "does not exist, set answerable=false and explain.",
                "unknown_value",
            )
