import ply.yacc as yacc
from lexer import tokens, lexer
from ast_nodes import Program, ModelDeclaration, Field, DataType, Constraint, DbOperation, Parameter, Literal, Identifier

# pila de errores
errores_sintacticos = []


#gramática 
def p_start(p):
    '''start : programa'''
    p[0] = Program(p[1])

# <programa> -> <sentencia> <programa> | <sentencia>
def p_programa_multiple(p):
    '''programa : sentencia programa'''
    if p[1] == '\n':
        p[0] = p[2]
    else:
        p[0] = [p[1]] + p[2]

def p_programa_simple(p):
    '''programa : sentencia'''
    if p[1] == '\n':
        p[0] = []
    else:
        p[0] = [p[1]]

# <sentencia> -> <declaracion_modelo> | <operacion_db> | SALTO_LINEA
def p_sentencia(p):
    '''
    sentencia : declaracion_modelo
              | operacion_db
              | SALTO_LINEA
    '''
    p[0] = p[1]

def p_declaracion_modelo(p):
    '''declaracion_modelo : MODEL IDENTIFIER COLON SALTO_LINEA INDENT lista_campos DEDENT'''
    # se filtran líneas en blanco
    campos_validos = [c for c in p[6] if c is not None]
    p[0] = ModelDeclaration(p[2], campos_validos)

def p_lista_campos_multiple(p):
    '''
    lista_campos : campo SALTO_LINEA lista_campos
                 | SALTO_LINEA lista_campos
    '''
    if len(p) == 4:
        p[0] = [p[1]] + p[3]
    else:
        p[0] = p[2]

def p_lista_campos_simple(p):
    '''
    lista_campos : campo SALTO_LINEA
                 | campo
                 | SALTO_LINEA
    '''
    if len(p) == 2 and p[1] == '\n':
        p[0] = []
    else:
        p[0] = [p[1]]

# <campo> -> IDENTIFIER COLON tipo_dato restricciones_opt
def p_campo(p):
    '''campo : IDENTIFIER COLON tipo_dato restricciones_opt'''
    p[0] = Field(p[1], p[3], p[4])

# <tipo_dato>
def p_tipo_dato_simple(p):
    '''
    tipo_dato : STRING
              | AUTO
              | NUM
              | TEXT
              | BOOL
    '''
    p[0] = DataType(p[1])

def p_tipo_dato_decimal(p):
    '''tipo_dato : DECIMAL LPAREN NUMBER_INT COMMA NUMBER_INT RPAREN'''
    p[0] = DataType('DECIMAL', [p[3], p[5]])

# <restricciones_opt>
def p_restricciones_opt_multiple(p):
    '''restricciones_opt : restriccion restricciones_opt'''
    p[0] = [p[1]] + p[2]

def p_restricciones_opt_vacia(p):
    '''restricciones_opt : '''
    p[0] = []

def p_restriccion(p):
    '''
    restriccion : REQUIRED
                | UNIQUE
                | MAIN KEY
                | EXTERNAL KEY
    '''
    if len(p) == 2:
        p[0] = Constraint(p[1])
    else:
        p[0] = Constraint(f"{p[1]} {p[2]}")

def p_restriccion_default(p):
    '''restriccion : DEFAULT ASSIGN valor'''
    p[0] = Constraint('DEFAULT', p[3])

def p_operacion_db(p):
    '''operacion_db : IDENTIFIER DOT metodo LPAREN argumentos_opt RPAREN'''
    p[0] = DbOperation(p[1], p[3], p[5])

def p_metodo(p):
    '''
    metodo : FIND
           | NEW
           | MODIFY
           | REMOVE
           | ADD
           | COUNT
           | SUM
           | AVG
           | MAX
           | MIN
           | IDENTIFIER
    '''
    p[0] = p[1]

def p_argumentos_opt(p):
    '''argumentos_opt : lista_argumentos'''
    p[0] = p[1]

def p_argumentos_opt_vacia(p):
    '''argumentos_opt : '''
    p[0] = []

def p_lista_argumentos_multiple(p):
    '''lista_argumentos : parametro COMMA lista_argumentos'''
    p[0] = [p[1]] + p[2]

def p_lista_argumentos_simple(p):
    '''lista_argumentos : parametro'''
    p[0] = [p[1]]

# <parametro> -> IDENTIFIER ASSIGN expresion
def p_parametro(p):
    '''parametro : IDENTIFIER ASSIGN expresion'''
    p[0] = Parameter(p[1], p[3])

def p_expresion(p):
    '''expresion : valor'''
    p[0] = p[1]

def p_valor(p):
    '''
    valor : STRING_LITERAL
          | NUMBER_INT
          | NUMBER_DECIMAL
          | DATE_LITERAL
          | TRUE
          | FALSE
          | EMPTY
    '''
    p[0] = Literal(p[1], p.slice[1].type)

def p_valor_identifier(p):
    '''valor : IDENTIFIER'''
    p[0] = Identifier(p[1])

#manejo de errores
def p_error(p):
    if p:
        linea_inicio = p.lexer.lexdata.rfind('\n', 0, p.lexpos)
        col = (p.lexpos - linea_inicio) if linea_inicio >= 0 else p.lexpos + 1
        msg = f"[!] Error Sintáctico: Token inesperado '{p.value}' (Tipo: {p.type}) en Línea {p.lineno}, Columna {col}."
        errores_sintacticos.append(msg)
        print(msg)
        parser.errok()
    else:
        msg = "[!] Error Sintáctico: Fin de archivo inesperado (EOF)."
        errores_sintacticos.append(msg)
        print(msg)


parser = yacc.yacc()