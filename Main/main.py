from lexer import lexer
from parser import parser, errores_sintacticos
from visitor import ASTPrinter

ruta_entrada = "C:/Users/varga/OneDrive/Desktop/CompiladorSQL/Prueba.txt" 
cad = ''
with open(ruta_entrada, encoding= "UTF-8", mode= 'r') as f:
    cad += f.read()
    

codigo_prueba = cad

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
    if ast_resultado:
        printer = ASTPrinter()
        printer.visit(ast_resultado)
print("="*50)