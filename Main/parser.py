import ply.yacc as yacc
from lexer import tokens, lexer

# Pila / Lista global de errores sintácticos
errores_sintacticos = []

# =====================================================================
# REGLAS SINTÁCTICAS (Gramática GBD adaptada a tokens de lexer.py)
# =====================================================================

# <programa> -> <sentencia> <programa> | <sentencia>
def p_programa_multiple(p):
    '''programa : sentencia programa'''
    p[0] = [p[1]] + p[2]

def p_programa_simple(p):
    '''programa : sentencia'''
    p[0] = [p[1]]

# <sentencia> -> <declaracion_modelo> | <operacion_db>
def p_sentencia(p):
    '''
    sentencia : declaracion_modelo
              | operacion_db
    '''
    p[0] = p[1]

# ---------------------------------------------------------------------
# Declaración de Modelos (Creación de Tablas)
# <declaracion_modelo> -> MODEL IDENTIFIER COLON lista_campos
# ---------------------------------------------------------------------
def p_declaracion_modelo(p):
    '''declaracion_modelo : MODEL IDENTIFIER COLON lista_campos'''
    p[0] = {
        'nodo': 'DECLARACION_MODELO',
        'tabla': p[2],
        'campos': p[4]
    }

def p_lista_campos_multiple(p):
    '''lista_campos : campo lista_campos'''
    p[0] = [p[1]] + p[2]

def p_lista_campos_simple(p):
    '''lista_campos : campo'''
    p[0] = [p[1]]

# <campo> -> IDENTIFIER COLON tipo_dato restricciones_opt
def p_campo(p):
    '''campo : IDENTIFIER COLON tipo_dato restricciones_opt'''
    p[0] = {
        'campo': p[1],
        'tipo': p[3],
        'restricciones': p[4]
    }

# <tipo_dato>
def p_tipo_dato_simple(p):
    '''
    tipo_dato : STRING
              | AUTO
              | NUM
              | TEXT
              | BOOL
    '''
    p[0] = p[1]

def p_tipo_dato_decimal(p):
    '''tipo_dato : DECIMAL LPAREN NUMBER_INT COMMA NUMBER_INT RPAREN'''
    p[0] = f"DECIMAL({p[3]},{p[5]})"

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
                | KEY
                | EXTERNAL
    '''
    p[0] = p[1]

def p_restriccion_default(p):
    '''restriccion : DEFAULT ASSIGN valor'''
    p[0] = f"DEFAULT={p[3]}"

# ---------------------------------------------------------------------
# Operaciones de Base de Datos (Consultas, Inserciones, etc.)
# <operacion_db> -> IDENTIFIER DOT metodo LPAREN argumentos_opt RPAREN
# ---------------------------------------------------------------------
def p_operacion_db(p):
    '''operacion_db : IDENTIFIER DOT metodo LPAREN argumentos_opt RPAREN'''
    p[0] = {
        'nodo': 'OPERACION_DB',
        'modelo': p[1],
        'metodo': p[3],
        'argumentos': p[5]
    }

def p_metodo(p):
    '''
    metodo : FIND
           | NEW
           | MODIFY
           | REMOVE
           | ADD
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
    p[0] = {
        'parametro': p[1],
        'valor': p[3]
    }

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
          | IDENTIFIER
    '''
    p[0] = p[1]

# =====================================================================
# MANEJO DE ERRORES SINTÁCTICOS (Modo Pánico)
# =====================================================================
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

# Construcción del analizador sintáctico
parser = yacc.yacc()