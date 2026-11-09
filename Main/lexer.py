import re
import ply.lex as lex

errores_lexicos = []

reserved = {
    'model': 'MODEL', 
    'change': 'CHANGE', 
    'erase': 'ERASE',
    'main': 'MAIN', 
    'key': 'KEY', 
    'external': 'EXTERNAL',
    'required': 'REQUIRED',
    'unique': 'UNIQUE',
    'default': 'DEFAULT',
    'validate': 'VALIDATE',
    'auto': 'AUTO',
    'num': 'NUM',
    'string': 'STRING', 
    'text': 'TEXT', 
    'decimal': 'DECIMAL',
    'bool': 'BOOL', 
    'add': 'ADD', 
    'find': 'FIND',
    'modify': 'MODIFY', 
    'remove': 'REMOVE', 
    'empty': 'EMPTY',
    'if': 'IF',
    'in': 'IN',
    'and': 'AND',
    'or': 'OR',
    'not': 'NOT',
    'link': 'LINK',
    'similar': 'SIMILAR',
    'range': 'RANGE',
    'up': 'UP',
    'down': 'DOWN',
    'group': 'GROUP',
    'ifgroup': 'IFGROUP',
    'take': 'TAKE',
    'skip': 'SKIP',
    'alias': 'ALIAS',
    'count': 'COUNT',
    'sum': 'SUM',
    'avg': 'AVG',
    'max': 'MAX',
    'min': 'MIN',
    'true': 'TRUE', 
    'false': 'FALSE',
    'new': 'NEW'
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
    'INDENT',
    'DEDENT',
    'SALTO_LINEA'
] + list(reserved.values())

t_PLUS = r'\+'
t_MINUS = r'-'
t_TIMES = r'\*'
t_DIVIDE = r'/'
t_MODULO = r'%'
t_NOT_EQUAL = r'!='
t_LESS_EQUAL = r'<='
t_GREATER_EQUAL = r'>='
t_ASSIGN = r'='
t_LESS = r'<'
t_GREATER = r'>'

t_DOT = r'\.'
t_COLON = r':'
t_COMMA = r','
t_LPAREN = r'\('
t_RPAREN = r'\)'

t_ignore = ' \t\r'

_LEADING_INTERMEDIATE_COMMENTS_RE = re.compile(
    r'^(?:[ \t\r\n]+|//[^\n]*(?:\n|$)|/\*[\s\S]*?\*/)+'
)
_STYLE_A_CONTINUATION_RE = re.compile(r'^\.[a-zA-Z_]')
_STYLE_B_CONTINUATION_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*\s*\(')

def t_MULTILINE_COMMENT(t):
    r'/\*(.|\n)*?\*/'
    t.lexer.lineno += t.value.count('\n')

def t_SINGLE_COMMENT(t):
    r'//.*'
    pass

def find_column(input_text, token):
    line_start = input_text.rfind('\n', 0, token.lexpos)
    if line_start < 0:
        line_start = 0
    else:
        line_start += 1
    return (token.lexpos - line_start) + 1

def t_DATE_LITERAL(t):
    r'\d{4}-\d{2}-\d{2}'
    return t

def t_NUMBER_DECIMAL(t):
    r'(\d+\.\d*|\d*\.\d+)'
    t.value = float(t.value)
    return t

def t_NUMBER_INT(t):
    r'\d+'
    t.value = int(t.value)
    return t

def t_STRING_LITERAL(t):
    r'("[^"\n]*"|\'[^\'\n]*\')'
    t.value = t.value[1:-1]
    return t

def t_IDENTIFIER(t):
    r'[a-zA-Z][a-zA-Z0-9_]*'
    t.type = reserved.get(t.value.lower(), 'IDENTIFIER')
    return t

def t_SALTO_LINEA(t):
    r'([ \t\r]*\n)+[ \t]*'
    t.lexer.lineno += t.value.count('\n')

    rest = t.lexer.lexdata[t.lexer.lexpos:]
    rest_effective = _LEADING_INTERMEDIATE_COMMENTS_RE.sub('', rest)

    # Caso 1 (Estilo A): la siguiente línea efectiva continúa la cadena con '.metodo'
    if _STYLE_A_CONTINUATION_RE.match(rest_effective):
        return None

    # Caso 2 (Estilo B): la línea anterior terminó en '.' (DOT) sin líneas en blanco vacías
    # y la siguiente línea continúa con 'metodo('
    if getattr(t.lexer, 'last_token_type', None) == 'DOT' and t.value.count('\n') == 1:
        if _STYLE_B_CONTINUATION_RE.match(rest) or (
            rest.startswith(('//', '/*')) and _STYLE_B_CONTINUATION_RE.match(rest_effective)
        ):
            return None

    last_newline_idx = t.value.rfind('\n')
    whitespaces = t.value[last_newline_idx + 1:]

    indent_level = 0
    if rest.strip():
        for char in whitespaces:
            if char == '\t':
                indent_level += 4
            elif char == ' ':
                indent_level += 1

    t.type = 'SALTO_LINEA'
    t.value = '\n'

    if indent_level > t.lexer.indents[-1]:
        t.lexer.indents.append(indent_level)
        tok = lex.LexToken()
        tok.type = 'INDENT'
        tok.value = indent_level
        tok.lineno = t.lexer.lineno
        tok.lexpos = t.lexpos
        t.lexer.token_queue.append(tok)
    elif indent_level < t.lexer.indents[-1]:
        while indent_level < t.lexer.indents[-1]:
            t.lexer.indents.pop()
            tok = lex.LexToken()
            tok.type = 'DEDENT'
            tok.value = t.lexer.indents[-1]
            tok.lineno = t.lexer.lineno
            tok.lexpos = t.lexpos
            t.lexer.token_queue.append(tok)
        if indent_level != t.lexer.indents[-1]:
            msg = f"Error de indentación en la línea {t.lexer.lineno}: nivel {indent_level} no coincide con un bloque anterior."
            errores_lexicos.append(msg)
            print(msg)

    return t

def t_error(t):
    col = find_column(t.lexer.lexdata, t)
    msg = f"Error léxico: Carácter no permitido '{t.value[0]}' en línea {t.lexer.lineno}, columna {col}"
    errores_lexicos.append(msg)
    print(msg)
    t.lexer.skip(1)

lexer = lex.lex()
lexer.indents = [0]
lexer.token_queue = []
lexer.last_token_type = None

lexer._original_input = lexer.input
def input_wrapper(data):
    lexer.indents = [0]
    lexer.token_queue = []
    lexer.lineno = 1
    lexer.last_token_type = None
    lexer._original_input(data)
lexer.input = input_wrapper

lexer._original_token = lexer.token
def token_wrapper():
    if lexer.token_queue:
        tok = lexer.token_queue.pop(0)
        lexer.last_token_type = tok.type
        return tok
    
    tok = lexer._original_token()
    if tok is not None:
        lexer.last_token_type = tok.type
        return tok
        
    if len(lexer.indents) > 1:
        lexer.indents.pop()
        tok_dedent = lex.LexToken()
        tok_dedent.type = 'DEDENT'
        tok_dedent.value = lexer.indents[-1] if lexer.indents else 0
        tok_dedent.lineno = lexer.lineno
        tok_dedent.lexpos = lexer.lexpos
        lexer.last_token_type = tok_dedent.type
        return tok_dedent
        
    return None
lexer.token = token_wrapper

if __name__ == "__main__":
    cad = ''
    ruta_entrada = "C:/Users/varga/OneDrive/Desktop/CompiladorSQL/Prueba.txt"
    ruta_salida = "C:/Users/varga/Downloads/resultado.txt"
    
    try:
        with open(file=ruta_entrada, encoding='UTF-8', mode='r') as f:
            cad += f.read()

        codigo_prueba = cad
        lexer.input(codigo_prueba)
        
        with open(file=ruta_salida, encoding='UTF-8', mode='w') as f:
            while True:
                tok = lexer.token()
                if not tok:
                    break
                col = find_column(codigo_prueba, tok)
                print(f"Token(tipo='{tok.type}', valor={repr(tok.value)}, linea={tok.lineno}, columna={col})")
                f.write(f"<{tok.type},{repr(tok.value)},{tok.lineno},{col}>\n")
    except FileNotFoundError:
        print("Error: No se encontró el archivo en la ruta especificada.")
