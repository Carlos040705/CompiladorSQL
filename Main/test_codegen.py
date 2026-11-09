import contextlib
import io
import sys
import unittest
from pathlib import Path

_SITE_PACKAGES = Path(__file__).resolve().parent.parent / "env" / "Lib" / "site-packages"
if _SITE_PACKAGES.is_dir() and str(_SITE_PACKAGES) not in sys.path:
    sys.path.insert(0, str(_SITE_PACKAGES))

from codegen import SQLCodeGenerator
from lexer import errores_lexicos, lexer
from parser import errores_sintacticos, parser
from semantic import SemanticAnalyzer, normalize_dsl_fragment


ROOT_DIR = Path(__file__).resolve().parent.parent


def compile_to_sql(source: str):
    # corre todas las fases del compilador y regresa el sql
    if not source.endswith("\n"):
        source += "\n"

    errores_lexicos.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        lexer.input(source)
        tokens = []
        while True:
            tok = lexer.token()
            if tok is None:
                break
            tokens.append(tok)

    if errores_lexicos:
        raise AssertionError(f"Errores léxicos inesperados: {errores_lexicos}")

    errores_sintacticos.clear()
    token_iterator = iter(tokens)
    with contextlib.redirect_stdout(io.StringIO()):
        ast = parser.parse(tokenfunc=lambda: next(token_iterator, None))

    if errores_sintacticos:
        raise AssertionError(f"Errores sintácticos inesperados: {errores_sintacticos}")

    analyzer = SemanticAnalyzer()
    with contextlib.redirect_stdout(io.StringIO()):
        sem_errors, sym_table = analyzer.analyze(ast)

    if sem_errors:
        raise AssertionError(f"Errores semánticos inesperados: {sem_errors}")

    generator = SQLCodeGenerator(sym_table)
    return generator.generate(ast)


class SQLCodeGeneratorTests(unittest.TestCase):
    def test_valid_repository_files_translate_without_errors(self):
        for filename, expected_min_stmts in [
            ("Prueba.txt", 2),
            ("prueba_completa_valida.txt", 25),
            ("prueba_expresiones_y_cadenas.txt", 16),
        ]:
            file_path = ROOT_DIR / filename
            self.assertTrue(file_path.is_file(), f"No se encontró {file_path}")
            source = normalize_dsl_fragment(file_path.read_text(encoding="utf-8"))
            statements = compile_to_sql(source)
            self.assertGreaterEqual(len(statements), expected_min_stmts)
            for stmt in statements:
                self.assertTrue(stmt.endswith(";"), f"Sentencia sin ';' final: {stmt}")
                self.assertNotIn("--", stmt, f"Comentario accidental '--' en sentencia: {stmt}")

    def test_ddl_create_table_types_and_constraints(self):
        source = """Model Estudiante:
\tmatricula: auto main key
\tnombre: string required
\tcorreo: string unique
\tbiografia: text default = "Sin biografia"
\tedad: num required default = 18
\tpromedio: decimal(4,2) default = 0.0
\tsaldo: decimal(10,2) default = -10.50
\tbecado: bool default = false
\tactivo: bool default = true
\tfecha_ingreso: string default = 2026-08-15

Model Curso:
\tid_curso: auto main key
\tid_estudiante: num external key required
\tnombre_curso: string required unique
"""
        stmts = compile_to_sql(source)
        self.assertEqual(len(stmts), 2)
        ddl_estudiante = stmts[0]
        ddl_curso = stmts[1]

        self.assertIn("CREATE TABLE IF NOT EXISTS estudiante", ddl_estudiante)
        self.assertIn("matricula SERIAL PRIMARY KEY", ddl_estudiante)
        self.assertIn("nombre VARCHAR(255) NOT NULL", ddl_estudiante)
        self.assertIn("correo VARCHAR(255) UNIQUE", ddl_estudiante)
        self.assertIn("biografia TEXT DEFAULT 'Sin biografia'", ddl_estudiante)
        self.assertIn("edad INTEGER NOT NULL DEFAULT 18", ddl_estudiante)
        self.assertIn("promedio NUMERIC(4, 2) DEFAULT 0.0", ddl_estudiante)
        self.assertIn("saldo NUMERIC(10, 2) DEFAULT -10.5", ddl_estudiante)
        self.assertIn("becado BOOLEAN DEFAULT FALSE", ddl_estudiante)
        self.assertIn("activo BOOLEAN DEFAULT TRUE", ddl_estudiante)
        self.assertIn("fecha_ingreso VARCHAR(255) DEFAULT '2026-08-15'", ddl_estudiante)

        self.assertIn("CREATE TABLE IF NOT EXISTS curso", ddl_curso)
        self.assertIn("id_curso SERIAL PRIMARY KEY", ddl_curso)
        self.assertIn("id_estudiante INTEGER NOT NULL REFERENCES estudiante(matricula)", ddl_curso)
        self.assertIn("nombre_curso VARCHAR(255) NOT NULL UNIQUE", ddl_curso)

    def test_dml_insert_update_and_delete(self):
        source = """Model Estudiante:
\tmatricula: auto main key
\tnombre: string required
\tcorreo: string
\tedad: num

Estudiante.new(nombre = "Jose", correo = empty, edad = 25)
Estudiante.add(nombre = "Ana's", correo = "ana@unach.mx", edad = 21)
Estudiante.find().if(matricula = 1).modify(edad = 26, correo = empty)
Estudiante.remove(nombre = "Jose")
Estudiante.find().if(edad < 18).remove()
"""
        stmts = compile_to_sql(source)
        self.assertEqual(
            stmts[1],
            "INSERT INTO estudiante (nombre, correo, edad) VALUES ('Jose', NULL, 25);",
        )
        self.assertEqual(
            stmts[2],
            "INSERT INTO estudiante (nombre, correo, edad) VALUES ('Ana''s', 'ana@unach.mx', 21);",
        )
        self.assertEqual(
            stmts[3],
            "UPDATE estudiante SET edad = 26, correo = NULL WHERE matricula = 1;",
        )
        self.assertEqual(
            stmts[4],
            "DELETE FROM estudiante WHERE nombre = 'Jose';",
        )
        self.assertEqual(
            stmts[5],
            "DELETE FROM estudiante WHERE edad < 18;",
        )

    def test_select_projections_filters_ordering_pagination_and_aggregates(self):
        source = """Model Estudiante:
\tmatricula: auto main key
\tnombre: string
\tedad: num
\tsemestre: num
\tpromedio: decimal(4,2)
\tbecado: bool

Estudiante.find(nombre = "Jose")
Estudiante.find(matricula, nombre).if(semestre >= 5).up(nombre).down(edad).take(10).skip(5)
Estudiante.count()
Estudiante.count(nombre)
Estudiante.sum(edad)
Estudiante.avg(promedio).if(becado = true)
Estudiante.max(edad)
Estudiante.min(edad)
"""
        stmts = compile_to_sql(source)
        self.assertEqual(stmts[1], "SELECT * FROM estudiante WHERE nombre = 'Jose';")
        self.assertEqual(
            stmts[2],
            "SELECT matricula, nombre FROM estudiante WHERE semestre >= 5 ORDER BY nombre ASC, edad DESC LIMIT 10 OFFSET 5;",
        )
        self.assertEqual(stmts[3], "SELECT COUNT(*) FROM estudiante;")
        self.assertEqual(stmts[4], "SELECT COUNT(nombre) FROM estudiante;")
        self.assertEqual(stmts[5], "SELECT SUM(edad) FROM estudiante;")
        self.assertEqual(stmts[6], "SELECT AVG(promedio) FROM estudiante WHERE becado = TRUE;")
        self.assertEqual(stmts[7], "SELECT MAX(edad) FROM estudiante;")
        self.assertEqual(stmts[8], "SELECT MIN(edad) FROM estudiante;")

    def test_link_join_and_postgresql_strict_group_by_and_disambiguation(self):
        # prueba con external key para ver que arme inner join
        source_fk = """Model Estudiante:
\tmatricula: auto main key
\tsemestre: num
Model Curso:
\tid_curso: auto main key
\tid_estudiante: num external key required
Estudiante.find(semestre).link(Curso).group(semestre).ifgroup(semestre > 3).up(semestre)
"""
        stmts_fk = compile_to_sql(source_fk)
        self.assertEqual(
            stmts_fk[2],
            "SELECT semestre FROM estudiante INNER JOIN curso ON estudiante.matricula = curso.id_estudiante GROUP BY semestre HAVING semestre > 3 ORDER BY semestre ASC;",
        )

        # prueba sin llave foranea para que saque cross join y separe campos repetidos
        source_cross = """Model Estudiante:
\tmatricula: auto main key
\tsemestre: num
\tpromedio: decimal(10,2)
\tactivo: bool
Model Curso:
\tid_curso: auto main key
\tactivo: bool
Estudiante.find(semestre, promedio).link(Curso).if(activo = true).group(semestre).ifgroup(promedio > 8.0)
"""
        stmts_cross = compile_to_sql(source_cross)
        self.assertEqual(
            stmts_cross[2],
            "SELECT semestre, promedio FROM estudiante CROSS JOIN curso WHERE estudiante.activo = TRUE GROUP BY semestre, promedio HAVING promedio > 8.0;",
        )

    def test_null_comparisons_and_double_unary_negation(self):
        source = """Model Estudiante:
\tcorreo: string
\tsaldo: decimal(10,2)

Estudiante.find().if(correo = empty)
Estudiante.find().if(correo != empty)
Estudiante.modify(saldo = -(-10 + 5) * -2)
Estudiante.modify(saldo = -(-5))
"""
        stmts = compile_to_sql(source)
        self.assertEqual(stmts[1], "SELECT * FROM estudiante WHERE correo IS NULL;")
        self.assertEqual(stmts[2], "SELECT * FROM estudiante WHERE correo IS NOT NULL;")
        self.assertEqual(stmts[3], "UPDATE estudiante SET saldo = -(-10 + 5) * -2;")
        self.assertEqual(stmts[4], "UPDATE estudiante SET saldo = -(-5);")
        for s in stmts:
            self.assertNotIn("--", s)

    def test_executor_helpers_and_ascii_table_formatting(self):
        from db_executor import PostgresExecutor, format_ascii_table

        table = format_ascii_table(["matricula", "nombre"], [(1, "Jose"), (2, None)])
        self.assertIn("matricula", table)
        self.assertIn("Jose", table)
        self.assertIn("NULL", table)

        extracted = PostgresExecutor._extract_created_tables([
            "CREATE TABLE IF NOT EXISTS estudiante (id SERIAL PRIMARY KEY);",
            "CREATE TABLE IF NOT EXISTS curso (id SERIAL PRIMARY KEY);",
            "SELECT * FROM estudiante;",
        ])
        self.assertEqual(extracted, ["estudiante", "curso"])

    def test_multiline_method_chaining_style_a_with_indentation_and_comments(self):
        source = """Model Estudiante:
    matricula: auto main key
    nombre: string required
    semestre: num
    promedio: decimal(4,2)

Estudiante.find(matricula, nombre, promedio)
    .if(semestre >= 5)
    // Comentario intermedio opcional
    .up(promedio)
    /* Comentario de bloque intermedio */
    .take(10)
    .skip(0)
"""
        stmts = compile_to_sql(source)
        self.assertEqual(len(stmts), 2)
        self.assertEqual(
            stmts[1],
            "SELECT matricula, nombre, promedio FROM estudiante WHERE semestre >= 5 ORDER BY promedio ASC LIMIT 10 OFFSET 0;",
        )

    def test_multiline_method_chaining_style_b_with_trailing_dot(self):
        source = """Model Estudiante:
    matricula: auto main key
    nombre: string required
    semestre: num
    promedio: decimal(4,2)

Estudiante.find(matricula, nombre, promedio).
    if(semestre >= 5).
    up(promedio).
    take(10).
    skip(0)
"""
        stmts = compile_to_sql(source)
        self.assertEqual(len(stmts), 2)
        self.assertEqual(
            stmts[1],
            "SELECT matricula, nombre, promedio FROM estudiante WHERE semestre >= 5 ORDER BY promedio ASC LIMIT 10 OFFSET 0;",
        )


if __name__ == "__main__":
    unittest.main()
