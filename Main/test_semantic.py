import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from lexer import errores_lexicos, lexer
from main import analizar_archivo
from parser import errores_sintacticos, parser
from semantic import SemanticAnalyzer


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


if __name__ == "__main__":
    unittest.main()
