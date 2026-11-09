import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

_SITE_PACKAGES = Path(__file__).resolve().parent.parent / "env" / "Lib" / "site-packages"
if _SITE_PACKAGES.is_dir() and str(_SITE_PACKAGES) not in sys.path:
    sys.path.insert(0, str(_SITE_PACKAGES))

from ast_nodes import ModelDeclaration
from codegen import SQLCodeGenerator
from lexer import errores_lexicos, lexer
from main import analizar_archivo
from parser import errores_sintacticos, parser
from semantic import (
    SemanticAnalyzer,
    SymbolTable,
    build_context_symbol_table,
    extract_context_models,
    normalize_dsl_fragment,
)


# funcion auxiliar para correr el analisis y regresar la lista de errores
def analyze_source(source: str):
    errores_lexicos.clear()
    lexer.input(source)
    tokens = []
    while True:
        token = lexer.token()
        if token is None:
            break
        tokens.append(token)

    if errores_lexicos:
        return errores_lexicos.copy()

    errores_sintacticos.clear()
    token_iterator = iter(tokens)
    ast = parser.parse(tokenfunc=lambda: next(token_iterator, None))
    if errores_sintacticos:
        return errores_sintacticos.copy()

    with contextlib.redirect_stdout(io.StringIO()):
        errors, _ = SemanticAnalyzer().analyze(ast)
    return errors


class SemanticAnalyzerTests(unittest.TestCase):
    def test_required_and_default_are_valid_in_either_order(self):
        source = """model A:
\tfirst: num required default = 1
\tsecond: num default = 2 required
"""
        self.assertEqual(analyze_source(source), [])

    def test_repeated_insert_parameter_is_rejected(self):
        errors = analyze_source(
            "model A:\n\tvalue: num\nA.new(value = 1, value = 2)\n"
        )
        self.assertTrue(any("más de una vez" in error for error in errors))

    def test_base_model_field_takes_precedence_after_link(self):
        source = """model A:
\tshared: string
model B:
\tshared: num
A.find(shared).link(B).up(shared)
"""
        self.assertEqual(analyze_source(source), [])

    def test_field_unique_to_multiple_linked_models_is_ambiguous(self):
        source = """model A:
\tbase: num
model B:
\tshared: num
model C:
\tshared: num
A.find().link(B).link(C).up(shared)
"""
        errors = analyze_source(source)
        self.assertTrue(any("ambiguo" in error for error in errors))

    def test_remove_without_filter_is_rejected(self):
        errors = analyze_source("model A:\n\tid: num\nA.remove()\n")
        self.assertTrue(any("requiere una condición" in error for error in errors))

    def test_remove_with_prior_filter_is_allowed(self):
        source = "model A:\n\tid: num\nA.find().if(id = 1).remove()\n"
        self.assertEqual(analyze_source(source), [])

    def test_remove_with_inline_filter_is_allowed(self):
        source = "model A:\n\tid: num\nA.remove(id = 1)\n"
        self.assertEqual(analyze_source(source), [])

    def test_constant_expression_division_by_zero_is_rejected(self):
        source = "model A:\n\tid: num\nA.find().if(id / (2 - 2) > 0)\n"
        errors = analyze_source(source)
        self.assertTrue(any("cero" in error for error in errors))

    def test_lexical_errors_skip_later_phases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "invalid.dsl"
            source_path.write_text("model A:\n\tid: num @\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                analizar_archivo(source_path)

        result = output.getvalue()
        self.assertIn("Fase Sintáctica] Omitida", result)
        self.assertIn("Fase Semántica] Omitida", result)

    def test_mixing_modify_and_remove_is_rejected(self):
        source = "model A:\n\tedad: num\nA.modify(edad = 20).remove(edad = 20)\n"
        errors = analyze_source(source)
        self.assertTrue(any(".modify()" in error and ".remove()" in error for error in errors))

    def test_mixing_mutations_with_query_clauses_is_rejected(self):
        source = "model A:\n\tedad: num\nA.modify(edad = 20).take(5)\n"
        errors = analyze_source(source)
        self.assertTrue(any("no se puede combinar" in error for error in errors))

    def test_if_after_modify_or_remove_is_rejected(self):
        errors_modify = analyze_source("model A:\n\tid: num\n\tedad: num\nA.modify(edad = 20).if(id = 1)\n")
        errors_remove = analyze_source("model A:\n\tid: num\n\tedad: num\nA.remove(id = 1).if(edad > 18)\n")
        self.assertTrue(any("debe preceder" in error for error in errors_modify))
        self.assertTrue(any("debe preceder" in error for error in errors_remove))

    def test_duplicate_single_clauses_are_rejected(self):
        errors_take = analyze_source("model A:\n\ta: num\nA.find().take(5).take(10)\n")
        errors_group = analyze_source("model A:\n\ta: num\n\tb: num\nA.find().group(a).group(b)\n")
        self.assertTrue(any("Cláusula duplicada" in error and ".take()" in error for error in errors_take))
        self.assertTrue(any("Cláusula duplicada" in error and ".group()" in error for error in errors_group))

    def test_self_link_and_duplicate_link_are_rejected(self):
        self_link_errors = analyze_source("model A:\n\tid: num\nA.find().link(A)\n")
        dup_link_errors = analyze_source(
            "model A:\n\tid: num\nmodel B:\n\tid_b: num\nA.find().link(B).link(B)\n"
        )
        self.assertTrue(any("Auto-enlace" in error or "ámbito activo" in error for error in self_link_errors))
        self.assertTrue(any("Enlace duplicado" in error or "ámbito activo" in error for error in dup_link_errors))

    def test_take_and_skip_constant_expression_evaluation(self):
        errors_take_zero = analyze_source("model A:\n\tid: num\nA.find().take(0)\n")
        errors_take_expr = analyze_source("model A:\n\tid: num\nA.find().take(2 - 5)\n")
        errors_skip_neg = analyze_source("model A:\n\tid: num\nA.find().skip(3 - 10)\n")
        valid_skip_zero = analyze_source("model A:\n\tid: num\nA.find().skip(0)\n")
        self.assertTrue(any(".take()" in error for error in errors_take_zero))
        self.assertTrue(any(".take()" in error for error in errors_take_expr))
        self.assertTrue(any(".skip()" in error for error in errors_skip_neg))
        self.assertEqual(valid_skip_zero, [])

    def test_decimal_overflow_is_rejected(self):
        source = "model A:\n\tprecio: decimal(4, 2)\nA.new(precio = 150.00)\n"
        errors = analyze_source(source)
        self.assertTrue(any("Desbordamiento" in error and "DECIMAL(4,2)" in error for error in errors))

    def test_invalid_calendar_date_literal_is_rejected(self):
        source = "model A:\n\tfecha: string\nA.new(fecha = 2026-02-30)\n"
        errors = analyze_source(source)
        self.assertEqual(len(errors), 1)
        self.assertTrue(any("Fecha calendario inválida" in error and "2026-02-30" in error for error in errors))

    def test_clipboard_selection_on_prueba_txt_with_mixed_indentation(self):
        root_dir = Path(__file__).resolve().parent.parent
        prueba_code = (root_dir / "Prueba.txt").read_text(encoding="utf-8")
        selection = '   estudiante.new(nombre = "Jose Cruz Castillo", edad = 67, peso = 160.00)'

        cleaned_selection = normalize_dsl_fragment(selection)
        context_models = extract_context_models(prueba_code)
        session_symbols = build_context_symbol_table(prueba_code)

        self.assertEqual(len(context_models), 1)
        self.assertIsNotNone(session_symbols.get_model("estudiante"))

        errores_lexicos.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            lexer.input(cleaned_selection)
            tokens = []
            while True:
                tok = lexer.token()
                if tok is None:
                    break
                tokens.append(tok)
        self.assertEqual(errores_lexicos, [])

        errores_sintacticos.clear()
        token_iter = iter(tokens)
        with contextlib.redirect_stdout(io.StringIO()):
            ast_sel = parser.parse(tokenfunc=lambda: next(token_iter, None))
        self.assertEqual(errores_sintacticos, [])

        analyzer = SemanticAnalyzer()
        with contextlib.redirect_stdout(io.StringIO()):
            sem_errors, sym_table = analyzer.analyze(
                ast_sel,
                context_models=context_models,
                context_code=prueba_code,
                persistent_symbols=session_symbols,
            )
        self.assertEqual(sem_errors, [])

        explicit_models = {
            stmt.name.lower()
            for stmt in ast_sel.statements
            if isinstance(stmt, ModelDeclaration)
        }
        sql_list = SQLCodeGenerator(sym_table).generate(
            ast_sel,
            allowed_model_declarations=explicit_models,
        )
        self.assertEqual(len(sql_list), 1)
        self.assertNotIn("CREATE TABLE", sql_list.script.upper())
        self.assertEqual(
            sql_list[0],
            "INSERT INTO estudiante (nombre, edad, peso) VALUES ('Jose Cruz Castillo', 67, 160.0);",
        )

    def test_clipboard_selection_on_prueba_completa_valida_with_link(self):
        root_dir = Path(__file__).resolve().parent.parent
        full_code = (root_dir / "prueba_completa_valida.txt").read_text(encoding="utf-8")
        selection = "Estudiante.find(semestre).link(Curso).group(semestre).ifgroup(semestre > 3).up(semestre)"

        cleaned_selection = normalize_dsl_fragment(selection)
        session_symbols = SymbolTable()
        session_symbols.merge_from(build_context_symbol_table(full_code), overwrite=True)

        errores_lexicos.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            lexer.input(cleaned_selection)
            tokens = []
            while True:
                tok = lexer.token()
                if tok is None:
                    break
                tokens.append(tok)
        self.assertEqual(errores_lexicos, [])

        errores_sintacticos.clear()
        token_iter = iter(tokens)
        with contextlib.redirect_stdout(io.StringIO()):
            ast_sel = parser.parse(tokenfunc=lambda: next(token_iter, None))
        self.assertEqual(errores_sintacticos, [])

        analyzer = SemanticAnalyzer()
        with contextlib.redirect_stdout(io.StringIO()):
            sem_errors, sym_table = analyzer.analyze(
                ast_sel,
                persistent_symbols=session_symbols,
            )
        self.assertEqual(sem_errors, [])

        sql_list = SQLCodeGenerator(sym_table).generate(
            ast_sel,
            allowed_model_declarations=set(),
        )
        self.assertEqual(len(sql_list), 1)
        self.assertNotIn("CREATE TABLE", sql_list.script.upper())
        self.assertEqual(
            sql_list[0],
            "SELECT semestre FROM estudiante INNER JOIN curso ON estudiante.matricula = curso.id_estudiante GROUP BY semestre HAVING semestre > 3 ORDER BY semestre ASC;",
        )

    def test_symbol_table_merge_and_partial_broken_file_resilience(self):
        broken_code = """
model Valido:
  id_valido: auto main key
    nombre: string required

model RotoSinDosPuntos
    campo: num

Valido.new(nombre = "Prueba")
"""
        models = extract_context_models(broken_code)
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].name, "Valido")

        ctx_table = build_context_symbol_table(broken_code)
        self.assertIsNotNone(ctx_table.get_model("Valido"))
        self.assertIsNotNone(ctx_table.get_model("Valido").get_field("id_valido"))
        self.assertIsNotNone(ctx_table.get_model("Valido").get_field("nombre"))

        session_table = SymbolTable()
        session_table.merge_from(ctx_table, overwrite=True)
        # limpiar la tabal temp no debe borrar lo que ya se clono en la sesion
        ctx_table.clear()
        self.assertIsNotNone(session_table.get_model("Valido"))

    def test_multiline_method_chaining_preserves_exact_line_number_on_semantic_error(self):
        # cadena en varias lineas con punto al inicio para ver que marque error en la 10
        code_style_a = (
            "Model Estudiante:\n"
            "    matricula: auto main key\n"
            "    nombre: string required\n"
            "    edad: num\n"
            "\n"
            "Estudiante.find(matricula, nombre)\n"
            "    .if(edad >= 18)\n"
            "    // Comentario intermedio\n"
            "    .up(edad)\n"
            "    .take(-5)\n"
        )
        sem_err = analyze_source(code_style_a)
        self.assertEqual(len(sem_err), 1)
        self.assertIn("(Línea 10)", sem_err[0])
        self.assertIn("take()", sem_err[0])

        # cadena dejando el punto al final de cada linea y error en la 9
        code_style_b = (
            "Model Estudiante:\n"
            "    matricula: auto main key\n"
            "    nombre: string required\n"
            "    edad: num\n"
            "\n"
            "Estudiante.find(matricula, nombre).\n"
            "    if(edad >= 18).\n"
            "    up(edad).\n"
            "    take(-5)\n"
        )
        sem_err_b = analyze_source(code_style_b)
        self.assertEqual(len(sem_err_b), 1)
        self.assertIn("(Línea 9)", sem_err_b[0])
        self.assertIn("take()", sem_err_b[0])

    def test_prueba_errores_sintacticos_detects_all_six_syntax_errors(self):
        from pathlib import Path
        root_dir = Path(__file__).resolve().parent.parent
        error_file = root_dir / "prueba_errores_sintacticos.txt"
        self.assertTrue(error_file.is_file())
        source = error_file.read_text(encoding="utf-8")

        errores_lexicos.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            lexer.input(source if source.endswith("\n") else source + "\n")
            tokens = []
            while True:
                tok = lexer.token()
                if tok is None:
                    break
                tokens.append(tok)
        self.assertEqual(errores_lexicos, [])

        errores_sintacticos.clear()
        token_iter = iter(tokens)
        with contextlib.redirect_stdout(io.StringIO()):
            parser.parse(tokenfunc=lambda: next(token_iter, None))

        self.assertEqual(len(errores_sintacticos), 6)
        joined_errors = "\n".join(errores_sintacticos)
        # revisar que siga detectando los errores de las lineas 18 y 21
        self.assertIn("Línea 18", joined_errors)
        self.assertIn("Línea 21", joined_errors)


if __name__ == "__main__":
    unittest.main()
