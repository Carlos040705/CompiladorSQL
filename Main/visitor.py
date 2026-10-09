class Visitor:
    def visit(self, node, *args, **kwargs):
        if node is None:
            return None
        method_name = 'visit_' + type(node).__name__
        visitor_method = getattr(self, method_name, self.generic_visit)
        return visitor_method(node, *args, **kwargs)

    def generic_visit(self, node, *args, **kwargs):
        raise Exception(f'No visit_{type(node).__name__} method defined in Visitor')

class ASTPrinter(Visitor):
    def __init__(self):
        self.indent_level = 0

    def print_indent(self, text):
        print("  " * self.indent_level + text)

    def visit_Program(self, node):
        self.print_indent("Program:")
        self.indent_level += 1
        for stmt in node.statements:
            self.visit(stmt)
        self.indent_level -= 1

    def visit_ModelDeclaration(self, node):
        self.print_indent(f"ModelDeclaration(name={node.name}):")
        self.indent_level += 1
        for field in node.fields:
            self.visit(field)
        self.indent_level -= 1

    def visit_Field(self, node):
        self.print_indent(f"Field(name={node.name})")
        self.indent_level += 1
        self.visit(node.data_type)
        if node.constraints:
            self.print_indent("Constraints:")
            self.indent_level += 1
            for constraint in node.constraints:
                self.visit(constraint)
            self.indent_level -= 1
        self.indent_level -= 1

    def visit_DataType(self, node):
        args_str = f", args={node.args}" if node.args else ""
        self.print_indent(f"DataType(type={node.type_name}{args_str})")

    def visit_Constraint(self, node):
        val_str = f", value={node.value}" if node.value is not None else ""
        self.print_indent(f"Constraint(type={node.constraint_type}{val_str})")

    def visit_DbOperation(self, node):
        self.print_indent(f"DbOperation(model={node.model_name}, method={node.method}):")
        if node.arguments:
            self.indent_level += 1
            for arg in node.arguments:
                self.visit(arg)
            self.indent_level -= 1

    def visit_Parameter(self, node):
        self.print_indent(f"Parameter(name={node.name}):")
        self.indent_level += 1
        self.visit(node.value)
        self.indent_level -= 1

    def visit_Literal(self, node):
        self.print_indent(f"Literal(value={node.value}, type={node.literal_type})")

    def visit_Identifier(self, node):
        self.print_indent(f"Identifier(name={node.name})")

    def visit_BinaryOperation(self, node):
        self.print_indent(f"BinaryOperation(op={node.operator}):")
        self.indent_level += 1
        self.visit(node.left)
        self.visit(node.right)
        self.indent_level -= 1

    def visit_UnaryOperation(self, node):
        self.print_indent(f"UnaryOperation(op={node.operator}):")
        self.indent_level += 1
        self.visit(node.operand)
        self.indent_level -= 1
