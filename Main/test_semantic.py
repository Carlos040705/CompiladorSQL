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


if __name__ == "__main__":
    unittest.main()
