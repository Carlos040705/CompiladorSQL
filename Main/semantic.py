import contextlib
from dataclasses import dataclass, field
from datetime import date
import io
import re
import textwrap
from typing import Dict, List, Optional, Sequence, Set, Union
from visitor import Visitor
from ast_nodes import (
    Program, ModelDeclaration, Field,
    DbOperation, Parameter, Literal, Identifier,
    BinaryOperation, UnaryOperation
)


# =====================================================================
# 0. EXTRACCIÓN DE CONTEXTO DE MODELOS Y NORMALIZACIÓN DE FRAGMENTOS
# =====================================================================

_MODEL_HEADER_RE = re.compile(r"^model\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*:", re.IGNORECASE)
_FIELD_HEADER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*\s*:")
_FIELD_FULL_RE = re.compile(
    r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*([a-zA-Z_][a-zA-Z0-9_]*)"
    r"(?:\s*\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\))?(.*)$"
)
_DML_OPERATION_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*\s*\.\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\(")
_VALID_FIELD_TYPES = {"STRING", "TEXT", "NUM", "AUTO", "DECIMAL", "BOOL", "DATE"}


def _extract_model_blocks_list(full_code: str) -> List[str]:
    """
    Extrae cada bloque `model <nombre>:` del código completo, normalizando
    la sangría de sus declaraciones de atributos a exactamente 4 espacios ('    ')
    sin importar si el archivo original mezcló 1, 2, 3 o 4 espacios.
    Devuelve una lista donde cada elemento es el código fuente de un bloque `model`.
    """
    if not full_code or not full_code.strip():
        return []

    normalized = full_code.replace("\r\n", "\n").replace("\t", "    ")
    lines = normalized.splitlines()

    blocks: List[List[str]] = []
    current_block: Optional[List[str]] = None
    in_multiline_comment = False

    for raw_line in lines:
        stripped = raw_line.strip()

        # Manejo de comentarios multilínea /* ... */
        if in_multiline_comment:
            if "*/" in stripped:
                in_multiline_comment = False
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped:
                in_multiline_comment = True
            continue

        # Eliminar comentario de una línea '//'
        code_part = raw_line.split("//", 1)[0].rstrip()
        code_stripped = code_part.strip()

        if not code_stripped:
            continue

        # ¿Es un encabezado `model <nombre>:` (con cualquier sangría base)?
        if _MODEL_HEADER_RE.match(code_stripped):
            if current_block is not None and len(current_block) > 1:
                blocks.append(current_block)
            current_block = [code_stripped]
            continue

        if current_block is not None:
            # ¿Es una declaración de atributo `<identificador> : <tipo>...` y no una operación DML?
            if (
                _FIELD_HEADER_RE.match(code_stripped)
                and not _MODEL_HEADER_RE.match(code_stripped)
                and not _DML_OPERATION_RE.match(code_stripped)
            ):
                current_block.append("    " + code_stripped)
            else:
                # Fin del bloque model al encontrar una operación DML u otra sentencia
                if len(current_block) > 1:
                    blocks.append(current_block)
                current_block = None

    if current_block is not None and len(current_block) > 1:
        blocks.append(current_block)

    return ["\n".join(block) + "\n" for block in blocks]


def extract_model_blocks_source(full_code: str) -> str:
    """
    Extrae únicamente los bloques `model <nombre>:` (con sus campos normalizados
    a 4 espacios de sangría) a partir del código completo del editor, ignorando
    operaciones DML sueltas.
    """
    blocks = _extract_model_blocks_list(full_code)
    if not blocks:
        return ""
    return "\n".join(b.rstrip("\n") for b in blocks) + "\n"


def normalize_dsl_fragment(fragment: str) -> str:
    """
    Normalización inteligente para fragmentos copiados al portapapeles:
    - Convierte tabulaciones en 4 espacios y normaliza saltos de línea.
    - Si el fragmento contiene únicamente operaciones DML (sin encabezados `model <nombre>:`),
      elimina los espacios iniciales de cada línea para evitar tokens INDENT o errores de sangría.
    - Si el fragmento contiene bloques `model` (solos o junto con operaciones DML), aplica
      `textwrap.dedent` y normaliza la sangría de los atributos de `model` a exactamente 4 espacios.
    """
    if not fragment or not fragment.strip():
        return ""

    cleaned = textwrap.dedent(fragment.replace("\r\n", "\n").replace("\t", "    "))
    lines = cleaned.splitlines()

    # Determinar si el fragmento contiene algún encabezado `model <nombre>:`
    has_model_header = False
    in_multiline = False
    for raw_line in lines:
        s = raw_line.strip()
        if in_multiline:
            if "*/" in s:
                in_multiline = False
            continue
        if s.startswith("/*"):
            if "*/" not in s:
                in_multiline = True
            continue
        code_stripped = raw_line.split("//", 1)[0].strip()
        if _MODEL_HEADER_RE.match(code_stripped):
            has_model_header = True
            break

    normalized_lines: List[str] = []
    if not has_model_header:
        # Solo operaciones DML (o comentarios): quitar sangría izquierda en cada línea
        for raw_line in lines:
            normalized_lines.append(raw_line.lstrip(" "))
        return "\n".join(normalized_lines) + "\n"

    # El fragmento incluye al menos un bloque `model <nombre>:`
    in_model = False
    in_multiline = False
    for raw_line in lines:
        s = raw_line.strip()
        if in_multiline:
            normalized_lines.append(raw_line)
            if "*/" in s:
                in_multiline = False
            continue
        if s.startswith("/*"):
            normalized_lines.append(raw_line)
            if "*/" not in s:
                in_multiline = True
            continue

        code_stripped = raw_line.split("//", 1)[0].strip()
        if not code_stripped:
            normalized_lines.append(raw_line.strip())
            continue

        if _MODEL_HEADER_RE.match(code_stripped):
            in_model = True
            normalized_lines.append(raw_line.lstrip(" "))
        elif in_model:
            if (
                _FIELD_HEADER_RE.match(code_stripped)
                and not _MODEL_HEADER_RE.match(code_stripped)
                and not _DML_OPERATION_RE.match(code_stripped)
            ):
                normalized_lines.append("    " + raw_line.lstrip(" "))
            else:
                in_model = False
                normalized_lines.append(raw_line.lstrip(" "))
        else:
            normalized_lines.append(raw_line.lstrip(" "))

    return "\n".join(normalized_lines) + "\n"


def _parse_model_source_quietly(source_text: str) -> List[ModelDeclaration]:
    """
    Ejecuta el lexer y parser sobre `source_text` preservando intacto el estado
    global de errores léxicos/sintácticos y el número de línea del lexer.
    """
    if not source_text or not source_text.strip():
        return []

    from lexer import lexer, errores_lexicos
    from parser import parser, errores_sintacticos

    saved_lex_errors = list(errores_lexicos)
    saved_syn_errors = list(errores_sintacticos)
    saved_lineno = getattr(lexer, "lineno", 1)

    parsed_models: List[ModelDeclaration] = []
    try:
        errores_lexicos.clear()
        errores_sintacticos.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            lexer.input(source_text if source_text.endswith("\n") else source_text + "\n")
            tokens = []
            while True:
                tok = lexer.token()
                if tok is None:
                    break
                tokens.append(tok)
            if tokens and not errores_lexicos:
                token_iter = iter(tokens)
                ast_ctx = parser.parse(tokenfunc=lambda: next(token_iter, None))
                if ast_ctx and getattr(ast_ctx, "statements", None):
                    parsed_models = [
                        stmt for stmt in ast_ctx.statements
                        if isinstance(stmt, ModelDeclaration)
                    ]
    except Exception:
        parsed_models = []
    finally:
        errores_lexicos.clear()
        errores_lexicos.extend(saved_lex_errors)
        errores_sintacticos.clear()
        errores_sintacticos.extend(saved_syn_errors)
        lexer.lineno = saved_lineno

    return parsed_models


def extract_context_models(full_code: str) -> List[ModelDeclaration]:
    """
    Parsea los bloques `model <nombre>:` del código completo del editor y devuelve
    la lista de nodos `ModelDeclaration`. Si un archivo tiene múltiples bloques
    `model` y alguno contiene un error sintáctico, parsea cada bloque individualmente
    como fallback para rescatar todos los modelos válidos.
    """
    blocks = _extract_model_blocks_list(full_code)
    if not blocks:
        return []

    combined_source = "\n".join(b.rstrip("\n") for b in blocks) + "\n"
    models = _parse_model_source_quietly(combined_source)

    if len(models) < len(blocks):
        seen_names = {m.name.lower() for m in models}
        for single_block in blocks:
            single_models = _parse_model_source_quietly(single_block)
            for m in single_models:
                if m.name.lower() not in seen_names:
                    models.append(m)
                    seen_names.add(m.name.lower())

    return models


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

    def clone(self) -> "FieldSymbol":
        return FieldSymbol(
            name=self.name,
            data_type=self.data_type,
            type_args=list(self.type_args),
            constraints=set(self.constraints),
            default_value=self.default_value,
            lineno=self.lineno,
        )


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

    def clone(self) -> "ModelSymbol":
        cloned = ModelSymbol(name=self.name, lineno=self.lineno)
        for key, f_sym in self.fields.items():
            cloned.fields[key] = f_sym.clone()
        return cloned


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

    def merge_from(
        self,
        other_table: Optional[Union["SymbolTable", Dict[str, ModelSymbol]]],
        overwrite: bool = True,
    ) -> None:
        """
        Copia o actualiza los `ModelSymbol` (y sus `FieldSymbol` clonados) desde
        otra tabla de símbolos sin perder los modelos ya registrados.
        """
        if other_table is None:
            return
        source_models = (
            other_table.models
            if isinstance(other_table, SymbolTable)
            else other_table
        )
        for key, model_sym in source_models.items():
            if not isinstance(model_sym, ModelSymbol):
                continue
            norm_key = key.lower()
            if overwrite or norm_key not in self.models:
                self.models[norm_key] = model_sym.clone()

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


def _parse_models_fallback_regex(full_code: str) -> SymbolTable:
    """
    Analizador de respaldo línea por línea sobre los bloques `model` en caso de que
    el parser de PLY falle por algún token inesperado en otro lugar del archivo.
    """
    table = SymbolTable()
    if not full_code or not full_code.strip():
        return table

    normalized = full_code.replace("\r\n", "\n").replace("\t", "    ")
    lines = normalized.splitlines()
    current_model: Optional[ModelSymbol] = None
    in_multiline_comment = False

    for idx, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if in_multiline_comment:
            if "*/" in stripped:
                in_multiline_comment = False
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped:
                in_multiline_comment = True
            continue

        code_stripped = raw_line.split("//", 1)[0].strip()
        if not code_stripped:
            continue

        header_match = _MODEL_HEADER_RE.match(code_stripped)
        if header_match:
            if current_model is not None and current_model.fields:
                table.models[current_model.name.lower()] = current_model
            model_name = header_match.group(1)
            current_model = ModelSymbol(name=model_name, lineno=idx)
            continue

        if current_model is not None:
            if _DML_OPERATION_RE.match(code_stripped):
                if current_model.fields:
                    table.models[current_model.name.lower()] = current_model
                current_model = None
                continue

            field_match = _FIELD_FULL_RE.match(code_stripped)
            if field_match:
                f_name = field_match.group(1)
                f_type = field_match.group(2).upper()
                if f_type in _VALID_FIELD_TYPES:
                    type_args: List[int] = []
                    if field_match.group(3) is not None:
                        type_args.append(int(field_match.group(3)))
                    if field_match.group(4) is not None:
                        type_args.append(int(field_match.group(4)))

                    rest_text = (field_match.group(5) or "").strip()
                    rest_lower = rest_text.lower()
                    constraints: Set[str] = set()
                    if "main key" in rest_lower:
                        constraints.add("MAIN KEY")
                    if "external key" in rest_lower:
                        constraints.add("EXTERNAL KEY")
                    if re.search(r"\brequired\b", rest_lower):
                        constraints.add("REQUIRED")
                    if re.search(r"\bunique\b", rest_lower):
                        constraints.add("UNIQUE")
                    if re.search(r"\bdefault\b", rest_lower):
                        constraints.add("DEFAULT")

                    current_model.add_field(
                        FieldSymbol(
                            name=f_name,
                            data_type=f_type,
                            type_args=type_args,
                            constraints=constraints,
                            default_value=None,
                            lineno=idx,
                        )
                    )
                    continue

            # Línea que no pertenece al bloque model
            if current_model.fields:
                table.models[current_model.name.lower()] = current_model
            current_model = None

    if current_model is not None and current_model.fields:
        table.models[current_model.name.lower()] = current_model

    return table


def build_context_symbol_table(
    full_code: str,
    fallback_table: Optional[SymbolTable] = None,
) -> SymbolTable:
    """
    Construye una `SymbolTable` de contexto combinando:
    1. `fallback_table` (si se proporciona, como `session_symbol_table`).
    2. Los modelos extraídos por AST mediante `extract_context_models(full_code)`.
    3. El analizador de respaldo línea por línea (`_parse_models_fallback_regex`)
       por si algún modelo no pudo ser parseado por PLY.
    """
    result_table = SymbolTable()
    if fallback_table is not None:
        result_table.merge_from(fallback_table, overwrite=True)

    if full_code and full_code.strip():
        ast_models = extract_context_models(full_code)
        if ast_models:
            temp_analyzer = SemanticAnalyzer()
            with contextlib.redirect_stdout(io.StringIO()):
                for m_node in ast_models:
                    temp_analyzer.visit_ModelDeclaration(m_node)
            result_table.merge_from(temp_analyzer.symbol_table, overwrite=True)

        regex_table = _parse_models_fallback_regex(full_code)
        # Inyectar cualquier modelo que el parser de PLY no haya podido construir
        result_table.merge_from(regex_table, overwrite=False)

    return result_table


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
        self.warnings: List[str] = []
        self.active_models: List[ModelSymbol] = []
        self._persistent_symbols: Optional[SymbolTable] = None

    def report_error(self, message: str, lineno: int = 0):
        loc = f" (Línea {lineno})" if lineno > 0 else ""
        full_msg = f"[!] Error Semántico{loc}: {message}"
        self.errors.append(full_msg)
        print(full_msg)

    def preload_context_models(
        self,
        context_models: Sequence[ModelDeclaration],
        skip_model_names: Optional[Set[str]] = None,
    ):
        """
        Registra declaraciones `model` de contexto en la Tabla de Símbolos
        sin añadirlas al AST del fragmento que se va a compilar/generar.
        """
        skip_set = {name.lower() for name in (skip_model_names or set())}
        with contextlib.redirect_stdout(io.StringIO()):
            for model_node in context_models:
                if not isinstance(model_node, ModelDeclaration):
                    continue
                if model_node.name.lower() in skip_set:
                    continue
                if self.symbol_table.get_model(model_node.name) is not None:
                    continue
                self.visit_ModelDeclaration(model_node)
        # Limpiar cualquier advertencia/error del pre-cargado para evaluar solo el fragmento
        self.errors.clear()

    def preload_symbol_table(
        self,
        source_symbols: Optional[Union[SymbolTable, Dict[str, ModelSymbol]]],
        skip_model_names: Optional[Set[str]] = None,
    ):
        """
        Inyecta en `self.symbol_table` cualquier `ModelSymbol` presente en `source_symbols`
        que aún no esté registrado ni sea redeclarado explícitamente en el AST actual.
        """
        if source_symbols is None:
            return
        skip_set = {name.lower() for name in (skip_model_names or set())}
        models_dict = (
            source_symbols.models
            if isinstance(source_symbols, SymbolTable)
            else source_symbols
        )
        for key, model_sym in models_dict.items():
            if not isinstance(model_sym, ModelSymbol):
                continue
            norm_key = key.lower()
            if norm_key in skip_set:
                continue
            if self.symbol_table.get_model(norm_key) is None:
                self.symbol_table.models[norm_key] = model_sym.clone()

    def _resolve_or_inject_model(self, name: str) -> Optional[ModelSymbol]:
        model = self.symbol_table.get_model(name)
        if model is not None:
            return model
        if self._persistent_symbols is not None:
            fallback = self._persistent_symbols.get_model(name)
            if fallback is not None:
                cloned = fallback.clone()
                self.symbol_table.models[name.lower()] = cloned
                return cloned
        return None

    def analyze(
        self,
        ast_root: Program,
        context_models: Optional[Sequence[ModelDeclaration]] = None,
        context_code: Optional[str] = None,
        persistent_symbols: Optional[Union[SymbolTable, Dict[str, ModelSymbol]]] = None,
    ):
        self.symbol_table.clear()
        self.errors.clear()
        self.warnings.clear()

        if isinstance(persistent_symbols, SymbolTable):
            self._persistent_symbols = persistent_symbols
        elif isinstance(persistent_symbols, dict):
            temp_sym = SymbolTable()
            temp_sym.merge_from(persistent_symbols, overwrite=True)
            self._persistent_symbols = temp_sym
        else:
            self._persistent_symbols = None

        declared_in_ast = {
            stmt.name.lower()
            for stmt in (getattr(ast_root, "statements", None) or [])
            if isinstance(stmt, ModelDeclaration)
        }

        if context_models is None and context_code:
            context_models = extract_context_models(context_code)

        if context_models:
            self.preload_context_models(context_models, skip_model_names=declared_in_ast)

        if context_code:
            ctx_table = build_context_symbol_table(context_code)
            self.preload_symbol_table(ctx_table, skip_model_names=declared_in_ast)

        if self._persistent_symbols is not None:
            self.preload_symbol_table(self._persistent_symbols, skip_model_names=declared_in_ast)

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
        default_constraints = []
        for c in node.constraints:
            c_type = c.constraint_type.upper()
            if c_type in constraints_set:
                self.report_error(
                    f"Restricción '{c_type}' duplicada en el campo '{node.name}' del modelo '{model_sym.name}'.",
                    lineno
                )
            constraints_set.add(c_type)
            if c_type == 'DEFAULT' and c.value is not None:
                default_constraints.append(c)

        default_val = default_constraints[0].value if default_constraints else None
        for constraint in default_constraints:
            c_lineno = getattr(constraint, 'lineno', lineno) or lineno
            val_type = self.visit(constraint.value)
            if dtype_name == 'AUTO':
                self.report_error(
                    f"El campo '{node.name}' es de tipo 'auto' (autoincremental) y no puede tener un valor 'default'.",
                    c_lineno
                )
            elif val_type == 'NULL' and 'REQUIRED' in constraints_set:
                self.report_error(
                    f"El campo '{node.name}' es 'required' pero su valor por defecto es 'empty' (nulo).",
                    c_lineno
                )
            elif not are_types_compatible_for_assignment(dtype_name, val_type):
                self.report_error(
                    f"Tipo incompatible en 'default' del campo '{node.name}': "
                    f"el campo es '{dtype_name}' pero el valor por defecto es de tipo '{val_type}'.",
                    c_lineno
                )
            elif dtype_name == 'DECIMAL' and len(dtype_args) == 2:
                self._validate_decimal_overflow(node.name, dtype_args, constraint.value, c_lineno)

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
        base_model = self._resolve_or_inject_model(node.model_name)
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
                call_lineno = getattr(call, 'lineno', lineno) or lineno
                self._validate_link_call(call, call_lineno)

        # Validar coherencia de la cadena de métodos y cada eslabón
        self._validate_method_chain_coherence(calls, lineno)

        for index, call in enumerate(calls):
            if call.method.lower() != 'link':  # link ya fue validado
                call_lineno = getattr(call, 'lineno', lineno) or lineno
                self._validate_single_call(
                    call,
                    base_model,
                    call_lineno,
                    has_prior_filter=any(
                        prior.method.lower() == 'if' and prior.arguments
                        for prior in calls[:index]
                    ),
                )

        self.active_models = []

    def _validate_link_call(self, call, lineno: int):
        call_lineno = getattr(call, 'lineno', lineno) or lineno
        if len(call.arguments) != 1 or not isinstance(call.arguments[0], Identifier):
            self.report_error(
                "El método '.link()' requiere exactamente el nombre de un modelo como argumento (ej. .link(Curso)).",
                call_lineno
            )
            return
        arg = call.arguments[0]
        arg_lineno = getattr(arg, 'lineno', call_lineno) or call_lineno
        target_name = arg.name
        target_model = self._resolve_or_inject_model(target_name)
        if target_model is None:
            self.report_error(
                f"El modelo '{target_name}' referenciado en '.link({target_name})' no existe.",
                arg_lineno
            )
        elif self.active_models and target_model == self.active_models[0]:
            self.report_error(
                f"Auto-enlace inválido en '.link({target_name})': el modelo '{target_model.name}' es el modelo base y ya forma parte del ámbito activo de la consulta.",
                arg_lineno
            )
        elif target_model in self.active_models:
            self.report_error(
                f"Enlace duplicado en '.link({target_name})': el modelo '{target_model.name}' ya fue unido previamente y ya forma parte del ámbito activo de la consulta.",
                arg_lineno
            )
        else:
            self.active_models.append(target_model)

    def _validate_method_chain_coherence(self, calls: list, lineno: int):
        methods = [c.method.lower() for c in calls]
        # new/add no deben encadenarse con cláusulas de consulta
        if ('new' in methods or 'add' in methods) and len(methods) > 1:
            self.report_error(
                f"El método de inserción '.{methods[0]}()' no puede encadenarse con otros métodos ({methods}).",
                lineno
            )
        # ifgroup (HAVING) requiere group (GROUP BY) en la cadena
        if 'ifgroup' in methods and 'group' not in methods:
            ifgroup_call = next((c for c in calls if c.method.lower() == 'ifgroup'), None)
            err_lineno = getattr(ifgroup_call, 'lineno', lineno) or lineno
            self.report_error(
                "El método '.ifgroup()' (HAVING) solo puede utilizarse cuando existe '.group()' (GROUP BY) en la cadena.",
                err_lineno
            )

        # Mezcla de operaciones mutadoras o terminales incompatibles
        if 'modify' in methods and 'remove' in methods:
            second_mut = next(
                (c for c in calls if c.method.lower() in ('modify', 'remove') and c != calls[0]),
                calls[-1]
            )
            err_lineno = getattr(second_mut, 'lineno', lineno) or lineno
            self.report_error(
                "Operaciones mutadoras incompatibles: no se puede combinar '.modify()' y '.remove()' en la misma cadena.",
                err_lineno
            )

        incompatible_with_mutation = {
            'count', 'sum', 'avg', 'max', 'min',
            'group', 'ifgroup',
            'up', 'down',
            'take', 'skip',
        }
        if 'modify' in methods or 'remove' in methods:
            mut_name = 'modify' if 'modify' in methods else 'remove'
            for call in calls:
                m = call.method.lower()
                if m in incompatible_with_mutation:
                    err_lineno = getattr(call, 'lineno', lineno) or lineno
                    self.report_error(
                        f"Operación incompatible en la cadena: no se puede combinar '.{mut_name}()' con '.{m}()'.",
                        err_lineno
                    )

        # Orden inválido de filtrado respecto a mutaciones
        seen_mutation = None
        for call in calls:
            m = call.method.lower()
            if m in ('modify', 'remove') and seen_mutation is None:
                seen_mutation = m
            elif m == 'if' and seen_mutation is not None:
                err_lineno = getattr(call, 'lineno', lineno) or lineno
                self.report_error(
                    f"Orden inválido en la cadena: el filtro '.if()' debe preceder a la operación de modificación o borrado '.{seen_mutation}()'.",
                    err_lineno
                )

        # Cláusulas únicas duplicadas en la misma cadena
        single_clause_methods = {'take', 'skip', 'group', 'ifgroup', 'modify', 'remove', 'new', 'add'}
        seen_single_clauses = set()
        for call in calls:
            m = call.method.lower()
            if m in single_clause_methods:
                if m in seen_single_clauses:
                    err_lineno = getattr(call, 'lineno', lineno) or lineno
                    self.report_error(
                        f"Cláusula duplicada en la cadena: el método '.{m}()' no puede invocarse más de una vez en la misma consulta.",
                        err_lineno
                    )
                seen_single_clauses.add(m)

    def _validate_single_call(
        self,
        call,
        base_model: ModelSymbol,
        lineno: int,
        has_prior_filter: bool = False,
    ):
        call_lineno = getattr(call, 'lineno', lineno) or lineno
        method = call.method.lower()
        args = call.arguments or []

        if method in ('new', 'add', 'modify'):
            seen_parameters = set()
            for arg in args:
                if not isinstance(arg, Parameter):
                    continue
                arg_lineno = getattr(arg, 'lineno', call_lineno) or call_lineno
                key = arg.name.lower()
                if key in seen_parameters:
                    self.report_error(
                        f"El campo '{arg.name}' aparece más de una vez en los argumentos de '.{method}()'.",
                        arg_lineno
                    )
                seen_parameters.add(key)

        # 1. Inserción: .new(...) o .add(...)
        if method in ('new', 'add'):
            if not args:
                self.report_error(
                    f"El método '.{method}()' sobre '{base_model.name}' requiere al menos un parámetro de asignación.",
                    call_lineno
                )
                return
            provided_fields = set()
            for arg in args:
                arg_lineno = getattr(arg, 'lineno', call_lineno) or call_lineno
                if not isinstance(arg, Parameter):
                    self.report_error(
                        f"En '.{method}()', todos los argumentos deben ser asignaciones 'campo = valor'.",
                        arg_lineno
                    )
                    continue
                self._validate_parameter_assignment(arg, base_model, is_insert=True, lineno=arg_lineno)
                provided_fields.add(arg.name.lower())

            # Verificar campos obligatorios (REQUIRED sin DEFAULT y que no sean AUTO)
            for f_sym in base_model.fields.values():
                if f_sym.is_required and f_sym.name.lower() not in provided_fields:
                    self.report_error(
                        f"Falta el campo obligatorio '{f_sym.name}' (required) al insertar en el modelo '{base_model.name}'.",
                        call_lineno
                    )

        # 2. Actualización: .modify(...)
        elif method == 'modify':
            if not args:
                self.report_error(
                    f"El método '.modify()' sobre '{base_model.name}' requiere al menos un campo a modificar.",
                    call_lineno
                )
                return
            for arg in args:
                arg_lineno = getattr(arg, 'lineno', call_lineno) or call_lineno
                if not isinstance(arg, Parameter):
                    self.report_error(
                        "En '.modify()', todos los argumentos deben ser asignaciones 'campo = nuevo_valor'.",
                        arg_lineno
                    )
                    continue
                self._validate_parameter_assignment(arg, base_model, is_insert=False, lineno=arg_lineno)

        # 3. Consulta / Proyección: .find(...)
        elif method == 'find':
            for arg in args:
                arg_lineno = getattr(arg, 'lineno', call_lineno) or call_lineno
                if isinstance(arg, Identifier):
                    self._resolve_field_or_error(arg.name, arg_lineno)
                elif isinstance(arg, Parameter):
                    # Soporta sintaxis corta Estudiante.find(edad = 67)
                    self._validate_parameter_filter(arg, arg_lineno)
                else:
                    cond_type = self.visit(arg)
                    if cond_type not in ('BOOL', 'ERROR'):
                        self.report_error(
                            f"Argumento inválido en '.find()': se esperaba un nombre de campo o una condición booleana, pero se obtuvo '{cond_type}'.",
                            arg_lineno
                        )

        # 4. Filtros condicionales: .if(...) / .ifgroup(...) / .remove(...)
        elif method in ('if', 'ifgroup', 'remove'):
            if method == 'remove' and not has_prior_filter and not args:
                self.report_error(
                    "El método '.remove()' requiere una condición '.if(...)' previa o una condición como argumento.",
                    call_lineno
                )
            if method in ('if', 'ifgroup') and not args:
                self.report_error(f"El método '.{method}()' requiere una condición lógica o relacional.", call_lineno)
                return
            for arg in args:
                arg_lineno = getattr(arg, 'lineno', call_lineno) or call_lineno
                if isinstance(arg, Parameter):
                    self._validate_parameter_filter(arg, arg_lineno)
                else:
                    cond_type = self.visit(arg)
                    if cond_type not in ('BOOL', 'ERROR'):
                        self.report_error(
                            f"La condición dentro de '.{method}()' debe evaluarse a un valor booleano (BOOL), pero se obtuvo '{cond_type}'.",
                            arg_lineno
                        )

        # 5. Ordenamiento y Agrupación: .up(...), .down(...), .group(...)
        elif method in ('up', 'down', 'group'):
            if not args:
                self.report_error(f"El método '.{method}()' requiere al menos un nombre de campo.", call_lineno)
                return
            for arg in args:
                arg_lineno = getattr(arg, 'lineno', call_lineno) or call_lineno
                if not isinstance(arg, Identifier):
                    self.report_error(
                        f"El método '.{method}()' solo acepta nombres de campos (identificadores) como argumentos.",
                        arg_lineno
                    )
                else:
                    self._resolve_field_or_error(arg.name, arg_lineno)

        # 6. Paginación: .take(N) y .skip(N)
        elif method in ('take', 'skip'):
            if len(args) != 1:
                self.report_error(f"El método '.{method}()' requiere exactamente 1 argumento entero.", call_lineno)
                return
            arg = args[0]
            arg_lineno = getattr(arg, 'lineno', call_lineno) or call_lineno
            arg_type = self.visit(arg)
            if arg_type not in ('NUM', 'ERROR'):
                self.report_error(
                    f"El método '.{method}()' requiere un número entero (NUM), pero recibió '{arg_type}'.",
                    arg_lineno
                )
                return
            const_val = self._constant_numeric_value(arg)
            if const_val is not None:
                if method == 'take' and const_val <= 0:
                    self.report_error(
                        f"El método '.take()' requiere un entero positivo mayor a 0 (no acepta cantidades negativas ni cero), pero se evaluó a {const_val}.",
                        arg_lineno
                    )
                elif method == 'skip' and const_val < 0:
                    self.report_error(
                        f"El método '.skip()' requiere un entero mayor o igual a 0 (no acepta cantidades negativas), pero se evaluó a {const_val}.",
                        arg_lineno
                    )
            elif isinstance(arg, UnaryOperation) and arg.operator == '-':
                self.report_error(
                    f"El método '.{method}()' no acepta cantidades negativas.",
                    arg_lineno
                )

        # 7. Funciones de agregación: .count(), .sum(campo), .avg(campo), .max(campo), .min(campo)
        elif method == 'count':
            if len(args) > 1:
                self.report_error("El método '.count()' acepta como máximo 1 campo opcional.", call_lineno)
            elif len(args) == 1:
                arg_lineno = getattr(args[0], 'lineno', call_lineno) or call_lineno
                if not isinstance(args[0], Identifier):
                    self.report_error("El argumento de '.count()' debe ser el nombre de un campo.", arg_lineno)
                else:
                    self._resolve_field_or_error(args[0].name, arg_lineno)

        elif method in ('sum', 'avg', 'max', 'min'):
            if len(args) != 1 or not isinstance(args[0], Identifier):
                arg_lineno = getattr(args[0], 'lineno', call_lineno) or call_lineno if args else call_lineno
                self.report_error(
                    f"La función de agregación '.{method}()' requiere exactamente el nombre de un campo como argumento.",
                    arg_lineno
                )
                return
            arg_lineno = getattr(args[0], 'lineno', call_lineno) or call_lineno
            f_sym = self._resolve_field_or_error(args[0].name, arg_lineno)
            if f_sym and method in ('sum', 'avg') and f_sym.data_type not in NUMERIC_TYPES:
                self.report_error(
                    f"La función '.{method}()' requiere un campo numérico, pero '{f_sym.name}' es de tipo '{f_sym.data_type}'.",
                    arg_lineno
                )

        else:
            self.report_error(f"El método '.{method}()' no es una operación válida del lenguaje.", call_lineno)

    # --- Auxiliares de validación de parámetros y campos ---
    def _resolve_field_or_error(self, field_name: str, lineno: int) -> Optional[FieldSymbol]:
        if self.active_models:
            base_field = self.active_models[0].get_field(field_name)
            if base_field is not None:
                return base_field

        matches = [
            (model, model.get_field(field_name))
            for model in self.active_models[1:]
            if model.get_field(field_name) is not None
        ]
        if not matches and self.active_models and self.active_models[0].get_field(field_name) is None:
            model_names = ", ".join(m.name for m in self.active_models)
            self.report_error(
                f"El campo '{field_name}' no existe en el modelo activo ({model_names}).",
                lineno
            )
            return None
        if len(matches) > 1:
            model_names = ", ".join(model.name for model, _ in matches)
            self.report_error(
                f"El campo '{field_name}' es ambiguo entre los modelos enlazados: {model_names}.",
                lineno
            )
            return None
        return matches[0][1] if matches else None

    def _validate_decimal_overflow(self, field_name: str, type_args: List[int], value_node, lineno: int):
        if len(type_args) != 2:
            return
        precision, scale = type_args[0], type_args[1]
        if precision <= 0 or scale < 0 or scale > precision:
            return
        val = self._constant_numeric_value(value_node)
        if val is None or isinstance(val, bool):
            return
        max_int_digits = precision - scale
        limit = 10 ** max_int_digits
        if abs(val) >= limit:
            self.report_error(
                f"Desbordamiento numérico en el campo '{field_name}': el valor {val} excede el límite de parte entera de DECIMAL({precision},{scale}) (máximo permitido: < {limit}).",
                lineno
            )

    def _validate_parameter_assignment(self, param: Parameter, model: ModelSymbol, is_insert: bool, lineno: int):
        param_lineno = getattr(param, 'lineno', lineno) or lineno
        f_sym = model.get_field(param.name)
        if f_sym is None:
            self.report_error(
                f"El campo '{param.name}' no existe en el modelo '{model.name}'.",
                param_lineno
            )
            return

        if f_sym.data_type == 'AUTO':
            accion = "insertar" if is_insert else "modificar"
            self.report_error(
                f"No se puede {accion} manualmente el campo '{f_sym.name}' porque es de tipo 'auto' (autoincremental).",
                param_lineno
            )
            return

        val_type = self.visit(param.value)
        if val_type == 'NULL':
            if 'REQUIRED' in f_sym.constraints:
                self.report_error(
                    f"El campo '{f_sym.name}' tiene la restricción 'required' y no admite el valor 'empty' (NULL).",
                    param_lineno
                )
            return

        if not are_types_compatible_for_assignment(f_sym.data_type, val_type):
            self.report_error(
                f"Incompatibilidad de tipos en '{param.name}': el campo es de tipo '{f_sym.data_type}', "
                f"pero se intentó asignar un valor de tipo '{val_type}'.",
                param_lineno
            )
        elif f_sym.data_type == 'DECIMAL' and len(f_sym.type_args) == 2:
            self._validate_decimal_overflow(f_sym.name, f_sym.type_args, param.value, param_lineno)

    def _validate_parameter_filter(self, param: Parameter, lineno: int):
        """Valida un Parameter(campo, valor) cuando se usa como condición de igualdad (ej. .if(nombre = 'Jose'))."""
        param_lineno = getattr(param, 'lineno', lineno) or lineno
        f_sym = self._resolve_field_or_error(param.name, param_lineno)
        val_type = self.visit(param.value)
        if f_sym is not None and not are_types_comparable(f_sym.data_type, val_type, '='):
            self.report_error(
                f"Comparación inválida en '{param.name} = ...': no se puede comparar el campo '{f_sym.name}' ({f_sym.data_type}) con un valor de tipo '{val_type}'.",
                param_lineno
            )

    # --- 3.3 Inferencia y Verificación de Tipos en Expresiones ---
    def visit_Literal(self, node: Literal) -> str:
        if node.literal_type.upper() == 'DATE_LITERAL':
            lineno = getattr(node, 'lineno', 0)
            try:
                date.fromisoformat(str(node.value))
            except ValueError:
                self.report_error(
                    f"Fecha calendario inválida '{node.value}': no corresponde a una fecha real del calendario.",
                    lineno
                )
                return 'ERROR'
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
            # Detect zero divisors even when they are expressed as constant subexpressions.
            if op in ('/', '%') and self._constant_numeric_value(node.right) == 0:
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

    def _constant_numeric_value(self, node):
        if isinstance(node, Literal) and node.literal_type in ('NUMBER_INT', 'NUMBER_DECIMAL'):
            return node.value
        if isinstance(node, UnaryOperation) and node.operator in ('+', '-'):
            value = self._constant_numeric_value(node.operand)
            if value is not None:
                return value if node.operator == '+' else -value
        if isinstance(node, BinaryOperation) and node.operator in ('+', '-', '*', '/', '%'):
            left = self._constant_numeric_value(node.left)
            right = self._constant_numeric_value(node.right)
            if left is None or right is None:
                return None
            if node.operator == '+':
                return left + right
            if node.operator == '-':
                return left - right
            if node.operator == '*':
                return left * right
            if right == 0:
                return None
            if node.operator == '/':
                return left / right
            return left % right
        return None
