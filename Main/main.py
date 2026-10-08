import psycopg2;
import sys;
import ast;
from lexer import lexer
from parser import parser, errores_sintacticos

codigo_prueba = "Estudiante.find(edad = 67)"

# Ejecución del parser pasando el código y el lexer
ast_resultado = parser.parse(codigo_prueba, lexer=lexer)

print("="*50)
if errores_sintacticos:
    print("SE ENCONTRARON ERRORES SINTÁCTICOS:")
    for err in errores_sintacticos:
        print(err)
else:
    print("¡ANÁLISIS SINTÁCTICO EXITOSO!")
    print("ÁRBOLES SINTÁCTICOS / ESTRUCTURA RESULTANTE (AST):")
    print(ast_resultado)
print("="*50)