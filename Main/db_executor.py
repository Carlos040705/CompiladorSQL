from dataclasses import dataclass, field
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import psycopg2
from psycopg2 import sql as pg_sql


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "db_config.json"

DEFAULT_DB_CONFIG: Dict[str, Any] = {
    "host": "localhost",
    "port": 5432,
    "user": "postgres",
    "password": "postgres",
    "dbname": "compiladorsql_db",
    "reset_tables": True,
}


def load_db_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Carga la configuración de conexión desde variables de entorno y/o db_config.json."""
    config = dict(DEFAULT_DB_CONFIG)

    # 1. Variables de entorno
    if os.environ.get("PGHOST"):
        config["host"] = os.environ["PGHOST"]
    if os.environ.get("PGPORT"):
        try:
            config["port"] = int(os.environ["PGPORT"])
        except ValueError:
            pass
    if os.environ.get("PGUSER"):
        config["user"] = os.environ["PGUSER"]
    if os.environ.get("PGPASSWORD"):
        config["password"] = os.environ["PGPASSWORD"]
    if os.environ.get("PGDATABASE"):
        config["dbname"] = os.environ["PGDATABASE"]

    # 2. Archivo db_config.json (si existe)
    path = config_path or DEFAULT_CONFIG_PATH
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key in ("host", "user", "password", "dbname"):
                    if key in raw and raw[key] is not None and str(raw[key]).strip() != "":
                        config[key] = str(raw[key]).strip() if key != "password" else str(raw[key])
                if "port" in raw and raw["port"] is not None:
                    try:
                        config["port"] = int(raw["port"])
                    except (ValueError, TypeError):
                        pass
                if "reset_tables" in raw and isinstance(raw["reset_tables"], bool):
                    config["reset_tables"] = raw["reset_tables"]
        except (OSError, json.JSONDecodeError):
            pass

    return config


def save_db_config(config: Dict[str, Any], config_path: Optional[Path] = None) -> Path:
    """Guarda la configuración de conexión PostgreSQL en db_config.json."""
    path = config_path or DEFAULT_CONFIG_PATH
    merged = load_db_config(path)
    merged.update(config)
    if "port" in merged:
        try:
            merged["port"] = int(merged["port"])
        except (ValueError, TypeError):
            merged["port"] = DEFAULT_DB_CONFIG["port"]
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def format_ascii_table(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """Formatea encabezados y filas de un SELECT en una tabla ASCII limpia."""
    if not columns:
        return "(Sin columnas)"

    str_headers = [str(col) for col in columns]
    str_rows = [
        ["NULL" if cell is None else str(cell) for cell in row]
        for row in rows
    ]

    widths = [len(h) for h in str_headers]
    for row in str_rows:
        for idx, val in enumerate(row):
            if idx < len(widths):
                widths[idx] = max(widths[idx], len(val))

    separator = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    header_line = "| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(str_headers)) + " |"

    lines = [separator, header_line, separator]
    if str_rows:
        for row in str_rows:
            lines.append(
                "| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(widths))) + " |"
            )
    else:
        empty_msg = "(0 filas devueltas)"
        total_inner_width = sum(widths) + 3 * (len(widths) - 1)
        lines.append("| " + empty_msg.ljust(total_inner_width) + " |")
    lines.append(separator)
    return "\n".join(lines)


@dataclass
class StatementResult:
    """Resultado estructurado de la ejecución de una sentencia SQL individual."""
    index: int
    sql: str
    success: bool
    command_type: str = ""
    rowcount: int = 0
    columns: List[str] = field(default_factory=list)
    rows: List[Tuple[Any, ...]] = field(default_factory=list)
    formatted_table: str = ""
    status_message: str = ""
    error: Optional[str] = None


@dataclass
class ExecutionReport:
    """Reporte completo de la ejecución de un lote de sentencias SQL en PostgreSQL."""
    connected: bool
    database: str
    results: List[StatementResult] = field(default_factory=list)
    connection_error: Optional[str] = None
    reset_tables_executed: List[str] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if not r.success)

    def format_report(self) -> str:
        lines = [
            "",
            "=" * 75,
            f"EJECUCIÓN EN POSTGRESQL (Base de datos: {self.database})",
            "=" * 75,
        ]
        if not self.connected:
            lines.append(f"[!] Error de conexión a PostgreSQL: {self.connection_error}")
            lines.append("=" * 75)
            return "\n".join(lines)

        if self.reset_tables_executed:
            lines.append(
                f"[Esquema] Tablas reiniciadas limpiamente: {', '.join(self.reset_tables_executed)}"
            )

        for res in self.results:
            lines.append(f"\n[{res.index}] SQL: {res.sql}")
            if res.success:
                lines.append(f"    Estado: OK ({res.status_message})")
                if res.formatted_table:
                    for tbl_line in res.formatted_table.splitlines():
                        lines.append(f"    {tbl_line}")
            else:
                lines.append(f"    [!] Error SQL: {res.error}")

        lines.append("\n" + "-" * 75)
        lines.append(
            f"Resumen de ejecución: {self.success_count} exitosas, "
            f"{self.error_count} con error (Total: {len(self.results)})."
        )
        lines.append("=" * 75)
        return "\n".join(lines)


class PostgresExecutor:
    """Ejecutor de sentencias SQL generadas sobre una instancia real de PostgreSQL."""

    CREATE_TABLE_REGEX = re.compile(
        r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_\"\.]+)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        dbname: Optional[str] = None,
        config_path: Optional[Path] = None,
    ):
        loaded = load_db_config(config_path)
        self.host: str = host if host is not None else loaded["host"]
        self.port: int = int(port if port is not None else loaded["port"])
        self.user: str = user if user is not None else loaded["user"]
        self.password: str = password if password is not None else loaded["password"]
        self.dbname: str = dbname if dbname is not None else loaded["dbname"]
        self.reset_tables_default: bool = bool(loaded.get("reset_tables", True))

    def get_connection_params(self, dbname_override: Optional[str] = None) -> Dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "dbname": dbname_override or self.dbname,
            "connect_timeout": 5,
        }

    def test_connection(self, ensure_db: bool = True) -> Tuple[bool, str]:
        """Prueba la conexión a PostgreSQL y opcionalmente crea la base destino si no existe."""
        try:
            if ensure_db:
                self.ensure_database()
            conn = psycopg2.connect(**self.get_connection_params())
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                ver_row = cur.fetchone()
                version_info = ver_row[0] if ver_row else "PostgreSQL"
            conn.close()
            return True, f"Conectado exitosamente a '{self.dbname}' ({version_info.split(',')[0]})"
        except psycopg2.Error as exc:
            msg = (exc.pgerror or str(exc)).strip()
            return False, msg
        except Exception as exc:
            return False, str(exc)

    def ensure_database(self) -> bool:
        """Se conecta a la base de mantenimiento 'postgres' y crea la base destino si aún no existe."""
        target_db = self.dbname
        try:
            conn = psycopg2.connect(**self.get_connection_params(dbname_override=target_db))
            conn.close()
            return True
        except psycopg2.OperationalError:
            pass

        conn = None
        try:
            conn = psycopg2.connect(**self.get_connection_params(dbname_override="postgres"))
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (target_db,))
                exists = cur.fetchone() is not None
                if not exists:
                    cur.execute(
                        pg_sql.SQL("CREATE DATABASE {}").format(pg_sql.Identifier(target_db))
                    )
            return True
        finally:
            if conn is not None:
                conn.close()

    @classmethod
    def _extract_created_tables(cls, statements: Sequence[str]) -> List[str]:
        tables: List[str] = []
        for stmt in statements:
            match = cls.CREATE_TABLE_REGEX.match(stmt)
            if match:
                tbl = match.group(1).strip().strip('"').lower()
                if tbl not in tables:
                    tables.append(tbl)
        return tables

    @staticmethod
    def _detect_command_type(stmt: str) -> str:
        tokens = stmt.strip().split()
        if not tokens:
            return "SQL"
        first = tokens[0].upper()
        if first == "CREATE" and len(tokens) >= 2:
            return f"CREATE {tokens[1].upper()}"
        if first == "DELETE":
            return "DELETE"
        if first == "INSERT":
            return "INSERT"
        if first == "UPDATE":
            return "UPDATE"
        if first == "SELECT":
            return "SELECT"
        return first

    def execute_statements(
        self,
        statements: Union[str, Sequence[str]],
        reset_tables: Optional[bool] = None,
        ensure_db: bool = True,
    ) -> ExecutionReport:
        """
        Ejecuta una lista de sentencias SQL en PostgreSQL, capturando filas devueltas,
        conteo de filas afectadas y errores por sentencia mediante SAVEPOINT.
        """
        if isinstance(statements, str):
            stmt_list = [s.strip() for s in statements.split(";") if s.strip()]
            stmt_list = [f"{s};" for s in stmt_list]
        else:
            stmt_list = [s.strip() for s in statements if s and s.strip()]

        if reset_tables is None:
            reset_tables = self.reset_tables_default

        report = ExecutionReport(connected=False, database=self.dbname)

        try:
            if ensure_db:
                self.ensure_database()
            conn = psycopg2.connect(**self.get_connection_params())
        except psycopg2.Error as exc:
            report.connection_error = (exc.pgerror or str(exc)).strip()
            return report
        except Exception as exc:
            report.connection_error = str(exc)
            return report

        report.connected = True
        try:
            with conn.cursor() as cur:
                if reset_tables:
                    tables_to_reset = self._extract_created_tables(stmt_list)
                    if tables_to_reset:
                        for tbl in reversed(tables_to_reset):
                            cur.execute(
                                pg_sql.SQL("DROP TABLE IF EXISTS {} CASCADE;").format(
                                    pg_sql.Identifier(tbl)
                                )
                            )
                        conn.commit()
                        report.reset_tables_executed = tables_to_reset

                for idx, stmt in enumerate(stmt_list, start=1):
                    cmd_type = self._detect_command_type(stmt)
                    savepoint_name = f"sp_stmt_{idx}"
                    try:
                        cur.execute(f"SAVEPOINT {savepoint_name};")
                        cur.execute(stmt)

                        if cur.description is not None:
                            columns = [desc[0] for desc in cur.description]
                            rows = cur.fetchall()
                            table_str = format_ascii_table(columns, rows)
                            status_msg = f"{len(rows)} fila(s) recuperada(s)"
                            report.results.append(
                                StatementResult(
                                    index=idx,
                                    sql=stmt,
                                    success=True,
                                    command_type=cmd_type,
                                    rowcount=len(rows),
                                    columns=columns,
                                    rows=rows,
                                    formatted_table=table_str,
                                    status_message=status_msg,
                                )
                            )
                        else:
                            affected = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
                            if cmd_type.startswith("CREATE"):
                                status_msg = "Tabla verificada/creada"
                            else:
                                status_msg = f"{affected} fila(s) afectada(s)"
                            report.results.append(
                                StatementResult(
                                    index=idx,
                                    sql=stmt,
                                    success=True,
                                    command_type=cmd_type,
                                    rowcount=affected,
                                    status_message=status_msg,
                                )
                            )
                        cur.execute(f"RELEASE SAVEPOINT {savepoint_name};")
                    except psycopg2.Error as stmt_exc:
                        try:
                            cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name};")
                            cur.execute(f"RELEASE SAVEPOINT {savepoint_name};")
                        except psycopg2.Error:
                            conn.rollback()
                        err_msg = (stmt_exc.pgerror or str(stmt_exc)).strip()
                        report.results.append(
                            StatementResult(
                                index=idx,
                                sql=stmt,
                                success=False,
                                command_type=cmd_type,
                                error=err_msg,
                            )
                        )
                conn.commit()
        finally:
            conn.close()

        return report
