class Node:
    """Clase base para todos los nodos del 'arbol'"""
    def accept(self, visitor):
        pass

class Program(Node):
    def __init__(self, statements):
        self.statements = statements # lista de sentencias (ModelDeclaration, DbOperation)

    def __repr__(self):
        return f"Program(statements={self.statements})"


#Clases modelo
class ModelDeclaration(Node):
    def __init__(self, name, fields):
        self.name = name
        self.fields = fields 

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
        self.args = args or [] # para tipos como DECIMAL(10,2)

    def __repr__(self):
        if self.args:
            return f"DataType({self.type_name}, args={self.args})"
        return f"DataType({self.type_name})"

class Constraint(Node):
    def __init__(self, constraint_type, value=None):
        self.constraint_type = constraint_type
        self.value = value # para constraints como DEFAULT = valor

    def __repr__(self):
        if self.value is not None:
            return f"Constraint({self.constraint_type}, value={self.value})"
        return f"Constraint({self.constraint_type})"

#operaciones de base de datos DML
class MethodCall(Node):
    def __init__(self, method, arguments=None):
        self.method = method
        self.arguments = arguments or []

    def __repr__(self):
        return f"MethodCall(method={self.method}, arguments={self.arguments})"

class DbOperation(Node):
    def __init__(self, model_name, calls):
        self.model_name = model_name
        self.calls = calls  # lista de objetos MethodCall
        self.method = calls[0].method if calls else None
        self.arguments = calls[0].arguments if calls else []

    def __repr__(self):
        return f"DbOperation(model={self.model_name}, calls={self.calls})"

class Parameter(Node):
    def __init__(self, name, value):
        self.name = name
        self.value = value # puede ser una Expression

    def __repr__(self):
        return f"Parameter(name={self.name}, value={self.value})"

#expresiones y vlores
class Expression(Node):
    pass

class Literal(Expression):
    def __init__(self, value, literal_type):
        self.value = value
        self.literal_type = literal_type # valor directo

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
