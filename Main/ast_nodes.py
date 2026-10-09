class Node:
    """Clase base para todos los nodos del AST"""
    def accept(self, visitor):
        pass

class Program(Node):
    def __init__(self, statements):
        self.statements = statements # Lista de sentencias (ModelDeclaration, DbOperation)

    def __repr__(self):
        return f"Program(statements={self.statements})"

# ==========================================
# DECLARACIÓN DE MODELOS
# ==========================================

class ModelDeclaration(Node):
    def __init__(self, name, fields):
        self.name = name
        self.fields = fields # Lista de Field

    def __repr__(self):
        return f"ModelDeclaration(name={self.name}, fields={self.fields})"

class Field(Node):
    def __init__(self, name, data_type, constraints=None):
        self.name = name
        self.data_type = data_type
        self.constraints = constraints or []

    def __repr__(self):
        return f"Field(name={self.name}, type={self.data_type}, constraints={self.constraints})"

class DataType(Node):
    def __init__(self, type_name, args=None):
        self.type_name = type_name
        self.args = args or [] # Para tipos como DECIMAL(10,2)

    def __repr__(self):
        if self.args:
            return f"DataType({self.type_name}, args={self.args})"
        return f"DataType({self.type_name})"

class Constraint(Node):
    def __init__(self, constraint_type, value=None):
        self.constraint_type = constraint_type
        self.value = value # Para constraints como DEFAULT = valor

    def __repr__(self):
        if self.value is not None:
            return f"Constraint({self.constraint_type}, value={self.value})"
        return f"Constraint({self.constraint_type})"

# ==========================================
# OPERACIONES DE BASE DE DATOS
# ==========================================

class DbOperation(Node):
    def __init__(self, model_name, method, arguments=None):
        self.model_name = model_name
        self.method = method # Find, Add, Modify, Remove, etc.
        self.arguments = arguments or []

    def __repr__(self):
        return f"DbOperation(model={self.model_name}, method={self.method}, arguments={self.arguments})"

class Parameter(Node):
    def __init__(self, name, value):
        self.name = name
        self.value = value # Puede ser una Expression

    def __repr__(self):
        return f"Parameter(name={self.name}, value={self.value})"

# ==========================================
# EXPRESIONES Y VALORES
# ==========================================

class Expression(Node):
    pass

class Literal(Expression):
    def __init__(self, value, literal_type):
        self.value = value
        self.literal_type = literal_type # STRING_LITERAL, NUMBER_INT, NUMBER_DECIMAL, DATE_LITERAL, BOOL, EMPTY

    def __repr__(self):
        return f"Literal({self.value}, type={self.literal_type})"

class Identifier(Expression):
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"Identifier({self.name})"

class BinaryOperation(Expression):
    def __init__(self, left, operator, right):
        self.left = left
        self.operator = operator
        self.right = right

    def __repr__(self):
        return f"BinaryOperation({self.left} {self.operator} {self.right})"

class UnaryOperation(Expression):
    def __init__(self, operator, operand):
        self.operator = operator
        self.operand = operand

    def __repr__(self):
        return f"UnaryOperation({self.operator}{self.operand})"
