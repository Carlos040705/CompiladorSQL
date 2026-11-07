from pathlib import Path
import ply.yacc as yacc
from lexer import tokens, lexer
from ast_nodes import (
    Program, ModelDeclaration, Field, DataType, Constraint,
    DbOperation, MethodCall, Parameter, Literal, Identifier,
    BinaryOperation, UnaryOperation
)

# Pila global de errores sintácticos
errores_sintacticos = []

start = 'start'


def p_start(p):
    '''start : programa'''
    p[0] = Program(p[1], lineno=1)


# 2.2.1 Programa en general
def p_programa_multiple(p):
    '''programa : sentencia programa'''
    if p[1] == '\n' or p[1] is None:
        p[0] = p[2]
    else:
        p[0] = [p[1]] + p[2]


def p_programa_simple(p):
    '''programa : sentencia'''
    if p[1] == '\n' or p[1] is None:
        p[0] = []
    else:
        p[0] = [p[1]]


def p_sentencia(p):
    '''
    sentencia : declaracion_modelo
              | operacion_db
              | SALTO_LINEA
    '''
    p[0] = p[1]


# Recuperación en modo pánico a nivel de sentencia (sincroniza en SALTO_LINEA o DEDENT)
def p_sentencia_error(p):
    '''
    sentencia : error SALTO_LINEA
              | error DEDENT
    '''
    p[0] = '\n'


# 2.2.2 Declaración de modelos (creación de tablas)
def p_declaracion_modelo(p):
    '''declaracion_modelo : MODEL IDENTIFIER COLON SALTO_LINEA INDENT lista_campos DEDENT'''
    campos_validos = [c for c in p[6] if c is not None]
    p[0] = ModelDeclaration(p[2], campos_validos, lineno=p.lineno(1))


def p_declaracion_modelo_error(p):
    '''declaracion_modelo : MODEL error SALTO_LINEA INDENT lista_campos DEDENT'''
    p[0] = '\n'


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


def p_campo(p):
    '''campo : IDENTIFIER COLON tipo_dato restricciones_opt'''
    p[0] = Field(p[1], p[3], p[4], lineno=p.lineno(1))


# 2.2.3 Tipos de datos y restricciones
def p_tipo_dato_simple(p):
    '''
    tipo_dato : STRING
              | AUTO
              | NUM
              | TEXT
              | BOOL
    '''
    p[0] = DataType(p[1].upper(), lineno=p.lineno(1))


def p_tipo_dato_decimal(p):
    '''tipo_dato : DECIMAL LPAREN NUMBER_INT COMMA NUMBER_INT RPAREN'''
    p[0] = DataType('DECIMAL', [p[3], p[5]], lineno=p.lineno(1))


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
        p[0] = Constraint(p[1].upper(), lineno=p.lineno(1))
    else:
        p[0] = Constraint(f"{p[1].upper()} {p[2].upper()}", lineno=p.lineno(1))


def p_restriccion_default(p):
    '''restriccion : DEFAULT ASSIGN factor'''
    p[0] = Constraint('DEFAULT', p[3], lineno=p.lineno(1))


# 2.2.4 Operaciones sobre modelos y encadenamiento de métodos
def p_operacion_db(p):
    '''operacion_db : IDENTIFIER cadena_metodos'''
    p[0] = DbOperation(p[1], p[2], lineno=p.lineno(1))


def p_cadena_metodos_multiple(p):
    '''cadena_metodos : DOT llamada_metodo cadena_metodos'''
    p[0] = [p[2]] + p[3]


def p_cadena_metodos_simple(p):
    '''cadena_metodos : DOT llamada_metodo'''
    p[0] = [p[2]]


def p_llamada_metodo(p):
    '''llamada_metodo : metodo LPAREN argumentos_opt RPAREN'''
    p[0] = MethodCall(p[1], p[3], lineno=p.lineno(2))


def p_metodo(p):
    '''
    metodo : NEW
           | FIND
           | MODIFY
           | REMOVE
           | ADD
           | IF
           | LINK
           | GROUP
           | IFGROUP
           | UP
           | DOWN
           | TAKE
           | SKIP
           | COUNT
           | SUM
           | AVG
           | MAX
           | MIN
           | IDENTIFIER
    '''
    p[0] = p[1].lower() if isinstance(p[1], str) else p[1]


# 2.2.5 Parámetros y valores
def p_argumentos_opt(p):
    '''argumentos_opt : lista_argumentos'''
    p[0] = p[1]


def p_argumentos_opt_vacia(p):
    '''argumentos_opt : '''
    p[0] = []


def p_lista_argumentos_multiple(p):
    '''lista_argumentos : parametro COMMA lista_argumentos'''
    p[0] = [p[1]] + p[3]


def p_lista_argumentos_simple(p):
    '''lista_argumentos : parametro'''
    p[0] = [p[1]]


def p_parametro(p):
    '''parametro : expresion'''
    if isinstance(p[1], BinaryOperation) and p[1].operator == '=' and isinstance(p[1].left, Identifier):
        p[0] = Parameter(p[1].left.name, p[1].right, lineno=p[1].lineno)
    else:
        p[0] = p[1]


# 2.2.6 Operaciones lógicas, relacionales, aritméticas y unarias
# Precedencia de mayor a menor: () > OP_UNARIO > OP_MULT_DIV_MOD > OP_SUMA_RESTA > OP_RELACIONAL > NOT > AND > OR
def p_expresion(p):
    '''expresion : expresion_or'''
    p[0] = p[1]


def p_expresion_or_binaria(p):
    '''expresion_or : expresion_or OR expresion_and'''
    p[0] = BinaryOperation(p[1], 'OR', p[3], lineno=p.lineno(2))


def p_expresion_or_simple(p):
    '''expresion_or : expresion_and'''
    p[0] = p[1]


def p_expresion_and_binaria(p):
    '''expresion_and : expresion_and AND expresion_not'''
    p[0] = BinaryOperation(p[1], 'AND', p[3], lineno=p.lineno(2))


def p_expresion_and_simple(p):
    '''expresion_and : expresion_not'''
    p[0] = p[1]


def p_expresion_not_unaria(p):
    '''expresion_not : NOT expresion_not'''
    p[0] = UnaryOperation('NOT', p[2], lineno=p.lineno(1))


def p_expresion_not_simple(p):
    '''expresion_not : expresion_relacional'''
    p[0] = p[1]


def p_expresion_relacional_binaria(p):
    '''expresion_relacional : expresion_aritmetica op_relacional expresion_aritmetica'''
    p[0] = BinaryOperation(p[1], p[2][0], p[3], lineno=p[2][1])


def p_expresion_relacional_simple(p):
    '''expresion_relacional : expresion_aritmetica'''
    p[0] = p[1]


def p_op_relacional(p):
    '''
    op_relacional : ASSIGN
                  | NOT_EQUAL
                  | LESS
                  | GREATER
                  | LESS_EQUAL
                  | GREATER_EQUAL
    '''
    p[0] = (p[1], p.lineno(1))


def p_expresion_aritmetica_binaria(p):
    '''expresion_aritmetica : expresion_aritmetica op_suma_resta termino'''
    p[0] = BinaryOperation(p[1], p[2][0], p[3], lineno=p[2][1])


def p_expresion_aritmetica_simple(p):
    '''expresion_aritmetica : termino'''
    p[0] = p[1]


def p_op_suma_resta(p):
    '''
    op_suma_resta : PLUS
                  | MINUS
    '''
    p[0] = (p[1], p.lineno(1))


def p_termino_binario(p):
    '''termino : termino op_mult_div_mod factor'''
    p[0] = BinaryOperation(p[1], p[2][0], p[3], lineno=p[2][1])


def p_termino_simple(p):
    '''termino : factor'''
    p[0] = p[1]


def p_op_mult_div_mod(p):
    '''
    op_mult_div_mod : TIMES
                    | DIVIDE
                    | MODULO
    '''
    p[0] = (p[1], p.lineno(1))


def p_factor_agrupacion(p):
    '''factor : LPAREN expresion RPAREN'''
    p[0] = p[2]


def p_factor_unario(p):
    '''factor : op_unario factor'''
    p[0] = UnaryOperation(p[1][0], p[2], lineno=p[1][1])


def p_factor_valor(p):
    '''factor : valor'''
    p[0] = p[1]


def p_op_unario(p):
    '''
    op_unario : PLUS
              | MINUS
    '''
    p[0] = (p[1], p.lineno(1))


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
    p[0] = Literal(p[1], p.slice[1].type, lineno=p.lineno(1))


def p_valor_identifier(p):
    '''valor : IDENTIFIER'''
    p[0] = Identifier(p[1], lineno=p.lineno(1))


# 2.3 Manejo de errores sintácticos con recuperación en modo pánico
def p_error(p):
    if p:
        linea_inicio = p.lexer.lexdata.rfind('\n', 0, p.lexpos)
        col = (p.lexpos - linea_inicio) if linea_inicio >= 0 else p.lexpos + 1
        valor_mostrar = '\\n' if p.value == '\n' else p.value
        msg = f"[!] Error Sintáctico: Token inesperado '{valor_mostrar}' (Tipo: {p.type}) en Línea {p.lineno}, Columna {col}."
        errores_sintacticos.append(msg)
        print(msg)
    else:
        msg = "[!] Error Sintáctico: Fin de archivo inesperado (EOF)."
        errores_sintacticos.append(msg)
        print(msg)


parser = yacc.yacc(outputdir=str(Path(__file__).resolve().parent))
