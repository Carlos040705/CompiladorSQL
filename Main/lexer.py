import ply.lex as lex;

reserved = {
    'Model': 'MODEL', 
    'Change': 'CHANGE', 
    'Erase': 'ERASE',
    'Main': 'MAIN', 
    'Key': 'KEY', 
    'External': 'EXTERNAL',
    'Required': 'REQUIRED',
    'Unique': 'UNIQUE',
    'Default': 'DEFAULT',
    'Validate': 'VALIDATE',
    'Auto': 'AUTO',
    'Num': 'NUM',
    'String': 'STRING', 
    'Text': 'TEXT', 
    'Decimal': 'DECIMAL',
    'Bool': 'BOOL', 
    'Add': 'ADD', 
    'Find': 'FIND',
    'Modify': 'MODIFY', 
    'Remove': 'REMOVE', 
    'Empty': 'EMPTY',
    'If' : 'IF',
    'In' : 'IN',
    'And' : 'AND',
    'Or' : 'OR',
    'Not' : 'NOT',
    'Link' : 'LINK',
    'Similar' : 'SIMILAR',
    'Range' : 'RANGE',
    'Up' : 'UP',
    'Down' : 'DOWN',
    'Group' : 'GROUP',
    'IfGroup' : 'IFGROUP',
    'Take' : 'TAKE',
    'Skip' : 'SKIP',
    'Alias' : 'ALIAS',
    'Count' : 'COUNT',
    #
    'true': 'TRUE', 
    'false': 'FALSE',
    'new' : 'NEW'
}

tokens = [
    'IDENTIFIER', 
    'NUMBER_INT', 
    'NUMBER_DECIMAL', 
    'STRING_LITERAL', 
    'DATE_LITERAL',
    'PLUS', 'MINUS', 
    'TIMES', 
    'DIVIDE', 
    'MODULO', 
    'ASSIGN', 
    'EQUAL', 
    'NOT_EQUAL',
    'LESS', 
    'GREATER', 
    'LESS_EQUAL', 
    'GREATER_EQUAL',
    'DOT', 
    'COLON', 
    'COMMA', 
    'LPAREN', 
    'RPAREN', 
] + list(reserved.values())

t_PLUS = r'\+'
t_MINUS = r'-'
t_TIMES = r'\*'
t_DIVIDE = r'/'
t_MODULO = r'%'
t_ASSIGN = r'='
t_EQUAL = r'=='
t_NOT_EQUAL = r'!='
t_LESS = r'<'
t_GREATER = r'>'
t_LESS_EQUAL = r'<='
t_GREATER_EQUAL = r'>='

t_DOT = r'\.'
t_COLON = r':'
t_COMMA = r','
t_LPAREN = r'\('
t_RPAREN = r'\)'

t_ignore = ' \t'

def find_column(input_text, token):
    line_start = input_text.rfind('\n', 0, token.lexpos)
    if line_start < 0:
        line_start = 0
    else:
        line_start += 1
    return (token.lexpos - line_start) + 1

def t_DATE_LITERAL(t):
    r'\d{4}-\d{2}-\d{2}'
    t.column = find_column(t.lexer.lexdata, t)
    return t

def t_NUMBER_DECIMAL(t):
    r'\d+\.\d+'
    t.value = float(t.value)
    t.column = find_column(t.lexer.lexdata, t)
    return t

def t_NUMBER_INT(t):
    r'\d+'
    t.value = int(t.value)
    t.column = find_column(t.lexer.lexdata, t)
    return t

def t_STRING_LITERAL(t):
    r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\''
    t.value = t.value[1:-1]
    t.column = find_column(t.lexer.lexdata, t)
    return t

def t_IDENTIFIER(t):
    r'[a-zA-Z][a-zA-Z0-9_]*'
    t.type = reserved.get(t.value, 'IDENTIFIER')
    t.column = find_column(t.lexer.lexdata, t)
    return t

def t_newline(t):
    r'\n+'
    t.lexer.lineno += len(t.value)
    

def t_error(t):
    col = find_column(t.lexer.lexdata, t)
    print(f"Error léxico: Carácter no permitido '{t.value[0]}' en línea {t.lexer.lineno}, columna {col}")
    t.lexer.skip(1)

lexer = lex.lex()

if __name__ == "__main__":
    cad =''
''' with open(file=r'C:\Users\varga\OneDrive\Desktop\CompiladorSQL\Main\Prueba.txt', encoding='UTF-8', mode='r') as f:
        cad += f.read()

    codigo_prueba = cad
    lexer.input(codigo_prueba)
    with open(file=r'C:\Users\varga\OneDrive\Desktop\CompiladorSQL\Main\resultado.txt', encoding='UTF-8', mode='w') as f:
        while True:
            tok = lexer.token()
            if not tok:
                break
            print(f"Token(tipo='{tok.type}', valor='{tok.value}', linea={tok.lineno}, columna={tok.lexpos})")
            f.write(f"<'{tok.type}','{tok.value}','{tok.lineno}','{tok.lexpos}'>\n")
'''