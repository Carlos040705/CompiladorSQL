class Node:
    # clase base para los nodos del arbol
    lineno: int = 0

    def accept(self, visitor):
        pass


class Program(Node):
    def __init__(self, statements, lineno=0):
        self.statements = statements
        self.lineno = lineno

    def __repr__(self):
        return f"Program(statements={self.statements})"


# clases para los modelos de tablas
class ModelDeclaration(Node):
    def __init__(self, name, fields, lineno=0):
        self.name = name
        self.fields = fields
        self.lineno = lineno

    def __repr__(self):
        return f"ModelDeclaration(name={self.name}, fields={self.fields})"


class Field(Node):
    def __init__(self, name, data_type, constraints=None, lineno=0):
        self.name = name
        self.data_type = data_type
        self.constraints = constraints or []
        self.lineno = lineno

    def __repr__(self):
        return f"Field(name={self.name}, type={self.data_type}, constraints={self.constraints})"


class DataType(Node):
    def __init__(self, type_name, args=None, lineno=0):
        self.type_name = type_name
        self.args = args or []
        self.lineno = lineno

    def __repr__(self):
        if self.args:
            return f"DataType({self.type_name}, args={self.args})"
        return f"DataType({self.type_name})"


class Constraint(Node):
    def __init__(self, constraint_type, value=None, lineno=0):
        self.constraint_type = constraint_type
        self.value = value
        self.lineno = lineno

    def __repr__(self):
        if self.value is not None:
            return f"Constraint({self.constraint_type}, value={self.value})"
        return f"Constraint({self.constraint_type})"


# calses para las operasiones de la db y metodos
class MethodCall(Node):
    def __init__(self, method, arguments=None, lineno=0):
        self.method = method
        self.arguments = arguments or []
        self.lineno = lineno

    def __repr__(self):
        return f"MethodCall(method={self.method}, arguments={self.arguments})"


class DbOperation(Node):
    def __init__(self, model_name, calls, arguments=None, lineno=0):
        self.model_name = model_name
        if isinstance(calls, list):
            self.calls = calls
            self.method = calls[0].method if calls else None
            self.arguments = calls[0].arguments if calls else []
        else:
            self.method = calls
            self.arguments = arguments or []
            self.calls = [MethodCall(calls, self.arguments, lineno=lineno)]
        self.lineno = lineno

    def __repr__(self):
        return f"DbOperation(model={self.model_name}, calls={self.calls})"


class Parameter(Node):
    def __init__(self, name, value, lineno=0):
        self.name = name
        self.value = value
        self.lineno = lineno

    def __repr__(self):
        return f"Parameter(name={self.name}, value={self.value})"


# nodos para las expresiones y valores
class Expression(Node):
    pass


class Literal(Expression):
    def __init__(self, value, literal_type, lineno=0):
        self.value = value
        self.literal_type = literal_type
        self.lineno = lineno

    def __repr__(self):
        return f"Literal({self.value}, type={self.literal_type})"


class Identifier(Expression):
    def __init__(self, name, lineno=0):
        self.name = name
        self.lineno = lineno

    def __repr__(self):
        return f"Identifier({self.name})"


class BinaryOperation(Expression):
    def __init__(self, left, operator, right, lineno=0):
        self.left = left
        self.operator = operator
        self.right = right
        self.lineno = lineno

    def __repr__(self):
        return f"BinaryOperation({self.left} {self.operator} {self.right})"


class UnaryOperation(Expression):
    def __init__(self, operator, operand, lineno=0):
        self.operator = operator
        self.operand = operand
        self.lineno = lineno

    def __repr__(self):
        return f"UnaryOperation({self.operator}{self.operand})"
