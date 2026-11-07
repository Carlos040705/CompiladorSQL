import sys
from pathlib import Path
from lexer import lexer, errores_lexicos
from parser import parser, errores_sintacticos
from visitor import ASTPrinter
from semantic import SemanticAnalyzer

ROOT_DIR = Path(__file__).resolve().parent.parent
analyzer = SemanticAnalyzer()


def analizar_archivo(ruta: Path):
    print("\n" + "=" * 75)
    print(f"ANALIZANDO ARCHIVO: {ruta.name}")
    print("=" * 75)
    if not ruta.is_file():
        print(f"[!] El archivo '{ruta}' no existe.")
        return

    codigo_prueba = ruta.read_text(encoding="utf-8")
    if not codigo_prueba.endswith("\n"):
        codigo_prueba += "\n"

    errores_lexicos.clear()
    lexer.input(codigo_prueba)
    tokens = []
    while True:
        token = lexer.token()
        if token is None:
            break
        tokens.append(token)

    if errores_lexicos:
        print(f"\n[Fase Léxica] Se encontraron {len(errores_lexicos)} errores léxicos.")
        print("[Fase Sintáctica] Omitida debido a errores léxicos previos.")
        print("[Fase Semántica] Omitida debido a errores léxicos previos.")
        print("=" * 75)
        return

    errores_sintacticos.clear()
    token_iterator = iter(tokens)
    ast_resultado = parser.parse(tokenfunc=lambda: next(token_iterator, None))

    if errores_sintacticos:
        print(f"\n[Fase Sintáctica] Se encontraron {len(errores_sintacticos)} errores sintácticos.")
        print("[Fase Semántica] Omitida debido a errores sintácticos previos.")
    else:
        print("\n[Fase Sintáctica] ÉXITO (0 errores sintácticos).")
        print("\n--- Árbol Sintáctico Abstracto (AST) ---")
        if ast_resultado:
            printer = ASTPrinter()
            printer.visit(ast_resultado)

        print("\n--- Iniciando Análisis Semántico ---")
        errores_sem, tabla_simbolos = analyzer.analyze(ast_resultado)
        tabla_simbolos.print_table()

        if errores_sem:
            print(f"\n[Fase Semántica] Se encontraron {len(errores_sem)} errores semánticos.")
        else:
            print("\n[Fase Semántica] ÉXITO (0 errores semánticos). La generación SQL aún no está implementada.")
    print("=" * 75)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            ruta_arg = Path(arg)
            if not ruta_arg.is_absolute():
                ruta_arg = ROOT_DIR / arg
            analizar_archivo(ruta_arg)
    else:
        archivos_default = [
            "Prueba.txt",
            "Prueba_Completa_Valida.txt",
            "Prueba_Expresiones_y_Cadenas.txt",
            "Prueba_Errores_Sintacticos.txt",
            "Prueba_Errores_Semanticos.txt",
        ]
        encontrados = [ROOT_DIR / nombre for nombre in archivos_default if (ROOT_DIR / nombre).is_file()]
        if not encontrados:
            print("No se encontraron archivos de prueba en la raíz del proyecto.")
        for ruta in encontrados:
            analizar_archivo(ruta)
