from lexer import lexer
from parser import parser, errores_sintacticos
from visitor import ASTPrinter

#reemplazar con la ruta al archivo de prueba incluido (CompiladorSQL/Prueba.txt)
ruta_entrada = "C:/Users/varga/OneDrive/Desktop/CompiladorSQL/Prueba.txt" 
cad = ''
with open(ruta_entrada, encoding= "UTF-8", mode= 'r') as f:
    cad += f.read()
    

codigo_prueba = cad

# ejecución de prueba
ast_resultado = parser.parse(codigo_prueba, lexer=lexer)

print("="*50)
if errores_sintacticos:
    print("error")
    for err in errores_sintacticos:
        print(err)
else:
    print("exito")
    print("arbol: ")
    if ast_resultado:
        printer = ASTPrinter()
        printer.visit(ast_resultado)
print("="*50)