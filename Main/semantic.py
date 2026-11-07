from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from visitor import Visitor
from ast_nodes import (
    Program, ModelDeclaration, Field, DataType, Constraint,
    DbOperation, Parameter, Literal, Identifier,
    BinaryOperation, UnaryOperation
)


# =====================================================================
# 1. ESTRUCTURAS DE LA TABLA DE SÍMBOLOS (ESQUEMA RELACIONAL EN MEMORIA)
# =====================================================================

@dataclass
class FieldSymbol:
    """Representa una columna registrada dentro de un Modelo (Tabla)."""
    name: str
    data_type: str                 # 'STRING', 'TEXT', 'NUM', 'AUTO', 'DECIMAL', 'BOOL', 'DATE'
    type_args: List[int] = field(default_factory=list)  # ej. [10, 2] para DECIMAL(10,2)
    constraints: Set[str] = field(default_factory=set)  # {'REQUIRED', 'UNIQUE', 'MAIN KEY', 'EXTERNAL KEY', 'DEFAULT'}
    default_value: Optional[object] = None
    lineno: int = 0

    @property
    def is_required(self) -> bool:
        """Un campo es obligatorio en inserciones si tiene REQUIRED y no es AUTO ni tiene DEFAULT."""
        return ('REQUIRED' in self.constraints) and (self.data_type != 'AUTO') and ('DEFAULT' not in self.constraints)


@dataclass
class ModelSymbol:
    """Representa un Modelo (Tabla SQL) en la Tabla de Símbolos."""
    name: str
    fields: Dict[str, FieldSymbol] = field(default_factory=dict)
    lineno: int = 0

    def add_field(self, field_sym: FieldSymbol) -> bool:
        key = field_sym.name.lower()
        if key in self.fields:
            return False
        self.fields[key] = field_sym
        return True

    def get_field(self, name: str) -> Optional[FieldSymbol]:
        return self.fields.get(name.lower())


class SymbolTable:
    """Tabla de Símbolos global del compilador."""
    def __init__(self):
        self.models: Dict[str, ModelSymbol] = {}

    def clear(self):
        self.models.clear()

    def add_model(self, model: ModelSymbol) -> bool:
        key = model.name.lower()
        if key in self.models:
            return False
        self.models[key] = model
        return True

    def get_model(self, name: str) -> Optional[ModelSymbol]:
        return self.models.get(name.lower())

    def resolve_field_in_scope(self, field_name: str, active_models: List[ModelSymbol]) -> List[FieldSymbol]:
        """Busca un atributo en todos los modelos activos de la consulta (incluyendo modelos unidos por .link())."""
        matches = []
        for model in active_models:
            f_sym = model.get_field(field_name)
            if f_sym is not None:
                matches.append(f_sym)
        return matches

    def print_table(self):
        print("\n" + "=" * 75)
        print("TABLA DE SÍMBOLOS (ESQUEMA RELACIONAL)")
        print("=" * 75)
        if not self.models:
            print("  (Tabla de símbolos vacía)")
        for model in self.models.values():
            print(f"\n[MODELO] {model.name} (definido en línea {model.lineno})")
            print(f"  {'Campo':<18} | {'Tipo':<16} | {'Restricciones':<30}")
            print("  " + "-" * 68)
            for f in model.fields.values():
                t_str = f"{f.data_type}({','.join(map(str, f.type_args))})" if f.type_args else f.data_type
                c_str = ", ".join(sorted(f.constraints)) if f.constraints else "Ninguna"
                print(f"  {f.name:<18} | {t_str:<16} | {c_str:<30}")
        print("=" * 75)


# =====================================================================
# 2. SISTEMA DE TIPOS Y REGLAS DE COMPATIBILIDAD
# =====================================================================

NUMERIC_TYPES = {'NUM', 'AUTO', 'DECIMAL'}
TEXT_TYPES = {'STRING', 'TEXT', 'DATE'}


def map_literal_to_semantic_type(literal_token_type: str) -> str:
    """Convierte el tipo de token léxico al tipo semántico interno."""
    mapping = {
        'NUMBER_INT': 'NUM',
        'NUMBER_DECIMAL': 'DECIMAL',
        'STRING_LITERAL': 'STRING',
        'DATE_LITERAL': 'DATE',
        'TRUE': 'BOOL',
        'FALSE': 'BOOL',
        'BOOLEANO': 'BOOL',
        'EMPTY': 'NULL',
    }
    return mapping.get(literal_token_type.upper(), 'ERROR')


def are_types_compatible_for_assignment(target_type: str, value_type: str) -> bool:
    """Verifica si un valor de tipo `value_type` puede asignarse a un campo de tipo `target_type`."""
    if target_type == 'ERROR' or value_type == 'ERROR':
        return True  # Evita cascada de errores si ya se reportó un error previo
    if value_type == 'NULL':
        return True  # El control de nulabilidad se hace verificando la restricción REQUIRED
    if target_type == value_type:
        return True
    # Compatibilidad numérica: un entero (NUM) puede asignarse a DECIMAL, pero un DECIMAL no a NUM
    if target_type == 'DECIMAL' and value_type in NUMERIC_TYPES:
        return True
    if target_type == 'NUM' and value_type in {'NUM', 'AUTO'}:
        return True
    # Compatibilidad de texto/fechas: STRING, TEXT y DATE son compatibles entre sí
    if target_type in {'STRING', 'TEXT'} and value_type in TEXT_TYPES:
        return True
    return False


def are_types_comparable(left_type: str, right_type: str, operator: str) -> bool:
    """Verifica si dos tipos pueden compararse con =, !=, <, >, <=, >=."""
    if 'ERROR' in (left_type, right_type):
        return True
    if 'NULL' in (left_type, right_type):
        return operator in ('=', '!=')
    if left_type in NUMERIC_TYPES and right_type in NUMERIC_TYPES:
        return True
    if left_type in TEXT_TYPES and right_type in TEXT_TYPES:
        return True
    if left_type == 'BOOL' and right_type == 'BOOL':
        return operator in ('=', '!=')
    return False


# =====================================================================
# 3. ANALIZADOR SEMÁNTICO (PATRÓN VISITOR)
# =====================================================================

class SemanticAnalyzer(Visitor):
    def __init__(self):
        self.symbol_table = SymbolTable()
        self.errors: List[str] = []
        self.active_models: List[ModelSymbol] = []

    def report_error(self, message: str, lineno: int = 0):
        loc = f" (Línea {lineno})" if lineno > 0 else ""
        full_msg = f"[!] Error Semántico{loc}: {message}"
        self.errors.append(full_msg)
        print(full_msg)

    def analyze(self, ast_root: Program):
        self.symbol_table.clear()
        self.errors.clear()
        if ast_root is not None:
            self.visit(ast_root)
        return self.errors, self.symbol_table

    # --- Visita del Programa ---
    def visit_Program(self, node: Program):
        for stmt in node.statements:
            self.visit(stmt)

    # --- 3.1 Validación de Declaración de Modelos (DDL) ---
    def visit_ModelDeclaration(self, node: ModelDeclaration):
        lineno = getattr(node, 'lineno', 0)
        model_sym = ModelSymbol(name=node.name, lineno=lineno)

        if not self.symbol_table.add_model(model_sym):
            existing = self.symbol_table.get_model(node.name)
            self.report_error(
                f"El modelo '{node.name}' ya fue declarado previamente en la línea {existing.lineno}.",
                lineno
            )
            return

        main_key_count = 0
        for field_node in node.fields:
            field_sym = self.visit_Field(field_node, model_sym)
            if field_sym:
                if 'MAIN KEY' in field_sym.constraints:
                    main_key_count += 1
                    if main_key_count > 1:
                        self.report_error(
                            f"El modelo '{node.name}' define múltiples 'main key' (campo '{field_sym.name}'). "
                            f"Solo se permite una llave primaria por modelo.",
                            field_sym.lineno
                        )
                if not model_sym.add_field(field_sym):
                    self.report_error(
                        f"El campo '{field_sym.name}' está duplicado dentro del modelo '{node.name}'.",
                        field_sym.lineno
                    )

    def visit_Field(self, node: Field, model_sym: ModelSymbol) -> FieldSymbol:
        lineno = getattr(node, 'lineno', 0)
        dtype_name = node.data_type.type_name.upper()
        dtype_args = node.data_type.args or []

        # Validar precisión y escala en DECIMAL(p, s)
        if dtype_name == 'DECIMAL' and len(dtype_args) == 2:
            precision, scale = dtype_args[0], dtype_args[1]
            if precision <= 0 or scale < 0 or scale > precision:
                self.report_error(
                    f"Parámetros inválidos en Decimal({precision},{scale}) para el campo '{node.name}': "
                    f"la precisión debe ser > 0 y la escala debe cumplir 0 <= escala <= precisión.",
                    lineno
                )

        constraints_set = set()
        default_val = None

        for c in node.constraints:
            c_type = c.constraint_type.upper()
            if c_type in constraints_set:
                self.report_error(
                    f"Restricción '{c_type}' duplicada en el campo '{node.name}' del modelo '{model_sym.name}'.",
                    lineno
                )
            constraints_set.add(c_type)

            # Validar compatibilidad de tipo en DEFAULT = valor
            if c_type == 'DEFAULT' and c.value is not None:
                default_val = c.value
                val_type = self.visit(c.value)
                if dtype_name == 'AUTO':
                    self.report_error(
                        f"El campo '{node.name}' es de tipo 'auto' (autoincremental) y no puede tener un valor 'default'.",
                        lineno
                    )
                elif val_type == 'NULL' and 'REQUIRED' in constraints_set:
                    self.report_error(
                        f"El campo '{node.name}' es 'required' pero su valor por defecto es 'empty' (nulo).",
                        lineno
                    )
                elif not are_types_compatible_for_assignment(dtype_name, val_type):
                    self.report_error(
                        f"Tipo incompatible en 'default' del campo '{node.name}': "
                        f"el campo es '{dtype_name}' pero el valor por defecto es de tipo '{val_type}'.",
                        lineno
                    )

        return FieldSymbol(
            name=node.name,
            data_type=dtype_name,
            type_args=dtype_args,
            constraints=constraints_set,
            default_value=default_val,
            lineno=lineno
        )

    # --- 3.2 Validación de Operaciones y Cadenas de Métodos (DML) ---
    def visit_DbOperation(self, node: DbOperation):
        lineno = getattr(node, 'lineno', 0)
        base_model = self.symbol_table.get_model(node.model_name)
        if base_model is None:
            self.report_error(
                f"El modelo '{node.model_name}' no ha sido declarado.",
                lineno
            )
            return

        # Contexto de modelos activos en esta operación (inicia con el modelo base)
        self.active_models = [base_model]

        # Soportar tanto la estructura nueva (node.calls) como la anterior (node.method / node.arguments)
        calls = getattr(node, 'calls', None)
        if calls is None:
            from ast_nodes import Node
            class _TempCall(Node):
                def __init__(self, m, a):
                    self.method = m
                    self.arguments = a
            calls = [_TempCall(node.method, node.arguments)]

        # Pre-procesar .link(OtroModelo) en la cadena para incorporar sus campos al ámbito activo
        for call in calls:
            if call.method.lower() == 'link':
                self._validate_link_call(call, lineno)

        # Validar coherencia de la cadena de métodos y cada eslabón
        self._validate_method_chain_coherence(calls, base_model, lineno)

        for call in calls:
            if call.method.lower() != 'link':  # link ya fue validado
                self._validate_single_call(call, base_model, lineno)

        self.active_models = []

    def _validate_link_call(self, call, lineno: int):
        if len(call.arguments) != 1 or not isinstance(call.arguments[0], Identifier):
            self.report_error(
                "El método '.link()' requiere exactamente el nombre de un modelo como argumento (ej. .link(Curso)).",
                lineno
            )
            return
        target_name = call.arguments[0].name
        target_model = self.symbol_table.get_model(target_name)
        if target_model is None:
            self.report_error(
                f"El modelo '{target_name}' referenciado en '.link({target_name})' no existe.",
                lineno
            )
        elif target_model not in self.active_models:
            self.active_models.append(target_model)

    def _validate_method_chain_coherence(self, calls: list, base_model: ModelSymbol, lineno: int):
        methods = [c.method.lower() for c in calls]
        # new/add no deben encadenarse con cláusulas de consulta
        if ('new' in methods or 'add' in methods) and len(methods) > 1:
            self.report_error(
                f"El método de inserción '.{methods[0]}()' no puede encadenarse con otros métodos ({methods}).",
                lineno
            )
        # ifgroup (HAVING) requiere group (GROUP BY) en la cadena
        if 'ifgroup' in methods and 'group' not in methods:
            self.report_error(
                "El método '.ifgroup()' (HAVING) solo puede utilizarse cuando existe '.group()' (GROUP BY) en la cadena.",
                lineno
            )

    def _validate_single_call(self, call, base_model: ModelSymbol, lineno: int):
        method = call.method.lower()
        args = call.arguments or []

        # 1. Inserción: .new(...) o .add(...)
        if method in ('new', 'add'):
            if not args:
                self.report_error(
                    f"El método '.{method}()' sobre '{base_model.name}' requiere al menos un parámetro de asignación.",
                    lineno
                )
                return
            provided_fields = set()
            for arg in args:
                if not isinstance(arg, Parameter):
                    self.report_error(
                        f"En '.{method}()', todos los argumentos deben ser asignaciones 'campo = valor'.",
                        lineno
                    )
                    continue
                self._validate_parameter_assignment(arg, base_model, is_insert=True, lineno=lineno)
                provided_fields.add(arg.name.lower())

            # Verificar campos obligatorios (REQUIRED sin DEFAULT y que no sean AUTO)
            for f_sym in base_model.fields.values():
                if f_sym.is_required and f_sym.name.lower() not in provided_fields:
                    self.report_error(
                        f"Falta el campo obligatorio '{f_sym.name}' (required) al insertar en el modelo '{base_model.name}'.",
                        lineno
                    )

        # 2. Actualización: .modify(...)
        elif method == 'modify':
            if not args:
                self.report_error(
                    f"El método '.modify()' sobre '{base_model.name}' requiere al menos un campo a modificar.",
                    lineno
                )
                return
            for arg in args:
                if not isinstance(arg, Parameter):
                    self.report_error(
                        "En '.modify()', todos los argumentos deben ser asignaciones 'campo = nuevo_valor'.",
                        lineno
                    )
                    continue
                self._validate_parameter_assignment(arg, base_model, is_insert=False, lineno=lineno)

        # 3. Consulta / Proyección: .find(...)
        elif method == 'find':
            for arg in args:
                if isinstance(arg, Identifier):
                    self._resolve_field_or_error(arg.name, lineno)
                elif isinstance(arg, Parameter):
                    # Soporta sintaxis corta Estudiante.find(edad = 67)
                    self._validate_parameter_filter(arg, lineno)
                else:
                    cond_type = self.visit(arg)
                    if cond_type not in ('BOOL', 'ERROR'):
                        self.report_error(
                            f"Argumento inválido en '.find()': se esperaba un nombre de campo o una condición booleana, pero se obtuvo '{cond_type}'.",
                            lineno
                        )

        # 4. Filtros condicionales: .if(...) / .ifgroup(...) / .remove(...)
        elif method in ('if', 'ifgroup', 'remove'):
            if method in ('if', 'ifgroup') and not args:
                self.report_error(f"El método '.{method}()' requiere una condición lógica o relacional.", lineno)
                return
            for arg in args:
                if isinstance(arg, Parameter):
                    self._validate_parameter_filter(arg, lineno)
                else:
                    cond_type = self.visit(arg)
                    if cond_type not in ('BOOL', 'ERROR'):
                        self.report_error(
                            f"La condición dentro de '.{method}()' debe evaluarse a un valor booleano (BOOL), pero se obtuvo '{cond_type}'.",
                            lineno
                        )

        # 5. Ordenamiento y Agrupación: .up(...), .down(...), .group(...)
        elif method in ('up', 'down', 'group'):
            if not args:
                self.report_error(f"El método '.{method}()' requiere al menos un nombre de campo.", lineno)
                return
            for arg in args:
                if not isinstance(arg, Identifier):
                    self.report_error(
                        f"El método '.{method}()' solo acepta nombres de campos (identificadores) como argumentos.",
                        lineno
                    )
                else:
                    self._resolve_field_or_error(arg.name, lineno)

        # 6. Paginación: .take(N) y .skip(N)
        elif method in ('take', 'skip'):
            if len(args) != 1:
                self.report_error(f"El método '.{method}()' requiere exactamente 1 argumento entero.", lineno)
                return
            arg_type = self.visit(args[0])
            if arg_type not in ('NUM', 'ERROR'):
                self.report_error(
                    f"El método '.{method}()' requiere un número entero (NUM), pero recibió '{arg_type}'.",
                    lineno
                )
            if isinstance(args[0], UnaryOperation) and args[0].operator == '-':
                self.report_error(
                    f"El método '.{method}()' no acepta cantidades negativas.",
                    lineno
                )

        # 7. Funciones de agregación: .count(), .sum(campo), .avg(campo), .max(campo), .min(campo)
        elif method == 'count':
            if len(args) > 1:
                self.report_error("El método '.count()' acepta como máximo 1 campo opcional.", lineno)
            elif len(args) == 1:
                if not isinstance(args[0], Identifier):
                    self.report_error("El argumento de '.count()' debe ser el nombre de un campo.", lineno)
                else:
                    self._resolve_field_or_error(args[0].name, lineno)

        elif method in ('sum', 'avg', 'max', 'min'):
            if len(args) != 1 or not isinstance(args[0], Identifier):
                self.report_error(
                    f"La función de agregación '.{method}()' requiere exactamente el nombre de un campo como argumento.",
                    lineno
                )
                return
            f_sym = self._resolve_field_or_error(args[0].name, lineno)
            if f_sym and method in ('sum', 'avg') and f_sym.data_type not in NUMERIC_TYPES:
                self.report_error(
                    f"La función '.{method}()' requiere un campo numérico, pero '{f_sym.name}' es de tipo '{f_sym.data_type}'.",
                    lineno
                )

        else:
            self.report_error(f"El método '.{method}()' no es una operación válida del lenguaje.", lineno)

    # --- Auxiliares de validación de parámetros y campos ---
    def _resolve_field_or_error(self, field_name: str, lineno: int) -> Optional[FieldSymbol]:
        matches = self.symbol_table.resolve_field_in_scope(field_name, self.active_models)
        if not matches:
            model_names = ", ".join(m.name for m in self.active_models)
            self.report_error(
                f"El campo '{field_name}' no existe en el modelo activo ({model_names}).",
                lineno
            )
            return None
        return matches[0]

    def _validate_parameter_assignment(self, param: Parameter, model: ModelSymbol, is_insert: bool, lineno: int):
        f_sym = model.get_field(param.name)
        if f_sym is None:
            self.report_error(
                f"El campo '{param.name}' no existe en el modelo '{model.name}'.",
                lineno
            )
            return

        if f_sym.data_type == 'AUTO':
            accion = "insertar" if is_insert else "modificar"
            self.report_error(
                f"No se puede {accion} manualmente el campo '{f_sym.name}' porque es de tipo 'auto' (autoincremental).",
                lineno
            )
            return

        val_type = self.visit(param.value)
        if val_type == 'NULL':
            if 'REQUIRED' in f_sym.constraints:
                self.report_error(
                    f"El campo '{f_sym.name}' tiene la restricción 'required' y no admite el valor 'empty' (NULL).",
                    lineno
                )
            return

        if not are_types_compatible_for_assignment(f_sym.data_type, val_type):
            self.report_error(
                f"Incompatibilidad de tipos en '{param.name}': el campo es de tipo '{f_sym.data_type}', "
                f"pero se intentó asignar un valor de tipo '{val_type}'.",
                lineno
            )

    def _validate_parameter_filter(self, param: Parameter, lineno: int):
        """Valida un Parameter(campo, valor) cuando se usa como condición de igualdad (ej. .if(nombre = 'Jose'))."""
        f_sym = self._resolve_field_or_error(param.name, lineno)
        val_type = self.visit(param.value)
        if f_sym is not None and not are_types_comparable(f_sym.data_type, val_type, '='):
            self.report_error(
                f"Comparación inválida en '{param.name} = ...': no se puede comparar el campo '{f_sym.name}' ({f_sym.data_type}) con un valor de tipo '{val_type}'.",
                lineno
            )

    # --- 3.3 Inferencia y Verificación de Tipos en Expresiones ---
    def visit_Literal(self, node: Literal) -> str:
        return map_literal_to_semantic_type(node.literal_type)

    def visit_Identifier(self, node: Identifier) -> str:
        lineno = getattr(node, 'lineno', 0)
        f_sym = self._resolve_field_or_error(node.name, lineno)
        if f_sym is None:
            return 'ERROR'
        return f_sym.data_type

    def visit_UnaryOperation(self, node: UnaryOperation) -> str:
        lineno = getattr(node, 'lineno', 0)
        op = node.operator.upper()
        operand_type = self.visit(node.operand)

        if operand_type == 'ERROR':
            return 'ERROR'

        if op in ('+', '-'):
            if operand_type not in NUMERIC_TYPES:
                self.report_error(
                    f"El operador unario '{op}' solo puede aplicarse a expresiones numéricas, pero se aplicó a '{operand_type}'.",
                    lineno
                )
                return 'ERROR'
            return 'DECIMAL' if operand_type == 'DECIMAL' else 'NUM'

        if op == 'NOT':
            if operand_type != 'BOOL':
                self.report_error(
                    f"El operador lógico 'NOT' requiere una expresión booleana (BOOL), pero recibió '{operand_type}'.",
                    lineno
                )
                return 'ERROR'
            return 'BOOL'

        return 'ERROR'

    def visit_BinaryOperation(self, node: BinaryOperation) -> str:
        lineno = getattr(node, 'lineno', 0)
        op = node.operator.upper()
        left_type = self.visit(node.left)
        right_type = self.visit(node.right)

        if 'ERROR' in (left_type, right_type):
            return 'ERROR'

        # 1. Operadores Aritméticos: +, -, *, /, %
        if op in ('+', '-', '*', '/', '%'):
            if left_type not in NUMERIC_TYPES or right_type not in NUMERIC_TYPES:
                self.report_error(
                    f"Operación aritmética inválida ('{op}'): no se pueden operar tipos '{left_type}' y '{right_type}'. "
                    f"Ambos operandos deben ser numéricos (ej. no se permite mezclar booleanos o cadenas con aritmética).",
                    lineno
                )
                return 'ERROR'
            # Verificar división o módulo por cero literal
            if op in ('/', '%') and isinstance(node.right, Literal) and node.right.value == 0:
                self.report_error(f"División o módulo por cero detectado en la operación '{op}'.", lineno)
                return 'ERROR'
            if left_type == 'DECIMAL' or right_type == 'DECIMAL' or op == '/':
                return 'DECIMAL'
            return 'NUM'

        # 2. Operadores Relacionales: =, !=, <, >, <=, >=
        if op in ('=', '!=', '<', '>', '<=', '>='):
            if not are_types_comparable(left_type, right_type, op):
                self.report_error(
                    f"Comparación relacional inválida ('{op}'): los tipos '{left_type}' y '{right_type}' no son compatibles para comparación.",
                    lineno
                )
                return 'ERROR'
            return 'BOOL'

        # 3. Operadores Lógicos: AND, OR
        if op in ('AND', 'OR'):
            if left_type != 'BOOL' or right_type != 'BOOL':
                self.report_error(
                    f"Operación lógica inválida ('{op}'): ambos operandos deben ser booleanos (BOOL), "
                    f"pero se recibieron '{left_type}' y '{right_type}'.",
                    lineno
                )
                return 'ERROR'
            return 'BOOL'

        return 'ERROR'
