from typing import List, Optional, Set, Tuple
from visitor import Visitor
from ast_nodes import (
    Node, Program, ModelDeclaration, Field, DataType, Constraint,
    DbOperation, MethodCall, Parameter, Literal, Identifier,
    BinaryOperation, UnaryOperation
)
from semantic import SymbolTable, ModelSymbol, FieldSymbol
from db_executor import (
    PostgresExecutor,
    ExecutionReport,
    StatementResult,
    load_db_config,
    save_db_config,
    format_ascii_table,
    filter_sql_statements,
)


class SQLStatementList(list):
    # lista de sentencias sql q tambien funciona como string para las pruebas

    @property
    def script(self) -> str:
        return "\n\n".join(self)

    def __str__(self) -> str:
        return self.script

    def __contains__(self, item: object) -> bool:
        if super().__contains__(item):
            return True
        if isinstance(item, str):
            return item in self.script
        return False

    def lower(self) -> str:
        return self.script.lower()

    def upper(self) -> str:
        return self.script.upper()

    def strip(self, *args, **kwargs) -> str:
        return self.script.strip(*args, **kwargs)

    def splitlines(self, *args, **kwargs) -> List[str]:
        return self.script.splitlines(*args, **kwargs)


class SQLCodeGenerator(Visitor):
    # pasa el ast validado a codigo sql para postgres

    TYPE_MAPPING = {
        "AUTO": "SERIAL",
        "STRING": "VARCHAR(255)",
        "TEXT": "TEXT",
        "NUM": "INTEGER",
        "BOOL": "BOOLEAN",
        "DATE": "DATE",
    }

    PRECEDENCE = {
        "OR": 1,
        "AND": 2,
        "NOT": 3,
        "=": 4,
        "!=": 4,
        "<": 4,
        ">": 4,
        "<=": 4,
        ">=": 4,
        "+": 5,
        "-": 5,
        "*": 6,
        "/": 6,
        "%": 6,
        "UNARY_+": 7,
        "UNARY_-": 7,
        "ATOM": 8,
    }

    def __init__(self, symbol_table: Optional[SymbolTable] = None):
        self.symbol_table: SymbolTable = symbol_table or SymbolTable()
        self.statements: SQLStatementList = SQLStatementList()
        self.active_models: List[ModelSymbol] = []
        self._declared_models_so_far: List[ModelSymbol] = []
        self._allowed_model_declarations: Optional[Set[str]] = None

    def generate(
        self,
        ast_root: Optional[Program],
        symbol_table: Optional[SymbolTable] = None,
        omit_ddl: bool = False,
        omit_alter: bool = True,
        allowed_model_declarations: Optional[Set[str]] = None,
    ) -> SQLStatementList:
        # recorre el arbol y devulve la lista de sentencias sql generadas
        if symbol_table is not None:
            self.symbol_table = symbol_table
        self.statements = SQLStatementList()
        self.active_models = []
        self._allowed_model_declarations = (
            {m.lower() for m in allowed_model_declarations}
            if allowed_model_declarations is not None
            else None
        )

        ast_model_names = {
            stmt.name.lower()
            for stmt in (getattr(ast_root, "statements", None) or [])
            if isinstance(stmt, ModelDeclaration)
            and (
                self._allowed_model_declarations is None
                or stmt.name.lower() in self._allowed_model_declarations
            )
        }
        self._declared_models_so_far = [
            model_sym
            for key, model_sym in self.symbol_table.models.items()
            if key not in ast_model_names
        ]

        if ast_root is not None:
            self.visit(ast_root)

        if omit_ddl:
            filtered, _ = filter_sql_statements(
                self.statements,
                omit_ddl=omit_ddl,
                omit_alter=omit_alter,
            )
            self.statements = SQLStatementList(filtered)

        return self.statements

    def generate_script(
        self,
        ast_root: Optional[Program],
        symbol_table: Optional[SymbolTable] = None,
        omit_ddl: bool = False,
        omit_alter: bool = True,
        allowed_model_declarations: Optional[Set[str]] = None,
    ) -> str:
        # une todas las consultas en un solo texto sql
        return self.generate(
            ast_root,
            symbol_table,
            omit_ddl=omit_ddl,
            omit_alter=omit_alter,
            allowed_model_declarations=allowed_model_declarations,
        ).script

    # recorrido del programa y creacion de tablas ddl

    def visit_Program(self, node: Program) -> SQLStatementList:
        for stmt in node.statements:
            sql_stmt = self.visit(stmt)
            if sql_stmt:
                self.statements.append(sql_stmt)
        return self.statements

    def visit_ModelDeclaration(self, node: ModelDeclaration) -> str:
        model_sym = self.symbol_table.get_model(node.name)
        if (
            self._allowed_model_declarations is not None
            and node.name.lower() not in self._allowed_model_declarations
        ):
            if model_sym is not None and model_sym not in self._declared_models_so_far:
                self._declared_models_so_far.append(model_sym)
            return ""

        table_name = self._normalize_identifier(node.name)

        column_defs: List[str] = []
        for field_node in node.fields:
            col_def = self._translate_field_definition(field_node, model_sym)
            column_defs.append(f"    {col_def}")

        if model_sym is not None and model_sym not in self._declared_models_so_far:
            self._declared_models_so_far.append(model_sym)

        cols_joined = ",\n".join(column_defs)
        return f"CREATE TABLE IF NOT EXISTS {table_name} (\n{cols_joined}\n);"

    def _translate_field_definition(
        self,
        field_node: Field,
        current_model: Optional[ModelSymbol],
    ) -> str:
        col_name = self._normalize_identifier(field_node.name)
        sql_type = self._translate_data_type(field_node.data_type)
        parts = [col_name, sql_type]

        is_serial = field_node.data_type.type_name.upper() == "AUTO"
        has_main_key = any(
            c.constraint_type.upper() == "MAIN KEY" for c in field_node.constraints
        )
        has_required = any(
            c.constraint_type.upper() == "REQUIRED" for c in field_node.constraints
        )
        has_unique = any(
            c.constraint_type.upper() == "UNIQUE" for c in field_node.constraints
        )
        has_external_key = any(
            c.constraint_type.upper() == "EXTERNAL KEY" for c in field_node.constraints
        )
        default_constraint = next(
            (
                c
                for c in field_node.constraints
                if c.constraint_type.upper() == "DEFAULT" and c.value is not None
            ),
            None,
        )

        if has_main_key:
            parts.append("PRIMARY KEY")

        if has_required and not (is_serial and has_main_key):
            parts.append("NOT NULL")

        if has_unique:
            parts.append("UNIQUE")

        if default_constraint is not None:
            default_sql = self._translate_expression(
                default_constraint.value,
                in_filter=False,
            )
            parts.append(f"DEFAULT {default_sql}")

        if has_external_key:
            ref_target = self._resolve_foreign_key_target(
                field_node.name,
                field_node.data_type.type_name.upper(),
                current_model,
            )
            if ref_target is not None:
                ref_table, ref_pk = ref_target
                parts.append(f"REFERENCES {ref_table}({ref_pk})")

        return " ".join(parts)

    def _translate_data_type(self, dtype: DataType) -> str:
        t_name = dtype.type_name.upper()
        if t_name == "DECIMAL":
            if dtype.args and len(dtype.args) == 2:
                return f"NUMERIC({dtype.args[0]}, {dtype.args[1]})"
            return "NUMERIC"
        return self.TYPE_MAPPING.get(t_name, t_name)

    @staticmethod
    def _find_model_pk(model: ModelSymbol) -> Optional[FieldSymbol]:
        for f_sym in model.fields.values():
            if "MAIN KEY" in f_sym.constraints:
                return f_sym
        for f_sym in model.fields.values():
            if f_sym.data_type == "AUTO":
                return f_sym
        return None

    @staticmethod
    def _are_fk_types_compatible(fk_type: str, pk_type: str) -> bool:
        int_group = {"NUM", "AUTO"}
        if fk_type in int_group and pk_type in int_group:
            return True
        return fk_type == pk_type

    def _resolve_foreign_key_target(
        self,
        field_name: str,
        field_type: str,
        current_model: Optional[ModelSymbol],
    ) -> Optional[Tuple[str, str]]:
        # busca a que tabla y llave apunta una external key
        lower_field = field_name.lower()
        current_name = current_model.name.lower() if current_model else ""

        # primero revisamos si el nombre tiene id_modelo o modelo_id
        candidate_names: List[str] = []
        if lower_field.startswith("id_") and len(lower_field) > 3:
            candidate_names.append(lower_field[3:])
        if lower_field.endswith("_id") and len(lower_field) > 3:
            candidate_names.append(lower_field[:-3])

        for cand in candidate_names:
            target_model = self.symbol_table.get_model(cand)
            if target_model is not None and target_model.name.lower() != current_name:
                pk_field = self._find_model_pk(target_model)
                if pk_field is not None:
                    return (
                        self._normalize_identifier(target_model.name),
                        self._normalize_identifier(pk_field.name),
                    )

        # si no vemos si el nombre de alguna tabla viene en el campo
        for model_key, model_sym in self.symbol_table.models.items():
            if model_key == current_name:
                continue
            if model_key in lower_field:
                pk_field = self._find_model_pk(model_sym)
                if pk_field is not None and self._are_fk_types_compatible(field_type, pk_field.data_type):
                    return (
                        self._normalize_identifier(model_sym.name),
                        self._normalize_identifier(pk_field.name),
                    )

        # como ultima opcion buscamos un modelo anterior con llave del mismo tipo
        prior_candidates = self._declared_models_so_far or [
            m for k, m in self.symbol_table.models.items() if k != current_name
        ]
        compatible_models: List[Tuple[ModelSymbol, FieldSymbol]] = []
        for model_sym in prior_candidates:
            if model_sym.name.lower() == current_name:
                continue
            pk_field = self._find_model_pk(model_sym)
            if pk_field is not None and self._are_fk_types_compatible(field_type, pk_field.data_type):
                compatible_models.append((model_sym, pk_field))

        if len(compatible_models) == 1:
            target_model, pk_field = compatible_models[0]
            return (
                self._normalize_identifier(target_model.name),
                self._normalize_identifier(pk_field.name),
            )

        return None

    # traduccion de operasiones dml y cadenas de metodos

    def visit_DbOperation(self, node: DbOperation) -> str:
        base_model = self.symbol_table.get_model(node.model_name)
        self.active_models = [base_model] if base_model is not None else []

        calls: List[MethodCall] = getattr(node, "calls", None) or [
            MethodCall(node.method, node.arguments, lineno=node.lineno)
        ]

        # cargar antes los modelos del link para revisar campos
        for call in calls:
            if call.method.lower() == "link" and call.arguments:
                arg = call.arguments[0]
                if isinstance(arg, Identifier):
                    linked_model = self.symbol_table.get_model(arg.name)
                    if linked_model is not None and linked_model not in self.active_models:
                        self.active_models.append(linked_model)

        methods = [c.method.lower() for c in calls]

        try:
            if "new" in methods or "add" in methods:
                return self._translate_insert(node.model_name, calls)
            if "modify" in methods:
                return self._translate_update(node.model_name, calls)
            if "remove" in methods:
                return self._translate_delete(node.model_name, calls)
            return self._translate_select(node.model_name, calls)
        finally:
            self.active_models = []

    def _translate_insert(self, model_name: str, calls: List[MethodCall]) -> str:
        table_name = self._normalize_identifier(model_name)
        insert_call = next(c for c in calls if c.method.lower() in ("new", "add"))

        columns: List[str] = []
        values: List[str] = []
        for arg in insert_call.arguments:
            if isinstance(arg, Parameter):
                columns.append(self._normalize_identifier(arg.name))
                values.append(self._translate_expression(arg.value, in_filter=False))

        cols_sql = ", ".join(columns)
        vals_sql = ", ".join(values)
        return f"INSERT INTO {table_name} ({cols_sql}) VALUES ({vals_sql});"

    def _translate_update(self, model_name: str, calls: List[MethodCall]) -> str:
        table_name = self._normalize_identifier(model_name)
        modify_call = next(c for c in calls if c.method.lower() == "modify")

        set_clauses: List[str] = []
        for arg in modify_call.arguments:
            if isinstance(arg, Parameter):
                col = self._normalize_identifier(arg.name)
                val = self._translate_expression(arg.value, in_filter=False)
                set_clauses.append(f"{col} = {val}")

        where_conditions: List[Node] = []
        for call in calls:
            m = call.method.lower()
            if m == "if":
                where_conditions.extend(call.arguments)
            elif m == "find":
                for arg in call.arguments:
                    if not isinstance(arg, Identifier):
                        where_conditions.append(arg)

        set_sql = ", ".join(set_clauses)
        if where_conditions:
            where_sql = self._join_filter_conditions(where_conditions)
            return f"UPDATE {table_name} SET {set_sql} WHERE {where_sql};"
        return f"UPDATE {table_name} SET {set_sql};"

    def _translate_delete(self, model_name: str, calls: List[MethodCall]) -> str:
        table_name = self._normalize_identifier(model_name)
        where_conditions: List[Node] = []

        for call in calls:
            m = call.method.lower()
            if m in ("if", "remove"):
                where_conditions.extend(call.arguments)
            elif m == "find":
                for arg in call.arguments:
                    if not isinstance(arg, Identifier):
                        where_conditions.append(arg)

        if where_conditions:
            where_sql = self._join_filter_conditions(where_conditions)
            return f"DELETE FROM {table_name} WHERE {where_sql};"
        return f"DELETE FROM {table_name};"

    def _translate_select(self, model_name: str, calls: List[MethodCall]) -> str:
        table_name = self._normalize_identifier(model_name)
        base_model = self.symbol_table.get_model(model_name)

        projection_cols: List[str] = []
        aggregate_exprs: List[str] = []
        join_clauses: List[str] = []
        where_nodes: List[Node] = []
        explicit_group_cols: List[str] = []
        having_nodes: List[Node] = []
        order_by_items: List[str] = []
        order_by_cols: List[str] = []
        limit_val: Optional[str] = None
        offset_val: Optional[str] = None

        joined_models: List[ModelSymbol] = [base_model] if base_model is not None else []

        for call in calls:
            m = call.method.lower()
            args = call.arguments or []

            if m == "find":
                for arg in args:
                    if isinstance(arg, Identifier):
                        col_sql = self._qualify_column(arg.name)
                        projection_cols.append(col_sql)
                    else:
                        where_nodes.append(arg)

            elif m == "count":
                if not args:
                    aggregate_exprs.append("COUNT(*)")
                elif isinstance(args[0], Identifier):
                    col_sql = self._qualify_column(args[0].name)
                    aggregate_exprs.append(f"COUNT({col_sql})")

            elif m in ("sum", "avg", "max", "min"):
                if args and isinstance(args[0], Identifier):
                    col_sql = self._qualify_column(args[0].name)
                    aggregate_exprs.append(f"{m.upper()}({col_sql})")

            elif m == "link":
                if args and isinstance(args[0], Identifier):
                    target_name = args[0].name
                    target_model = self.symbol_table.get_model(target_name)
                    join_sql = self._build_join_clause(target_name, target_model, joined_models)
                    join_clauses.append(join_sql)
                    if target_model is not None and target_model not in joined_models:
                        joined_models.append(target_model)

            elif m == "if":
                where_nodes.extend(args)

            elif m == "group":
                for arg in args:
                    if isinstance(arg, Identifier):
                        col_sql = self._qualify_column(arg.name)
                        if col_sql not in explicit_group_cols:
                            explicit_group_cols.append(col_sql)

            elif m == "ifgroup":
                having_nodes.extend(args)

            elif m == "up":
                for arg in args:
                    if isinstance(arg, Identifier):
                        col_sql = self._qualify_column(arg.name)
                        order_by_items.append(f"{col_sql} ASC")
                        order_by_cols.append(col_sql)

            elif m == "down":
                for arg in args:
                    if isinstance(arg, Identifier):
                        col_sql = self._qualify_column(arg.name)
                        order_by_items.append(f"{col_sql} DESC")
                        order_by_cols.append(col_sql)

            elif m == "take":
                if args:
                    limit_val = self._translate_pagination_arg(args[0])

            elif m == "skip":
                if args:
                    offset_val = self._translate_pagination_arg(args[0])

        # armar la parte del select
        select_items = projection_cols + aggregate_exprs
        select_sql = ", ".join(select_items) if select_items else "*"

        parts = [f"SELECT {select_sql} FROM {table_name}"]

        if join_clauses:
            parts.extend(join_clauses)

        if where_nodes:
            where_sql = self._join_filter_conditions(where_nodes)
            parts.append(f"WHERE {where_sql}")

        if explicit_group_cols:
            # postgres pide meter en el group by todas las columnas que no son de agregacion
            all_group_cols = list(explicit_group_cols)
            for col in projection_cols:
                if col not in all_group_cols:
                    all_group_cols.append(col)
            for h_node in having_nodes:
                for col in self._extract_qualified_identifiers(h_node):
                    if col not in all_group_cols:
                        all_group_cols.append(col)
            for col in order_by_cols:
                if col not in all_group_cols:
                    all_group_cols.append(col)
            parts.append(f"GROUP BY {', '.join(all_group_cols)}")

        if having_nodes:
            having_sql = self._join_filter_conditions(having_nodes)
            parts.append(f"HAVING {having_sql}")

        if order_by_items:
            parts.append(f"ORDER BY {', '.join(order_by_items)}")

        if limit_val is not None:
            parts.append(f"LIMIT {limit_val}")

        if offset_val is not None:
            parts.append(f"OFFSET {offset_val}")

        return " ".join(parts) + ";"

    def _build_join_clause(
        self,
        target_name: str,
        target_model: Optional[ModelSymbol],
        prior_models: List[ModelSymbol],
    ) -> str:
        target_table = self._normalize_identifier(target_name)
        if target_model is None or not prior_models:
            return f"CROSS JOIN {target_table}"

        # revisar si la tabla nueva tiene llave foranea hacia las anteriores
        for f_sym in target_model.fields.values():
            if "EXTERNAL KEY" in f_sym.constraints:
                ref = self._resolve_fk_between(target_model, f_sym, prior_models)
                if ref is not None:
                    left_model, left_pk = ref
                    left_table = self._normalize_identifier(left_model.name)
                    pk_col = self._normalize_identifier(left_pk.name)
                    fk_col = self._normalize_identifier(f_sym.name)
                    return f"INNER JOIN {target_table} ON {left_table}.{pk_col} = {target_table}.{fk_col}"

        # revisar si alguna tabla anterior apunta a la nueva
        for left_model in prior_models:
            for f_sym in left_model.fields.values():
                if "EXTERNAL KEY" in f_sym.constraints:
                    ref = self._resolve_fk_between(left_model, f_sym, [target_model])
                    if ref is not None:
                        _, target_pk = ref
                        left_table = self._normalize_identifier(left_model.name)
                        fk_col = self._normalize_identifier(f_sym.name)
                        pk_col = self._normalize_identifier(target_pk.name)
                        return f"INNER JOIN {target_table} ON {left_table}.{fk_col} = {target_table}.{pk_col}"

        # si no tienen relacion directa mandamos cross join
        return f"CROSS JOIN {target_table}"

    def _resolve_fk_between(
        self,
        fk_model: ModelSymbol,
        fk_field: FieldSymbol,
        candidate_models: List[ModelSymbol],
    ) -> Optional[Tuple[ModelSymbol, FieldSymbol]]:
        lower_fk = fk_field.name.lower()
        for cand in candidate_models:
            cand_name = cand.name.lower()
            pk_field = self._find_model_pk(cand)
            if pk_field is None:
                continue
            if lower_fk in (f"id_{cand_name}", f"{cand_name}_id") or cand_name in lower_fk:
                if self._are_fk_types_compatible(fk_field.data_type, pk_field.data_type):
                    return cand, pk_field

        if len(candidate_models) == 1:
            cand = candidate_models[0]
            pk_field = self._find_model_pk(cand)
            if pk_field is not None and self._are_fk_types_compatible(fk_field.data_type, pk_field.data_type):
                return cand, pk_field

        return None

    # manejo de expresioness precedencia y valores nulos

    def _join_filter_conditions(self, cond_nodes: List[Node]) -> str:
        translated: List[str] = []
        for node in cond_nodes:
            sql_cond = self._translate_filter_node(node)
            if (
                len(cond_nodes) > 1
                and isinstance(node, BinaryOperation)
                and node.operator.upper() == "OR"
            ):
                sql_cond = f"({sql_cond})"
            translated.append(sql_cond)
        return " AND ".join(translated)

    def _translate_filter_node(self, node: Node) -> str:
        if isinstance(node, Parameter):
            col_sql = self._qualify_column(node.name)
            if self._is_empty_literal(node.value):
                return f"{col_sql} IS NULL"
            val_sql = self._translate_expression(node.value, in_filter=True)
            return f"{col_sql} = {val_sql}"
        return self._translate_expression(node, in_filter=True)

    def _translate_expression(self, node: Node, in_filter: bool = False) -> str:
        if isinstance(node, Literal):
            return self._translate_literal(node)

        if isinstance(node, Identifier):
            return self._qualify_column(node.name)

        if isinstance(node, Parameter):
            return self._translate_filter_node(node)

        if isinstance(node, UnaryOperation):
            op = node.operator.upper()
            if op == "NOT":
                parent_prec = self.PRECEDENCE["NOT"]
                child_prec = self._get_node_precedence(node.operand)
                operand_sql = self._translate_expression(node.operand, in_filter=in_filter)
                if child_prec < parent_prec:
                    return f"NOT ({operand_sql})"
                return f"NOT {operand_sql}"

            # operadores unarios de mas y menos
            parent_prec = self.PRECEDENCE[f"UNARY_{op}"]
            child_prec = self._get_node_precedence(node.operand)
            operand_sql = self._translate_expression(node.operand, in_filter=in_filter)

            # ponemos parentesis para que dos signos menos seguidos no se vuelvan comentario sql
            if child_prec < parent_prec or (
                op == "-" and (isinstance(node.operand, UnaryOperation) or operand_sql.startswith("-"))
            ):
                return f"{op}({operand_sql})"
            return f"{op}{operand_sql}"

        if isinstance(node, BinaryOperation):
            op = node.operator.upper()

            # cambiar comparaciones con empty por is null o is not null
            if op in ("=", "!="):
                if self._is_empty_literal(node.right):
                    left_sql = self._translate_expression(node.left, in_filter=in_filter)
                    return f"{left_sql} IS NULL" if op == "=" else f"{left_sql} IS NOT NULL"
                if self._is_empty_literal(node.left):
                    right_sql = self._translate_expression(node.right, in_filter=in_filter)
                    return f"{right_sql} IS NULL" if op == "=" else f"{right_sql} IS NOT NULL"

            parent_prec = self.PRECEDENCE.get(op, 4)
            left_prec = self._get_node_precedence(node.left)
            right_prec = self._get_node_precedence(node.right)

            left_sql = self._translate_expression(node.left, in_filter=in_filter)
            right_sql = self._translate_expression(node.right, in_filter=in_filter)

            if left_prec < parent_prec:
                left_sql = f"({left_sql})"

            # poner parentesis al lado derecho si hace falta por la jerarquia
            if right_prec < parent_prec or (
                right_prec == parent_prec and op in ("+", "-", "*", "/", "%", "=", "!=", "<", ">", "<=", ">=")
            ):
                right_sql = f"({right_sql})"

            return f"{left_sql} {op} {right_sql}"

        return str(node)

    def _translate_literal(self, node: Literal) -> str:
        lit_type = node.literal_type.upper()
        if lit_type == "EMPTY":
            return "NULL"
        if lit_type in ("STRING_LITERAL", "DATE_LITERAL"):
            escaped = str(node.value).replace("'", "''")
            return f"'{escaped}'"
        if lit_type in ("TRUE", "FALSE", "BOOLEANO"):
            is_true = str(node.value).lower() == "true" or lit_type == "TRUE"
            return "TRUE" if is_true else "FALSE"
        return str(node.value)

    def _translate_pagination_arg(self, node: Node) -> str:
        const_val = self._evaluate_constant_int(node)
        if const_val is not None:
            return str(const_val)
        return self._translate_expression(node, in_filter=False)

    def _evaluate_constant_int(self, node: Node) -> Optional[int]:
        if isinstance(node, Literal) and node.literal_type.upper() == "NUMBER_INT":
            return int(node.value)
        if isinstance(node, UnaryOperation) and node.operator in ("+", "-"):
            val = self._evaluate_constant_int(node.operand)
            if val is not None:
                return val if node.operator == "+" else -val
        if isinstance(node, BinaryOperation) and node.operator in ("+", "-", "*", "/", "%"):
            left = self._evaluate_constant_int(node.left)
            right = self._evaluate_constant_int(node.right)
            if left is not None and right is not None:
                if node.operator == "+":
                    return left + right
                if node.operator == "-":
                    return left - right
                if node.operator == "*":
                    return left * right
                if right != 0:
                    if node.operator == "/":
                        return int(left // right)
                    if node.operator == "%":
                        return int(left % right)
        return None

    def _get_node_precedence(self, node: Node) -> int:
        if isinstance(node, (Literal, Identifier)):
            return self.PRECEDENCE["ATOM"]
        if isinstance(node, UnaryOperation):
            op = node.operator.upper()
            if op == "NOT":
                return self.PRECEDENCE["NOT"]
            return self.PRECEDENCE.get(f"UNARY_{op}", 7)
        if isinstance(node, BinaryOperation):
            return self.PRECEDENCE.get(node.operator.upper(), 4)
        return self.PRECEDENCE["ATOM"]

    @staticmethod
    def _is_empty_literal(node: Node) -> bool:
        return isinstance(node, Literal) and node.literal_type.upper() == "EMPTY"

    @staticmethod
    def _normalize_identifier(name: str) -> str:
        return name.strip().lower()

    def _qualify_column(self, field_name: str) -> str:
        # le pone el nombre de la tabla al campo cuando hay link y se repite
        col = self._normalize_identifier(field_name)
        if len(self.active_models) <= 1:
            return col

        matching_models = [
            m for m in self.active_models if m is not None and m.get_field(field_name) is not None
        ]
        if len(matching_models) > 1:
            owner = matching_models[0]
            return f"{self._normalize_identifier(owner.name)}.{col}"
        if len(matching_models) == 1 and matching_models[0] != self.active_models[0]:
            owner = matching_models[0]
            return f"{self._normalize_identifier(owner.name)}.{col}"
        return col

    def _extract_qualified_identifiers(self, node: Node) -> List[str]:
        # saca los nombres de columnas que aparecen dentro de una expresion
        cols: List[str] = []
        if isinstance(node, Identifier):
            cols.append(self._qualify_column(node.name))
        elif isinstance(node, Parameter):
            cols.append(self._qualify_column(node.name))
            cols.extend(self._extract_qualified_identifiers(node.value))
        elif isinstance(node, UnaryOperation):
            cols.extend(self._extract_qualified_identifiers(node.operand))
        elif isinstance(node, BinaryOperation):
            cols.extend(self._extract_qualified_identifiers(node.left))
            cols.extend(self._extract_qualified_identifiers(node.right))
        return cols
