import sys
from pathlib import Path
from lexer import lexer, errores_lexicos
from parser import parser, errores_sintacticos
from visitor import ASTPrinter
from semantic import SemanticAnalyzer
from codegen import SQLCodeGenerator
from db_executor import PostgresExecutor

ROOT_DIR = Path(__file__).resolve().parent.parent
SQL_OUT_DIR = ROOT_DIR / "sql_generado"
analyzer = SemanticAnalyzer()


def analizar_archivo(ruta: Path, ejecutar_pg: bool = False):
    print("\n" + "=" * 75)
    print(f"ANALIZANDO ARCHIVO: {ruta.name}")
    print("=" * 75)
    if not ruta.is_file():
        print(f"[!] El archivo '{ruta}' no existe.")
        return None

    codigo_prueba = ruta.read_text(encoding="utf-8")
    if not codigo_prueba.endswith("\n"):
        codigo_prueba += "\n"

    # primero sacamos los tokens con el lexer
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
        return None

    # armamos el arbol sintactico
    errores_sintacticos.clear()
    token_iterator = iter(tokens)
    ast_resultado = parser.parse(tokenfunc=lambda: next(token_iterator, None))

    if errores_sintacticos:
        print(f"\n[Fase Sintáctica] Se encontraron {len(errores_sintacticos)} errores sintácticos.")
        print("[Fase Semántica] Omitida debido a errores sintácticos previos.")
        print("=" * 75)
        return None

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
        print("[Fase de Generación SQL] Omitida debido a errores semánticos previos.")
        print("=" * 75)
        return None

    print("\n[Fase Semántica] ÉXITO (0 errores semánticos).")

    # pasamos el arbol a codigo sql de postgres
    generador = SQLCodeGenerator(tabla_simbolos)
    sentencias_sql = generador.generate(ast_resultado)
    script_sql = sentencias_sql.script

    print("\n--- Código SQL Generado (PostgreSQL) ---")
    for idx, stmt in enumerate(sentencias_sql, start=1):
        print(f"\n-- [{idx}]")
        print(stmt)

    SQL_OUT_DIR.mkdir(parents=True, exist_ok=True)
    archivo_sql = SQL_OUT_DIR / f"{ruta.stem}.sql"
    archivo_sql.write_text(script_sql + ("\n" if script_sql else ""), encoding="utf-8")
    print(f"\n[Fase Generación SQL] ÉXITO ({len(sentencias_sql)} sentencias generadas).")
    print(f"[Archivo SQL guardado] {archivo_sql}")

    # si pusieron el flag de ejecusion lo corremos en postgres
    if ejecutar_pg and sentencias_sql:
        executor = PostgresExecutor()
        reporte = executor.execute_statements(sentencias_sql, reset_tables=True, ensure_db=True)
        print(reporte.format_report())

    print("=" * 75)
    return sentencias_sql


if __name__ == "__main__":
    flags_ejecucion = {"--execute", "--pg", "-x"}
    ejecutar_en_postgres = any(arg.lower() in flags_ejecucion for arg in sys.argv[1:])
    argumentos_archivos = [arg for arg in sys.argv[1:] if arg.lower() not in flags_ejecucion]

    if argumentos_archivos:
        for arg in argumentos_archivos:
            ruta_arg = Path(arg)
            if not ruta_arg.is_absolute():
                ruta_arg = ROOT_DIR / arg
            analizar_archivo(ruta_arg, ejecutar_pg=ejecutar_en_postgres)
    else:
        archivos_default = [
            "Prueba.txt",
            "prueba_completa_valida.txt",
            "prueba_expresiones_y_cadenas.txt",
            "prueba_errores_sintacticos.txt",
            "Prueba_Errores_Semanticos.txt",
        ]
        archivos_raiz = {p.name.lower(): p for p in ROOT_DIR.iterdir() if p.is_file()}
        encontrados = [
            archivos_raiz[nombre.lower()]
            for nombre in archivos_default
            for _ in [1]
            if nombre.lower() in archivos_raiz
        ]
        if not encontrados:
            print("No se encontraron archivos de prueba en la raíz del proyecto.")
        for ruta in encontrados:
            analizar_archivo(ruta, ejecutar_pg=ejecutar_en_postgres)
