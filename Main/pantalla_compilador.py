import asyncio
import contextlib
import ctypes
import io
import os
import queue
import re
import shutil
import textwrap
import threading
import time
from pathlib import Path

import flet as ft
import pyte
try:
    from winpty import PtyProcess, WinptyError
except ImportError:
    PtyProcess = None  # type: ignore
    WinptyError = OSError  # type: ignore

from ast_nodes import (
    BinaryOperation,
    DbOperation,
    Identifier,
    Literal,
    ModelDeclaration,
    Parameter,
    Program,
    UnaryOperation,
)
from codegen import SQLCodeGenerator
from db_executor import PostgresExecutor, load_db_config, save_db_config
from lexer import errores_lexicos, lexer
from parser import errores_sintacticos, parser
from semantic import (
    SemanticAnalyzer,
    SymbolTable,
    build_context_symbol_table,
    extract_context_models,
    normalize_dsl_fragment,
)


BACKGROUND = "#101722"
PANEL = "#172232"
PANEL_LIGHT = "#203149"
HEADER = "#1c2b40"
BORDER = "#2d405b"
TEXT = "#e5edf7"
MUTED = "#93a4ba"
ACCENT = "#24b8ad"
BLUE = "#4da3ff"


# =====================================================================
# UTILIDADES DE PORTAPAPELES DEL SISTEMA (WINDOWS NATIVO + TKINTER)
# =====================================================================

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def leer_portapapeles_sistema() -> str:
    """
    Lee el texto actual del portapapeles del sistema de forma síncrona e instantánea.
    Intenta primero con tkinter (librería estándar) y usa la API nativa Win32 (ctypes)
    como respaldo directo en Windows.
    """
    # 1. Intento mediante tkinter
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        try:
            contenido = root.clipboard_get()
        except Exception:
            contenido = ""
        finally:
            try:
                root.destroy()
            except Exception:
                pass
        if isinstance(contenido, str) and contenido:
            return contenido
    except Exception:
        pass

    # 2. Respaldo directo con API Win32 (ctypes)
    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.OpenClipboard.argtypes = [ctypes.c_void_p]
            user32.OpenClipboard.restype = ctypes.c_int
            user32.GetClipboardData.argtypes = [ctypes.c_uint]
            user32.GetClipboardData.restype = ctypes.c_void_p
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = ctypes.c_int
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.restype = ctypes.c_int

            if user32.OpenClipboard(None):
                try:
                    handle = user32.GetClipboardData(CF_UNICODETEXT)
                    if handle:
                        pcontents = kernel32.GlobalLock(handle)
                        if pcontents:
                            try:
                                texto = ctypes.wstring_at(pcontents)
                                return texto or ""
                            finally:
                                kernel32.GlobalUnlock(handle)
                finally:
                    user32.CloseClipboard()
        except Exception:
            pass

    return ""


def copiar_portapapeles_sistema(texto: str) -> bool:
    """
    Copia texto al portapapeles del sistema de forma síncrona usando tkinter
    y la API nativa Win32 (ctypes) como respaldo.
    """
    texto_str = str(texto or "")

    # 1. Intento con API Win32 (instantáneo y persistente tras cerrar ventana)
    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.OpenClipboard.argtypes = [ctypes.c_void_p]
            user32.OpenClipboard.restype = ctypes.c_int
            user32.EmptyClipboard.argtypes = []
            user32.EmptyClipboard.restype = ctypes.c_int
            user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
            user32.SetClipboardData.restype = ctypes.c_void_p
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = ctypes.c_int
            kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
            kernel32.GlobalAlloc.restype = ctypes.c_void_p
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.restype = ctypes.c_int

            raw_bytes = (texto_str + "\x00").encode("utf-16-le")
            h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(raw_bytes))
            if h_mem:
                ptr = kernel32.GlobalLock(h_mem)
                if ptr:
                    ctypes.memmove(ptr, raw_bytes, len(raw_bytes))
                    kernel32.GlobalUnlock(h_mem)
                    if user32.OpenClipboard(None):
                        try:
                            user32.EmptyClipboard()
                            user32.SetClipboardData(CF_UNICODETEXT, h_mem)
                            return True
                        finally:
                            user32.CloseClipboard()
        except Exception:
            pass

    # 2. Respaldo mediante tkinter
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        try:
            root.clipboard_clear()
            root.clipboard_append(texto_str)
            root.update()
            return True
        finally:
            try:
                root.destroy()
            except Exception:
                pass
    except Exception:
        return False


def crear_borde_campo(
    color_default: str = BORDER,
    color_foco: str = ACCENT,
    radio: int = 4,
):
    """Configuración moderna de bordes para TextField en Flet 1.0+ sin DeprecationWarning."""
    return {
        ft.ControlState.DEFAULT: ft.OutlineInputBorder(
            border_radius=radio,
            side=ft.BorderSide(1, color_default),
        ),
        ft.ControlState.FOCUSED: ft.OutlineInputBorder(
            border_radius=radio,
            side=ft.BorderSide(1.5, color_foco),
        ),
    }


def normalizar_tabulaciones(texto: str) -> str:
    """Reemplaza retornos de carro Windows y convierte tabuladores '\\t' en 4 espacios."""
    return (texto or "").replace("\r\n", "\n").replace("\t", "    ")


def iniciar_interfaz(page: ft.Page):
    page.title = "CompiladorSQL — Editor y compilador"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BACKGROUND
    page.padding = 0
    page.spacing = 0

    # Bandera de estado de ciclo de vida para evitar RuntimeError y WinError 10054 al cerrar
    app_cerrando = False

    root_directory = Path(__file__).resolve().parent.parent
    active_path = root_directory / "Prueba.txt"
    if not active_path.is_file():
        active_path = None
    saved_content = ""
    previous_editor_text = ""
    editor_has_focus = False
    documents: list[dict] = []
    active_document: dict | None = None
    next_document_id = 1
    session_symbol_table = SymbolTable()
    expanded_directories: set[Path] = set()
    renaming_path: Path | None = None
    active_context_menu_overlay: ft.Control | None = None
    shell_process: PtyProcess | None = None
    terminal_columns = 80
    terminal_rows = 12
    terminal_content_width = 600
    rendered_terminal_width = 600
    terminal_screen = pyte.HistoryScreen(
        terminal_columns,
        terminal_rows,
        history=5000,
    )
    terminal_stream = pyte.Stream(terminal_screen)
    pressed_modifiers: set[str] = set()
    terminal_height = 250
    pending_drag_height = 250.0
    terminal_is_resizing = False
    terminal_diagnostic_document_id: int | None = None
    terminal_diagnostic_targets: dict[str, tuple[int, int, int]] = {}
    workspace_height = 0
    terminal_has_focus = True
    terminal_refocus_pending = False
    rendered_history_count = -1
    rendered_history_ids: tuple[int, ...] = ()
    terminal_row_controls: list[ft.Text] = []
    terminal_app_output_lines: list[tuple[object, str]] = []
    terminal_app_output_controls: list[ft.Text] = []
    terminal_app_output_anchors: list[object] = []
    terminal_app_output_dirty = False
    terminal_selections: dict[int, str] = {}
    terminal_resize_handle: asyncio.TimerHandle | None = None
    pending_terminal_size: tuple[int, int, float] | None = None
    editor_scroll_offset = 0.0
    editor_viewport_height = 0.0
    editor_horizontal_scroll_offset = 0.0
    editor_horizontal_viewport_width = 800.0
    editor_text_content_width = 800.0
    editor_line_height = 18

    def actualizar_pagina_seguro(*controles):
        if app_cerrando:
            return
        try:
            page.update(*controles)
        except RuntimeError:
            pass
        except Exception:
            pass

    def actualizar_control_seguro(control):
        if app_cerrando or control is None:
            return
        try:
            control.update()
        except RuntimeError:
            pass
        except Exception:
            pass

    def devolver_foco_al_editor_si_activo(_=None):
        if editor_has_focus and not search_bar.visible and not app_cerrando:
            try:
                page.run_task(editor.focus)
            except RuntimeError:
                pass

    def configurar_sin_foco(control):
        """
        Configura can_request_focus=False en el control y evita que la tecla Tab
        robe el foco cuando el usuario está escribiendo en el editor.
        """
        if control is None:
            return control
        try:
            control.can_request_focus = False
        except Exception:
            pass
        if hasattr(control, "autofocus"):
            try:
                control.autofocus = False
            except Exception:
                pass
        if hasattr(control, "on_focus") and getattr(control, "on_focus", None) is None:
            try:
                control.on_focus = devolver_foco_al_editor_si_activo
            except Exception:
                pass
        return control

    file_picker = ft.FilePicker()
    page.services.append(file_picker)
    terminal_clipboard = ft.Clipboard()
    page.services.append(terminal_clipboard)

    status_text = ft.Text(
        "Listo",
        size=12,
        color=MUTED,
        font_family="Segoe UI",
    )
    tabs_bar = ft.Row(
        controls=[],
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )
    language_label = ft.Text("SQL", size=11, color=MUTED)
    root_name_label = ft.Text(
        root_directory.name,
        size=12,
        color=MUTED,
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS,
    )
    line_numbers = ft.Column(
        controls=[
            ft.Container(
                content=ft.Text(
                    "1",
                    size=14,
                    color="#61738c",
                    font_family="Consolas",
                    style=ft.TextStyle(height=editor_line_height / 14),
                    text_align=ft.TextAlign.RIGHT,
                    selectable=False,
                ),
                height=editor_line_height,
                alignment=ft.Alignment.CENTER_RIGHT,
            )
        ],
        spacing=0,
        horizontal_alignment=ft.CrossAxisAlignment.END,
    )
    cursor_position_label = ft.Text("Ln 1, Col 1", size=12, color=MUTED)
    editor = ft.TextField(
        value="",
        multiline=True,
        min_lines=1,
        max_lines=2,
        width=editor_text_content_width,
        expand=False,
        border=ft.NoInputBorder(),
        bgcolor="transparent",
        color=TEXT,
        cursor_color=ACCENT,
        selection_color="#315275",
        content_padding=ft.Padding.only(left=8, top=10, right=12, bottom=12),
        text_style=ft.TextStyle(
            font_family="Consolas",
            size=14,
            height=editor_line_height / 14,
            color=TEXT,
        ),
        strut_style=ft.StrutStyle(
            font_family="Consolas",
            size=14,
            height=editor_line_height / 14,
            force_strut_height=True,
        ),
        on_change=None,
    )

    def al_desplazarse_editor(event):
        nonlocal editor_scroll_offset
        editor_scroll_offset = event.pixels

    def al_redimensionar_editor(event):
        nonlocal editor_viewport_height
        editor_viewport_height = event.height

    def actualizar_desplazamiento_horizontal_editor(event):
        nonlocal editor_horizontal_scroll_offset
        editor_horizontal_scroll_offset = event.pixels

    def actualizar_ancho_editor(contents: str):
        nonlocal editor_text_content_width
        longest_line = max(
            (len(line.expandtabs(4)) for line in contents.splitlines()),
            default=0,
        )
        required_width = max(
            editor_horizontal_viewport_width,
            longest_line * 8.5 + 28,
        )
        if abs(required_width - editor_text_content_width) < 1:
            return
        editor_text_content_width = required_width
        editor_text_view.width = required_width
        editor.width = required_width
        editor_preview.width = required_width
        editor_preview_container.width = required_width

    def redimensionar_vista_horizontal_editor(event):
        nonlocal editor_horizontal_viewport_width
        if app_cerrando:
            return
        if abs(event.width - editor_horizontal_viewport_width) < 1:
            return
        editor_horizontal_viewport_width = event.width
        actualizar_ancho_editor(editor.value or "")
        actualizar_control_seguro(editor_text_view)
        actualizar_control_seguro(editor_horizontal_scroll)

    editor_preview = ft.Text(
        value="",
        size=14,
        font_family="Consolas",
        no_wrap=True,
        style=ft.TextStyle(
            height=editor_line_height / 14,
            color=TEXT,
        ),
        width=editor_text_content_width,
    )
    editor_preview_container = ft.Container(
        content=editor_preview,
        padding=ft.Padding.only(left=8, top=10, right=12, bottom=12),
        width=editor_text_content_width,
        ignore_interactions=True,
        visible=False,
    )
    editor_text_view = ft.Stack(
        controls=[
            editor_preview_container,
            editor,
        ],
        fit=ft.StackFit.EXPAND,
        width=editor_text_content_width,
    )
    editor_horizontal_scroll = ft.Row(
        controls=[editor_text_view],
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
        on_scroll=lambda event: actualizar_desplazamiento_horizontal_editor(event),
        on_size_change=lambda event: redimensionar_vista_horizontal_editor(event),
    )
    editor_content = ft.Row(
        [
            ft.Container(
                content=line_numbers,
                width=42,
                padding=ft.Padding.only(left=0, top=6, right=8),
                alignment=ft.Alignment.TOP_RIGHT,
            ),
            ft.Container(
                content=editor_horizontal_scroll,
                expand=True,
                bgcolor="transparent",
            ),
        ],
        spacing=0,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    editor_scroll = ft.Column(
        [editor_content],
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        on_scroll=al_desplazarse_editor,
        on_size_change=al_redimensionar_editor,
    )
    terminal_output = ft.ListView(
        controls=[],
        key="terminal-output",
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
        auto_scroll=True,
        auto_scroll_animation=0,
        expand=True,
        build_controls_on_demand=True,
        item_extent=18,
        width=terminal_content_width,
    )
    explorer_body = ft.Column(
        spacing=1,
        scroll=ft.ScrollMode.AUTO,
        width=246,
    )
    explorer_horizontal_scroll = ft.Row(
        controls=[explorer_body],
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    def establecer_estado(message: str, color: str = MUTED):
        if app_cerrando:
            return
        status_text.value = message
        status_text.color = color
        actualizar_pagina_seguro()

    def sincronizar_documento_activo():
        if active_document is not None:
            active_document["content"] = editor.value if editor.value is not None else ""
            active_document["saved_content"] = saved_content

    def dibujar_pestanas():
        tab_controls = []
        for document in documents:
            document_id = document["id"]
            path = document["path"]
            filename = path.name if path is not None else document["name"]
            is_dirty = document["content"] != document["saved_content"]
            close_btn = configurar_sin_foco(
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_size=15,
                    icon_color=MUTED,
                    tooltip="Cerrar archivo",
                    on_click=lambda _, selected_id=document_id: cerrar_documento(
                        selected_id
                    ),
                )
            )
            tab_controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text(
                                f"{filename}{'  ●' if is_dirty else ''}",
                                size=13,
                                color=TEXT if document is active_document else MUTED,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            close_btn,
                        ],
                        spacing=4,
                        tight=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.Padding.only(left=10, right=5, top=1, bottom=1),
                    bgcolor="#202f43" if document is active_document else "transparent",
                    border=ft.Border.only(
                        bottom=ft.BorderSide(
                            2,
                            ACCENT if document is active_document else "transparent",
                        )
                    ),
                    on_click=lambda _, selected_id=document_id: activar_documento(
                        selected_id
                    ),
                    ink=True,
                )
            )
        tabs_bar.controls = tab_controls

    def actualizar_metadatos_editor():
        sincronizar_documento_activo()
        language_label.value = (
            active_path.suffix[1:].upper()
            if active_path and active_path.suffix
            else "SQL"
        )
        contents = editor.value if editor.value is not None else ""
        line_count = contents.count("\n") + 1
        actualizar_ancho_editor(contents)
        editor.max_lines = line_count + 2
        line_numbers.controls = [
            ft.Container(
                content=ft.Text(
                    str(number),
                    size=14,
                    color="#61738c",
                    font_family="Consolas",
                    style=ft.TextStyle(height=editor_line_height / 14),
                    text_align=ft.TextAlign.RIGHT,
                    selectable=False,
                ),
                height=editor_line_height,
                alignment=ft.Alignment.CENTER_RIGHT,
            )
            for number in range(1, line_count + 1)
        ]
        content_height = (line_count + 2) * editor_line_height + 22
        line_numbers.height = content_height
        editor.height = content_height
        editor_content.height = content_height
        editor_text_view.height = content_height
        if search_bar.visible:
            actualizar_vista_busqueda()
        actualizar_posicion_cursor(editor.selection)
        dibujar_pestanas()

    def actualizar_posicion_cursor(selection=None):
        contents = editor.value or ""
        offset = selection.extent_offset if selection is not None else 0
        offset = max(0, min(offset, len(contents)))
        preceding_text = contents[:offset]
        line = preceding_text.count("\n") + 1
        column = len(preceding_text) - preceding_text.rfind("\n")
        cursor_position_label.value = f"Ln {line}, Col {column}"

    async def revelar_posicion_editor(offset: int):
        if app_cerrando:
            return
        contents = editor.value or ""
        offset = max(0, min(offset, len(contents)))
        preceding_text = contents[:offset]
        line = preceding_text.count("\n") + 1
        line_top = (line - 1) * editor_line_height + 10
        try:
            if editor_viewport_height and line_top < editor_scroll_offset:
                await editor_scroll.scroll_to(offset=max(0, line_top), duration=120)
            elif (
                editor_viewport_height
                and line_top + editor_line_height
                > editor_scroll_offset + editor_viewport_height
            ):
                target = line_top - editor_viewport_height + editor_line_height
                await editor_scroll.scroll_to(offset=max(0, target), duration=120)
            line_start = preceding_text.rfind("\n") + 1
            column = len(preceding_text[line_start:].expandtabs(4))
            caret_x = column * 8.5 + 8
            if caret_x < editor_horizontal_scroll_offset:
                await editor_horizontal_scroll.scroll_to(
                    offset=max(0, caret_x - 8),
                    duration=120,
                )
            elif (
                editor_horizontal_viewport_width
                and caret_x
                > editor_horizontal_scroll_offset + editor_horizontal_viewport_width - 24
            ):
                target = (
                    caret_x
                    - editor_horizontal_viewport_width
                    + 24
                )
                await editor_horizontal_scroll.scroll_to(
                    offset=max(0, target),
                    duration=120,
                )
        except RuntimeError:
            pass

    async def ir_a_posicion_error(
        line: int,
        column: int,
        document_id: int | None,
    ):
        if app_cerrando or document_id is None:
            return
        document = next(
            (item for item in documents if item["id"] == document_id),
            None,
        )
        if document is None:
            return
        if active_document is not document:
            activar_documento(document_id)

        contents = editor.value or ""
        offset = 0
        for _ in range(max(0, line - 1)):
            newline = contents.find("\n", offset)
            if newline < 0:
                offset = len(contents)
                break
            offset = newline + 1
        line_end = contents.find("\n", offset)
        if line_end < 0:
            line_end = len(contents)
        offset = min(offset + max(0, column - 1), line_end)
        editor.selection = ft.TextSelection(offset, offset)
        actualizar_posicion_cursor(editor.selection)
        try:
            await editor.focus()
            await revelar_posicion_editor(offset)
        except RuntimeError:
            return
        actualizar_pagina_seguro(editor, cursor_position_label)

    async def al_cambiar_seleccion_editor(event):
        if app_cerrando:
            return
        actualizar_posicion_cursor(event.selection)
        await revelar_posicion_editor(event.selection.extent_offset)
        actualizar_pagina_seguro(cursor_position_label)

    search_matches: list[tuple[int, int]] = []
    active_search_match = -1
    search_status = ft.Text("0 coincidencias", size=11, color=MUTED)

    def actualizar_vista_busqueda():
        contents = editor.value or ""
        spans = []
        cursor = 0
        for index, (start, end) in enumerate(search_matches):
            if start > cursor:
                spans.append(
                    ft.TextSpan(
                        text=contents[cursor:start],
                        style=ft.TextStyle(
                            font_family="Consolas",
                            size=14,
                            height=editor_line_height / 14,
                            color=TEXT,
                        ),
                    )
                )
            spans.append(
                ft.TextSpan(
                    text=contents[start:end],
                    style=ft.TextStyle(
                        font_family="Consolas",
                        size=14,
                        height=editor_line_height / 14,
                        color=TEXT,
                        bgcolor="#b78b2c" if index == active_search_match else "#634f28",
                    ),
                )
            )
            cursor = end
        if cursor < len(contents):
            spans.append(
                ft.TextSpan(
                    text=contents[cursor:],
                    style=ft.TextStyle(
                        font_family="Consolas",
                        size=14,
                        height=editor_line_height / 14,
                        color=TEXT,
                    ),
                )
            )
        editor_preview.value = ""
        editor_preview.spans = spans or None
        if not spans:
            editor_preview.value = contents
        editor_preview_container.visible = search_bar.visible

    async def seleccionar_coincidencia(index: int):
        nonlocal active_search_match
        if not search_matches or app_cerrando:
            return
        active_search_match = index % len(search_matches)
        start, end = search_matches[active_search_match]
        editor.selection = ft.TextSelection(start, end)
        search_status.value = (
            f"{active_search_match + 1} de {len(search_matches)}"
        )
        actualizar_vista_busqueda()
        await revelar_posicion_editor(start)
        actualizar_pagina_seguro(editor_preview, editor_preview_container, search_status)

    async def actualizar_busqueda(_=None):
        nonlocal search_matches, active_search_match
        if app_cerrando:
            return
        query = search_field.value or ""
        contents = editor.value or ""
        search_matches = (
            [
                (match.start(), match.end())
                for match in re.finditer(re.escape(query), contents, re.IGNORECASE)
            ]
            if query
            else []
        )
        if search_matches:
            await seleccionar_coincidencia(0)
        else:
            active_search_match = -1
            if editor.selection and not editor.selection.is_collapsed:
                editor.selection = ft.TextSelection(
                    editor.selection.extent_offset,
                    editor.selection.extent_offset,
                )
            search_status.value = "0 coincidencias"
            actualizar_vista_busqueda()
            actualizar_pagina_seguro(editor_preview, editor_preview_container, search_status)

    async def abrir_busqueda(_=None):
        nonlocal editor_has_focus
        if app_cerrando:
            return
        editor_has_focus = False
        selected_text = ""
        if editor.selection and not editor.selection.is_collapsed:
            start = editor.selection.start
            end = editor.selection.end
            selected_text = (editor.value or "")[start:end]
        search_field.value = selected_text
        editor.color = ft.Colors.TRANSPARENT
        editor.text_style = ft.TextStyle(
            font_family="Consolas",
            size=14,
            height=editor_line_height / 14,
            color=ft.Colors.TRANSPARENT,
        )
        editor.selection_color = ft.Colors.TRANSPARENT
        search_bar.visible = True
        actualizar_vista_busqueda()
        actualizar_pagina_seguro()
        await actualizar_busqueda()
        try:
            await search_field.focus()
        except RuntimeError:
            pass

    async def buscar_siguiente(_=None):
        if search_matches:
            await seleccionar_coincidencia(active_search_match + 1)

    async def buscar_anterior(_=None):
        if search_matches:
            await seleccionar_coincidencia(active_search_match - 1)

    async def cerrar_busqueda(_=None):
        nonlocal editor_has_focus
        if app_cerrando:
            return
        search_bar.visible = False
        editor_preview_container.visible = False
        editor.color = TEXT
        editor.text_style = ft.TextStyle(
            font_family="Consolas",
            size=14,
            height=editor_line_height / 14,
            color=TEXT,
        )
        editor.selection_color = "#315275"
        editor_has_focus = True
        try:
            await editor.focus()
        except RuntimeError:
            pass
        actualizar_pagina_seguro(editor, editor_preview_container, search_bar)

    search_field = ft.TextField(
        hint_text="Buscar en el archivo",
        height=38,
        content_padding=ft.Padding.symmetric(horizontal=10, vertical=6),
        border=crear_borde_campo(BORDER, ACCENT),
        text_size=13,
        expand=True,
        can_request_focus=True,
        on_change=actualizar_busqueda,
        on_submit=buscar_siguiente,
    )
    search_bar = ft.Container(
        content=ft.Row(
            [
                search_field,
                search_status,
                configurar_sin_foco(
                    ft.IconButton(
                        icon=ft.Icons.KEYBOARD_ARROW_UP,
                        tooltip="Coincidencia anterior",
                        icon_color=MUTED,
                        on_click=buscar_anterior,
                    )
                ),
                configurar_sin_foco(
                    ft.IconButton(
                        icon=ft.Icons.KEYBOARD_ARROW_DOWN,
                        tooltip="Coincidencia siguiente",
                        icon_color=MUTED,
                        on_click=buscar_siguiente,
                    )
                ),
                configurar_sin_foco(
                    ft.IconButton(
                        icon=ft.Icons.CLOSE,
                        tooltip="Cerrar búsqueda",
                        icon_color=MUTED,
                        on_click=cerrar_busqueda,
                    )
                ),
            ],
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding.symmetric(horizontal=8, vertical=5),
        bgcolor="#151e2b",
        visible=False,
    )

    def al_pulsar_tecla_pagina(event):
        if app_cerrando:
            return
        key_upper = (event.key or "").upper()
        if key_upper == "ESCAPE":
            if active_context_menu_overlay is not None:
                cerrar_menu_contextual()
                return
            if renaming_path is not None:
                cancelar_renombrado_en_linea()
                return
            if search_bar.visible:
                page.run_task(cerrar_busqueda)
                return
        if event.ctrl and key_upper == "F":
            cerrar_menu_contextual()
            page.run_task(abrir_busqueda)
        elif event.ctrl and key_upper == "S":
            cerrar_menu_contextual()
            page.run_task(guardar_archivo, None, True)
        elif key_upper == "TAB" and editor_has_focus and not search_bar.visible:
            # Evita que presionar Tab por accidente saque al usuario del editor
            try:
                page.run_task(editor.focus)
            except RuntimeError:
                pass

    page.on_keyboard_event = al_pulsar_tecla_pagina

    terminal_colors = {
        "black": "#101722",
        "red": "#ff5f56",
        "green": "#56d68b",
        "brown": "#f0b45b",
        "blue": "#4da3ff",
        "magenta": "#c084fc",
        "cyan": "#56d9e8",
        "white": "#d5deeb",
        "brightblack": "#687990",
        "brightred": "#ff7c84",
        "brightgreen": "#80f5a1",
        "brightbrown": "#ffd27a",
        "brightblue": "#82bcff",
        "brightmagenta": "#d6a5ff",
        "brightcyan": "#82eff5",
        "brightwhite": "#ffffff",
        "default": "#d5deeb",
    }

    def obtener_color_terminal(color: str, fallback: str) -> str:
        if color == "default":
            return fallback
        if color.startswith("#"):
            return color
        return terminal_colors.get(color, fallback)

    def dibujar_linea_terminal(row, cursor_x: int | None = None):
        spans = []
        last_column = max(row, default=-1) + 1
        while last_column and row[last_column - 1].data == " ":
            last_column -= 1
        if cursor_x is not None and not terminal_screen.cursor.hidden:
            last_column = max(last_column, cursor_x + 1)

        run_text = ""
        run_style = None
        for x in range(last_column):
            cell = row[x]
            foreground = cell.bg if cell.reverse else cell.fg
            background = cell.fg if cell.reverse else cell.bg
            if cursor_x == x and not terminal_screen.cursor.hidden:
                if foreground == "default" and background == "default":
                    foreground, background = "#101722", "#d5deeb"
                else:
                    foreground, background = background, foreground
            style_key = (
                foreground,
                background,
                cell.bold,
                cell.italics,
                cell.underscore,
            )
            if style_key != run_style:
                if run_text:
                    spans.append(
                        ft.TextSpan(
                            text=run_text,
                            style=convertir_estilo_texto(run_style),
                        )
                    )
                run_text = cell.data
                run_style = style_key
            else:
                run_text += cell.data
        if run_text:
            spans.append(
                ft.TextSpan(
                    text=run_text,
                    style=convertir_estilo_texto(run_style),
                )
            )
        return spans

    def al_cambiar_seleccion_terminal(event):
        control_id = id(event.control)
        if event.selected_text:
            terminal_selections[control_id] = event.selected_text
        else:
            terminal_selections.pop(control_id, None)

    def crear_linea_terminal(
        row,
        cursor_x: int | None = None,
        *,
        key: str | None = None,
    ):
        row_text = "".join(
            row[x].data for x in range(max(row, default=-1) + 1)
        ).rstrip()
        link_match = re.search(r"(\[[^\]\r\n]+:\d+(?::\d+)?\])", row_text)
        diagnostic_link = link_match.group(1) if link_match else None
        document_id = (
            terminal_diagnostic_targets.get(diagnostic_link)
            if diagnostic_link
            else None
        )

        def abrir_diagnostico(_=None):
            if app_cerrando or document_id is None:
                return
            try:
                page.run_task(
                    ir_a_posicion_error,
                    *document_id,
                )
            except RuntimeError:
                return

        spans = dibujar_linea_terminal(row, cursor_x)
        if link_match and document_id is not None:
            link_start, link_end = link_match.span()
            span_offset = 0
            linked_spans = []
            for span in spans:
                span_text = span.text or ""
                span_end = span_offset + len(span_text)
                overlap_start = max(link_start, span_offset)
                overlap_end = min(link_end, span_end)
                if overlap_start >= overlap_end:
                    linked_spans.append(span)
                else:
                    prefix = span_text[: overlap_start - span_offset]
                    link_text = span_text[
                        overlap_start - span_offset : overlap_end - span_offset
                    ]
                    suffix = span_text[overlap_end - span_offset :]
                    if prefix:
                        linked_spans.append(
                            ft.TextSpan(text=prefix, style=span.style)
                        )
                    linked_spans.append(
                        ft.TextSpan(
                            text=link_text,
                            style=ft.TextStyle(
                                color=BLUE,
                                decoration=ft.TextDecoration.UNDERLINE,
                            ),
                            on_click=abrir_diagnostico,
                        )
                    )
                    if suffix:
                        linked_spans.append(
                            ft.TextSpan(text=suffix, style=span.style)
                        )
                span_offset = span_end
            spans = linked_spans

        return ft.Text(
            spans=spans,
            size=13,
            font_family="Consolas",
            color="#d5deeb",
            selectable=True,
            show_selection_cursor=True,
            no_wrap=True,
            max_lines=1,
            width=terminal_content_width,
            key=key,
            tooltip=diagnostic_link,
            on_tap=enfocar_terminal if diagnostic_link is None else None,
            on_selection_change=al_cambiar_seleccion_terminal,
        )

    def reconstruir_filas_terminal(history_rows):
        terminal_row_controls[:] = [
            crear_linea_terminal(row, key=f"terminal-history-{id(row)}")
            for row in history_rows
        ]
        terminal_row_controls.extend(
            crear_linea_terminal(
                terminal_screen.buffer[y],
                terminal_screen.cursor.x if y == terminal_screen.cursor.y else None,
                key=f"terminal-screen-{y}",
            )
            for y in range(terminal_screen.lines)
        )
        current_control_ids = {
            id(control)
            for control in (*terminal_row_controls, *terminal_app_output_controls)
        }
        for control_id in terminal_selections.keys() - current_control_ids:
            del terminal_selections[control_id]

    def reconstruir_salida_app_terminal():
        terminal_app_output_controls.clear()
        terminal_app_output_anchors.clear()
        width = max(1, terminal_columns)
        for index, (anchor, line) in enumerate(terminal_app_output_lines):
            wrapped_lines = textwrap.wrap(
                line,
                width=width,
                replace_whitespace=False,
                drop_whitespace=False,
            ) or [""]
            for part_index, wrapped_line in enumerate(wrapped_lines):
                row = pyte.screens.StaticDefaultDict(terminal_screen.default_char)
                for x, character in enumerate(wrapped_line[:width]):
                    row[x] = terminal_screen.default_char._replace(data=character)
                terminal_app_output_controls.append(
                    crear_linea_terminal(
                        row,
                        key=f"terminal-app-{index}-{part_index}",
                    )
                )
                terminal_app_output_anchors.append(anchor)

    def dibujar_terminal():
        nonlocal rendered_history_count, rendered_history_ids
        nonlocal terminal_refocus_pending
        nonlocal terminal_app_output_dirty
        if app_cerrando:
            return
        history_rows = list(terminal_screen.history.top)
        history_count = len(history_rows)
        history_ids = tuple(id(row) for row in history_rows)
        previous_history_ids = rendered_history_ids
        expected_row_count = history_count + terminal_screen.lines
        rebuild = rendered_history_count < 0
        if not rebuild and history_ids != rendered_history_ids:
            previous_history_controls = terminal_row_controls[:rendered_history_count]
            if (
                history_count > rendered_history_count
                and history_ids[:rendered_history_count] == rendered_history_ids
            ):
                history_controls = [
                    *previous_history_controls,
                    *(
                        crear_linea_terminal(
                            row,
                            key=f"terminal-history-{id(row)}",
                        )
                        for row in history_rows[rendered_history_count:]
                    ),
                ]
            elif history_count == rendered_history_count and rendered_history_ids:
                try:
                    last_retained = history_ids.index(rendered_history_ids[-1])
                except (ValueError, IndexError):
                    rebuild = True
                else:
                    dropped_count = rendered_history_count - last_retained - 1
                    history_controls = [
                        *previous_history_controls[dropped_count:],
                        *(
                            crear_linea_terminal(
                                row,
                                key=f"terminal-history-{id(row)}",
                            )
                            for row in history_rows[last_retained + 1 :]
                        ),
                    ]
            else:
                rebuild = True

            if not rebuild and len(history_controls) == history_count:
                terminal_row_controls[:] = [
                    *history_controls,
                    *(
                        crear_linea_terminal(
                            terminal_screen.buffer[y],
                            terminal_screen.cursor.x
                            if y == terminal_screen.cursor.y
                            else None,
                            key=f"terminal-screen-{y}",
                        )
                        for y in range(terminal_screen.lines)
                    ),
                ]
            else:
                rebuild = True

        if rebuild:
            reconstruir_filas_terminal(history_rows)
        if len(terminal_row_controls) != expected_row_count:
            rebuild = True
            reconstruir_filas_terminal(history_rows)

        current_control_ids = {
            id(control)
            for control in (*terminal_row_controls, *terminal_app_output_controls)
        }
        for control_id in terminal_selections.keys() - current_control_ids:
            del terminal_selections[control_id]

        changed_rows = terminal_screen.dirty
        if not rebuild and history_ids == previous_history_ids:
            for y in changed_rows:
                if 0 <= y < terminal_screen.lines:
                    terminal_row_controls[history_count + y] = crear_linea_terminal(
                        terminal_screen.buffer[y],
                        terminal_screen.cursor.x
                        if y == terminal_screen.cursor.y
                        else None,
                        key=f"terminal-screen-{y}",
                    )

        rendered_history_count = history_count
        rendered_history_ids = history_ids

        if terminal_app_output_dirty:
            reconstruir_salida_app_terminal()

        if (
            rebuild
            or history_ids != previous_history_ids
            or changed_rows
            or terminal_app_output_dirty
        ):
            display_rows = [
                *history_rows,
                *(terminal_screen.buffer[y] for y in range(terminal_screen.lines)),
            ]
            row_indexes = {id(row): index for index, row in enumerate(display_rows)}
            cursor_index = min(
                history_count + terminal_screen.cursor.y,
                len(terminal_row_controls),
            )
            app_controls_by_row: dict[int, list[ft.Text]] = {}
            for anchor, control in zip(
                terminal_app_output_anchors,
                terminal_app_output_controls,
            ):
                row_index = row_indexes.get(id(anchor), cursor_index)
                app_controls_by_row.setdefault(row_index, []).append(control)
            display_controls = []
            for index, control in enumerate(terminal_row_controls):
                display_controls.extend(app_controls_by_row.get(index, ()))
                display_controls.append(control)
            terminal_output.controls = display_controls
            terminal_app_output_dirty = False
            actualizar_control_seguro(terminal_output)
            if terminal_refocus_pending and terminal_has_focus and not app_cerrando:
                terminal_refocus_pending = False
                try:
                    page.run_task(terminal_listener.focus)
                except RuntimeError:
                    pass
        terminal_screen.dirty.clear()

    def escribir_salida_terminal(texto: str):
        nonlocal terminal_app_output_dirty
        if app_cerrando:
            return
        normalized = texto.replace("\r\n", "\n").replace("\r", "\n")
        anchor = terminal_screen.buffer[terminal_screen.cursor.y]
        terminal_app_output_lines.extend(
            (anchor, line) for line in ["", *normalized.split("\n"), ""]
        )
        if len(terminal_app_output_lines) > terminal_screen.history.size:
            del terminal_app_output_lines[
                : len(terminal_app_output_lines) - terminal_screen.history.size
            ]
        terminal_app_output_dirty = True
        dibujar_terminal()

    def convertir_estilo_texto(style):
        foreground, background, bold, italics, underscore = style
        return ft.TextStyle(
            color=obtener_color_terminal(foreground, "#d5deeb"),
            bgcolor=obtener_color_terminal(background, "transparent"),
            weight=ft.FontWeight.W_700 if bold else None,
            italic=italics,
            decoration=(
                ft.TextDecoration.UNDERLINE if underscore else ft.TextDecoration.NONE
            ),
        )

    def informar_error_terminal(message: str):
        if app_cerrando:
            return
        status_text.value = message
        status_text.color = "#ff7c84"
        try:
            escribir_salida_terminal(message)
            actualizar_pagina_seguro()
        except RuntimeError as error:
            if app_cerrando or "destroyed session" in str(error).lower():
                detener_powershell()
                return
            raise

    def leer_salida_terminal(
        process: PtyProcess,
        output_queue: queue.Queue[str | Exception | None],
    ):
        while not app_cerrando and process.isalive():
            try:
                chunk = process.read()
                if app_cerrando:
                    break
                output_queue.put(chunk)
            except (EOFError, ConnectionResetError):
                break
            except (WinptyError, OSError) as error:
                if (
                    app_cerrando
                    or isinstance(error, ConnectionResetError)
                    or getattr(error, "winerror", None) == 10054
                    or "10054" in str(error)
                ):
                    break
                output_queue.put(error)
                break
        output_queue.put(None)

    async def procesar_salida_terminal(
        process: PtyProcess,
        output_queue: queue.Queue[str | Exception | None],
    ):
        while not app_cerrando and shell_process is process:
            try:
                output = output_queue.get_nowait()
            except queue.Empty:
                if app_cerrando or not process.isalive():
                    break
                await asyncio.sleep(0.02)
                continue

            chunks = []
            errors = []
            finished = False
            while output is not None:
                if isinstance(output, Exception):
                    errors.append(output)
                else:
                    chunks.append(output)
                try:
                    output = output_queue.get_nowait()
                except queue.Empty:
                    break
            else:
                finished = True

            if app_cerrando:
                break

            if chunks:
                terminal_stream.feed("".join(chunks))
                dibujar_terminal()
            for error in errors:
                if (
                    app_cerrando
                    or not process.isalive()
                    or isinstance(error, ConnectionResetError)
                    or getattr(error, "winerror", None) == 10054
                    or "10054" in str(error)
                ):
                    continue
                informar_error_terminal(f"Error al leer PowerShell: {error}")
            if finished:
                break

        if not app_cerrando and shell_process is process:
            establecer_estado("PowerShell finalizó", "#f0b45b")

    async def iniciar_powershell():
        nonlocal shell_process, terminal_stream
        if app_cerrando:
            return None
        if shell_process and shell_process.isalive():
            return shell_process

        executable = (
            shutil.which("powershell.exe")
            or shutil.which("powershell")
            or shutil.which("pwsh")
        )
        if not executable:
            informar_error_terminal("No se encontró PowerShell en este equipo.")
            return None

        try:
            process = await asyncio.to_thread(
                PtyProcess.spawn,
                [executable, "-NoLogo", "-NoProfile", "-NoExit"],
                cwd=str(root_directory),
                dimensions=(terminal_rows, terminal_columns),
            )
        except (OSError, WinptyError) as error:
            if not app_cerrando:
                informar_error_terminal(f"No se pudo iniciar PowerShell: {error}")
            return None

        if app_cerrando:
            try:
                process.close(force=True)
            except Exception:
                pass
            return None

        shell_process = process
        terminal_screen.reset()
        terminal_stream = pyte.Stream(terminal_screen)
        dibujar_terminal()
        output_queue = queue.Queue()
        threading.Thread(
            target=leer_salida_terminal,
            args=(process, output_queue),
            name="powershell-terminal-reader",
            daemon=True,
        ).start()
        establecer_estado(f"PowerShell activo · {root_directory}", "#56d68b")
        try:
            page.run_task(procesar_salida_terminal, process, output_queue)
        except RuntimeError:
            pass
        return process

    def enviar_entrada_terminal(text: str):
        if app_cerrando:
            return
        if not shell_process or not shell_process.isalive():
            establecer_estado("PowerShell no está activo", "#f0b45b")
            return
        try:
            shell_process.write(text)
        except (EOFError, OSError, WinptyError) as error:
            if not app_cerrando:
                informar_error_terminal(f"No se pudo enviar la tecla: {error}")

    special_keys = {
        "enter": "\r",
        "tab": "\t",
        "backspace": "\x7f",
        "escape": "\x1b",
        "arrowup": "\x1b[A",
        "arrowdown": "\x1b[B",
        "arrowright": "\x1b[C",
        "arrowleft": "\x1b[D",
        "home": "\x1b[H",
        "end": "\x1b[F",
        "delete": "\x1b[3~",
        "insert": "\x1b[2~",
        "pageup": "\x1b[5~",
        "pagedown": "\x1b[6~",
        "f1": "\x1bOP",
        "f2": "\x1bOQ",
        "f3": "\x1bOR",
        "f4": "\x1bOS",
        "f5": "\x1b[15~",
        "f6": "\x1b[17~",
        "f7": "\x1b[18~",
        "f8": "\x1b[19~",
        "f9": "\x1b[20~",
        "f10": "\x1b[21~",
        "f11": "\x1b[23~",
        "f12": "\x1b[24~",
    }
    shifted_characters = dict(
        zip("1234567890-=[]\\;',./`", '!@#$%^&*()_+{}|:"<>?~')
    )

    def normalizar_tecla(key: str) -> str:
        return key.casefold().replace(" ", "")

    def actualizar_modificadores_pulsados(key: str, pressed: bool):
        normalized = normalizar_tecla(key)
        for modifier in ("control", "shift", "alt", "meta"):
            if normalized == modifier or normalized.startswith(modifier):
                if pressed:
                    pressed_modifiers.add(modifier)
                else:
                    pressed_modifiers.discard(modifier)
                return True
        return False

    async def copiar_seleccion_terminal(text: str):
        if app_cerrando:
            return
        copiar_portapapeles_sistema(text)
        try:
            await terminal_clipboard.set(text)
        except Exception:
            pass
        status_text.value = "Texto copiado"
        status_text.color = "#56d68b"
        actualizar_pagina_seguro(status_text)

    def manejar_tecla_terminal(key: str):
        nonlocal terminal_refocus_pending
        if app_cerrando:
            return
        if key in {" ", "Space", "Spacebar"}:
            key = " "
        normalized = normalizar_tecla(key)
        if key == " " or normalized in {"space", "spacebar"}:
            key = " "
        elif normalized in {"enter", "numpadenter"}:
            key = "enter"
        elif normalized in {"arrowup", "arrowdown", "arrowleft", "arrowright"}:
            key = normalized
        else:
            key = normalized

        if "control" in pressed_modifiers and key == "c":
            selected_text = "\n".join(
                terminal_selections[id(control)]
                for control in terminal_output.controls
                if id(control) in terminal_selections
            )
            if selected_text:
                page.run_task(copiar_seleccion_terminal, selected_text)
                return

        if "control" in pressed_modifiers and key in {
            "arrowleft",
            "arrowright",
            "arrowup",
            "arrowdown",
            "home",
            "end",
        }:
            sequence = {
                "arrowleft": "D",
                "arrowright": "C",
                "arrowup": "A",
                "arrowdown": "B",
                "home": "H",
                "end": "F",
            }[key]
            enviar_entrada_terminal(f"\x1b[1;5{sequence}")
            return
        if "shift" in pressed_modifiers and key == "tab":
            enviar_entrada_terminal("\x1b[Z")
            return
        if key in special_keys:
            if key in {"enter", "tab"} and terminal_has_focus:
                terminal_refocus_pending = True
            enviar_entrada_terminal(special_keys[key])
            return
        if len(key) != 1 or key in pressed_modifiers:
            return

        if "control" in pressed_modifiers and key.isalpha():
            enviar_entrada_terminal(chr(ord(key.upper()) - ord("A") + 1))
            return
        if "alt" in pressed_modifiers:
            enviar_entrada_terminal("\x1b")
        if "shift" in pressed_modifiers:
            key = shifted_characters.get(key, key.upper())
        elif key.isalpha():
            key = key.lower()
        enviar_entrada_terminal(key)

    def al_pulsar_tecla_terminal(event):
        if not actualizar_modificadores_pulsados(event.key, True):
            manejar_tecla_terminal(event.key)

    def al_soltar_tecla_terminal(event):
        actualizar_modificadores_pulsados(event.key, False)

    def aplicar_redimension_terminal():
        nonlocal terminal_columns, terminal_rows, terminal_resize_handle
        nonlocal terminal_content_width, rendered_terminal_width
        nonlocal terminal_app_output_dirty
        terminal_resize_handle = None
        if app_cerrando or pending_terminal_size is None:
            return
        columns, rows, content_width = pending_terminal_size
        dimensions_changed = (columns, rows) != (terminal_columns, terminal_rows)
        width_changed = content_width != rendered_terminal_width
        if not dimensions_changed and not width_changed:
            return

        if dimensions_changed:
            previous_rows = terminal_screen.lines
            previous_cursor_x = terminal_screen.cursor.x
            previous_cursor_y = terminal_screen.cursor.y
            rows_clipped_from_top = max(0, previous_rows - rows)
            preserve_top_rows = (
                rows_clipped_from_top > 0
                and previous_cursor_y < rows_clipped_from_top
            )
            preserved_rows = (
                [
                    dict(terminal_screen.buffer[y])
                    for y in range(min(rows, previous_rows))
                ]
                if preserve_top_rows
                else []
            )
            terminal_columns, terminal_rows = columns, rows
            terminal_screen.resize(lines=rows, columns=columns)
            if preserve_top_rows:
                for y, previous_row in enumerate(preserved_rows):
                    resized_row = pyte.screens.StaticDefaultDict(
                        terminal_screen.default_char
                    )
                    resized_row.update(
                        {
                            x: cell
                            for x, cell in previous_row.items()
                            if x < columns
                        }
                    )
                    terminal_screen.buffer[y] = resized_row
                terminal_screen.cursor.y = min(previous_cursor_y, rows - 1)
            else:
                terminal_screen.cursor.y = max(
                    0,
                    min(previous_cursor_y - rows_clipped_from_top, rows - 1),
                )
            terminal_screen.cursor.x = min(previous_cursor_x, columns)
            terminal_screen.dirty.update(range(rows))
        terminal_content_width = content_width
        rendered_terminal_width = content_width
        terminal_output.width = content_width
        if dimensions_changed or width_changed:
            terminal_app_output_dirty = True
        if width_changed:
            if terminal_row_controls:
                reconstruir_filas_terminal(list(terminal_screen.history.top))

        if dimensions_changed and shell_process and shell_process.isalive():
            try:
                shell_process.setwinsize(rows, columns)
            except (WinptyError, OSError) as error:
                if not app_cerrando:
                    informar_error_terminal(f"No se pudo redimensionar PowerShell: {error}")
        if dimensions_changed or width_changed:
            dibujar_terminal()

    def al_redimensionar_terminal(event):
        nonlocal pending_terminal_size, terminal_resize_handle
        if app_cerrando:
            return
        content_width = max(1, int(event.width) - 24)
        columns = max(20, min(240, int(content_width / 7.8)))
        rows = max(3, min(80, int(event.height / 18)))
        pending_terminal_size = (columns, rows, content_width)

        if terminal_is_resizing:
            return
        if terminal_resize_handle is not None:
            terminal_resize_handle.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            aplicar_redimension_terminal()
        else:
            terminal_resize_handle = loop.call_later(0.12, aplicar_redimension_terminal)

    # =====================================================================
    # 2. REDIMENSIONAMIENTO DIFERIDO HASTA SOLTAR EL MOUSE
    # =====================================================================

    terminal_divider_bar = ft.Container(
        height=2,
        bgcolor=BORDER,
        border_radius=2,
        width=64,
    )
    terminal_divider_label = ft.Text(
        "",
        size=10,
        color=ACCENT,
        font_family="Consolas",
        weight=ft.FontWeight.W_600,
        visible=False,
    )

    def obtener_altura_maxima_terminal():
        return max(130, workspace_height + terminal_height - 130)

    def al_redimensionar_area_trabajo(event):
        nonlocal workspace_height, terminal_height, pending_drag_height
        if app_cerrando:
            return
        workspace_height = event.height
        maximum = obtener_altura_maxima_terminal()
        if terminal_height > maximum:
            terminal_height = maximum
            pending_drag_height = float(terminal_height)
            terminal_panel.height = terminal_height
            actualizar_control_seguro(terminal_panel)

    def iniciar_redimension_terminal(_):
        nonlocal terminal_is_resizing, terminal_resize_handle
        nonlocal pending_drag_height
        if app_cerrando:
            return
        terminal_is_resizing = True
        pending_drag_height = float(terminal_height)
        if terminal_resize_handle is not None:
            terminal_resize_handle.cancel()
            terminal_resize_handle = None
        terminal_divider_bar.bgcolor = ACCENT
        terminal_divider_bar.width = 96
        terminal_divider_label.value = f"{int(pending_drag_height)} px"
        terminal_divider_label.visible = True
        actualizar_control_seguro(terminal_divider)

    def redimensionar_terminal(event):
        """Guarda la altura provisional y actualiza la etiqueta mientras se arrastra."""
        nonlocal pending_drag_height
        if app_cerrando:
            return
        delta = event.primary_delta
        if delta is None and event.local_delta is not None:
            delta = event.local_delta.dy
        if delta is None:
            return
        maximum = obtener_altura_maxima_terminal()
        previous_height = int(pending_drag_height)
        pending_drag_height = max(
            130.0,
            min(float(maximum), pending_drag_height - float(delta)),
        )
        if int(pending_drag_height) != previous_height:
            terminal_divider_label.value = f"{int(pending_drag_height)} px"
            actualizar_control_seguro(terminal_divider_label)

    def finalizar_redimension_terminal(_):
        """
        Aplica la altura final una sola vez; el cambio de tamaño del viewport
        programa la reconfiguración de pyte/PowerShell.
        """
        nonlocal terminal_resize_handle
        nonlocal terminal_is_resizing, terminal_height
        if app_cerrando:
            return
        terminal_is_resizing = False

        if terminal_resize_handle is not None:
            terminal_resize_handle.cancel()
            terminal_resize_handle = None

        terminal_height = int(pending_drag_height)
        terminal_panel.height = terminal_height

        terminal_divider_bar.bgcolor = BORDER
        terminal_divider_bar.width = 64
        terminal_divider_label.visible = False
        terminal_divider_label.value = ""
        actualizar_control_seguro(terminal_panel)
        actualizar_control_seguro(terminal_divider)

    async def enfocar_terminal(_):
        nonlocal terminal_has_focus, terminal_refocus_pending, editor_has_focus
        if app_cerrando:
            return
        pressed_modifiers.clear()
        editor_has_focus = False
        terminal_has_focus = True
        terminal_refocus_pending = False
        try:
            await terminal_listener.focus()
        except RuntimeError:
            return
        status_text.value = "Consola enfocada"
        status_text.color = "#56d68b"
        actualizar_pagina_seguro(status_text)

    def al_enfocar_editor(_):
        nonlocal terminal_has_focus, terminal_refocus_pending, editor_has_focus
        editor_has_focus = True
        terminal_has_focus = False
        terminal_refocus_pending = False

    def detener_powershell(_=None):
        nonlocal app_cerrando, shell_process
        app_cerrando = True
        if terminal_resize_handle is not None:
            try:
                terminal_resize_handle.cancel()
            except Exception:
                pass
        proc = shell_process
        shell_process = None
        if proc is not None:
            try:
                if proc.isalive():
                    proc.close(force=True)
            except Exception:
                pass

    def manejar_evento_ventana(event):
        ev_type = getattr(event, "type", None)
        ev_data = str(getattr(event, "data", "") or "").lower()
        if ev_type == ft.WindowEventType.CLOSE or ev_data == "close":
            detener_powershell(event)

    page.on_close = detener_powershell
    page.on_disconnect = detener_powershell
    page.window.on_event = manejar_evento_ventana

    # =====================================================================
    # 3. MANEJO DE IDENTACIÓN EN VIVO ('>>' y '\t' -> 4 ESPACIOS + ENTER)
    # =====================================================================

    def procesar_identacion_en_vivo(old_text: str, new_text: str) -> tuple[str, int | None]:
        """
        Aplica reemplazo instantáneo de '>>' o '\\t' por 4 espacios ('    ')
        y auto-identación al presionar Enter (heredando sangría previa y sumando
        4 espacios si la línea anterior terminaba en ':').
        Devuelve (texto_transformado, nuevo_offset_cursor_o_None).
        """
        if new_text == old_text:
            return new_text, None

        # Normalizar saltos de línea CRLF si se pegó texto
        if "\r\n" in new_text:
            new_text = new_text.replace("\r\n", "\n")

        # 1. Calcular prefijo y sufijo común entre old_text y new_text para ubicar la edición
        min_len = min(len(old_text), len(new_text))
        prefix_len = 0
        while prefix_len < min_len and old_text[prefix_len] == new_text[prefix_len]:
            prefix_len += 1

        suffix_len = 0
        max_suffix = min(len(old_text) - prefix_len, len(new_text) - prefix_len)
        while (
            suffix_len < max_suffix
            and old_text[len(old_text) - 1 - suffix_len]
            == new_text[len(new_text) - 1 - suffix_len]
        ):
            suffix_len += 1

        inserted = new_text[prefix_len : len(new_text) - suffix_len]
        caret_offset: int | None = None

        # 2. Caso Enter: el usuario acaba de insertar un salto de línea '\n'
        if inserted == "\n" and len(new_text) >= len(old_text):
            line_start = new_text.rfind("\n", 0, prefix_len) + 1
            prev_line = new_text[line_start:prefix_len]
            prev_indent_len = len(prev_line) - len(prev_line.lstrip(" "))
            prev_indent = " " * prev_indent_len
            prev_code = prev_line.split("//", 1)[0].rstrip()

            if prev_code.endswith(":"):
                auto_indent = prev_indent + "    "
            elif prev_indent_len > 0:
                auto_indent = prev_indent
            else:
                auto_indent = ""

            if auto_indent:
                insert_pos = prefix_len + 1
                new_text = (
                    new_text[:insert_pos]
                    + auto_indent
                    + new_text[insert_pos:]
                )
                caret_offset = insert_pos + len(auto_indent)

        # 3. Caso secuencia rápida '>>' o carácter '\t' -> reemplazar en vivo por 4 espacios
        if "\t" in new_text:
            tab_idx = new_text.find("\t")
            count_tabs = new_text.count("\t")
            new_text = new_text.replace("\t", "    ")
            caret_offset = tab_idx + 4 * count_tabs

        if ">>" in new_text:
            seq_idx = new_text.find(">>")
            new_text = new_text.replace(">>", "    ")
            caret_offset = seq_idx + 4

        return new_text, caret_offset

    async def al_cambiar_editor(event):
        nonlocal previous_editor_text
        if app_cerrando:
            return
        raw_contents = (
            event.data
            if isinstance(event.data, str)
            else (editor.value if editor.value is not None else "")
        )
        transformed, new_caret = procesar_identacion_en_vivo(
            previous_editor_text,
            raw_contents,
        )
        previous_editor_text = transformed
        editor.value = transformed
        if new_caret is not None:
            clamped_caret = max(0, min(new_caret, len(transformed)))
            editor.selection = ft.TextSelection(clamped_caret, clamped_caret)
        actualizar_metadatos_editor()
        if search_bar.visible:
            await actualizar_busqueda()
        actualizar_pagina_seguro()

    editor.on_change = al_cambiar_editor
    editor.on_focus = al_enfocar_editor
    editor.on_selection_change = al_cambiar_seleccion_editor

    # =====================================================================
    # 1. SISTEMA UNIFICADO DE MENÚ CONTEXTUAL FLOTANTE (page.overlay)
    #    Y RENOMBRADO EN LÍNEA EN EL EXPLORADOR DE ARCHIVOS
    # =====================================================================

    def cerrar_menu_contextual(_=None):
        nonlocal active_context_menu_overlay
        if active_context_menu_overlay is not None:
            try:
                if active_context_menu_overlay in page.overlay:
                    page.overlay.remove(active_context_menu_overlay)
            except Exception:
                pass
            active_context_menu_overlay = None
            actualizar_pagina_seguro()

    def extraer_coordenadas_clic(event) -> tuple[float, float]:
        """
        Extrae de forma segura las coordenadas globales (x, y) de un TapEvent
        en Flet 1.0+, soportando event.global_position.{x,y} y event.global_{x,y}.
        """
        x_val = None
        y_val = None
        if event is not None:
            global_pos = getattr(event, "global_position", None)
            if global_pos is not None:
                x_val = getattr(global_pos, "x", None)
                y_val = getattr(global_pos, "y", None)
            if x_val is None:
                x_val = getattr(event, "global_x", None)
            if y_val is None:
                y_val = getattr(event, "global_y", None)
            if x_val is None or y_val is None:
                local_pos = getattr(event, "local_position", None)
                if local_pos is not None:
                    if x_val is None:
                        x_val = getattr(local_pos, "x", None)
                    if y_val is None:
                        y_val = getattr(local_pos, "y", None)
            if x_val is None:
                x_val = getattr(event, "local_x", None)
            if y_val is None:
                y_val = getattr(event, "local_y", None)
        try:
            x_float = float(x_val) if x_val is not None else 160.0
        except (TypeError, ValueError):
            x_float = 160.0
        try:
            y_float = float(y_val) if y_val is not None else 160.0
        except (TypeError, ValueError):
            y_float = 160.0
        return x_float, y_float

    def ajustar_coordenadas_menu(
        x: float,
        y: float,
        menu_width: float,
        menu_height: float,
    ) -> tuple[float, float]:
        """
        Ajusta (clamp) las coordenadas (left, top) contra las dimensiones de la
        ventana para que el menú contextual nunca se desborde fuera de la pantalla.
        """
        win_w = getattr(page, "width", None)
        if not win_w:
            win_obj = getattr(page, "window", None)
            win_w = getattr(win_obj, "width", None) if win_obj is not None else None
        win_h = getattr(page, "height", None)
        if not win_h:
            win_obj = getattr(page, "window", None)
            win_h = getattr(win_obj, "height", None) if win_obj is not None else None

        try:
            max_w = float(win_w) if win_w else 1280.0
        except (TypeError, ValueError):
            max_w = 1280.0
        try:
            max_h = float(win_h) if win_h else 800.0
        except (TypeError, ValueError):
            max_h = 800.0

        left = max(8.0, min(float(x), max(8.0, max_w - float(menu_width) - 10.0)))
        top = max(8.0, min(float(y), max(8.0, max_h - float(menu_height) - 10.0)))
        return left, top

    def crear_item_menu_contextual(
        texto: str,
        icono,
        on_click,
        *,
        atajo: str | None = None,
        color_texto: str = TEXT,
        color_icono: str = MUTED,
    ) -> ft.Container:
        row_controls: list[ft.Control] = [
            ft.Icon(icono, size=15, color=color_icono),
            ft.Text(
                texto,
                size=12.5,
                color=color_texto,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
                expand=True,
            ),
        ]
        if atajo:
            row_controls.append(
                ft.Text(
                    atajo,
                    size=11,
                    color=MUTED,
                    font_family="Consolas",
                )
            )

        item_container = ft.Container(
            content=ft.Row(
                row_controls,
                spacing=9,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=31,
            border_radius=4,
            padding=ft.Padding.symmetric(horizontal=10, vertical=5),
            bgcolor="transparent",
            ink=True,
        )

        def al_pasar_mouse(ev):
            is_hover = ev.data is True or str(ev.data).lower() == "true"
            item_container.bgcolor = PANEL_LIGHT if is_hover else "transparent"
            actualizar_control_seguro(item_container)

        async def al_hacer_clic(ev):
            cerrar_menu_contextual()
            if on_click is not None:
                res = on_click(ev)
                if asyncio.iscoroutine(res):
                    await res

        item_container.on_hover = al_pasar_mouse
        item_container.on_click = al_hacer_clic
        return item_container

    def mostrar_menu_contextual_flotante(
        event,
        items: list[ft.Control],
        width: int = 240,
    ):
        nonlocal active_context_menu_overlay
        if app_cerrando:
            return
        if active_context_menu_overlay is not None:
            try:
                if active_context_menu_overlay in page.overlay:
                    page.overlay.remove(active_context_menu_overlay)
            except Exception:
                pass
            active_context_menu_overlay = None

        estimated_height = (
            sum(7 if isinstance(item, ft.Divider) else 32 for item in items) + 12
        )
        raw_x, raw_y = extraer_coordenadas_clic(event)
        left, top = ajustar_coordenadas_menu(raw_x, raw_y, width, estimated_height)

        menu_card = ft.Container(
            content=ft.Column(
                items,
                tight=True,
                spacing=1,
            ),
            width=width,
            left=left,
            top=top,
            bgcolor="#182334",
            border=ft.Border.all(1, "#324663"),
            border_radius=7,
            padding=ft.Padding.symmetric(vertical=4, horizontal=4),
            shadow=ft.BoxShadow(
                blur_radius=16,
                spread_radius=0,
                color="#00000099",
                offset=ft.Offset(0, 6),
            ),
        )

        backdrop = ft.GestureDetector(
            content=ft.Container(
                expand=True,
                bgcolor="transparent",
            ),
            on_tap=cerrar_menu_contextual,
            on_secondary_tap_down=cerrar_menu_contextual,
            expand=True,
        )

        overlay_stack = ft.Stack(
            controls=[backdrop, menu_card],
            expand=True,
        )
        active_context_menu_overlay = overlay_stack
        page.overlay.append(overlay_stack)
        actualizar_pagina_seguro()

    def crear_fila_arbol(
        label: str,
        icon,
        depth: int,
        *,
        color: str = TEXT,
        selected: bool = False,
        on_click=None,
        on_secondary_click=None,
        leading_icon=None,
        horizontal_scroll: bool = False,
    ):
        prefix = (
            ft.Icon(leading_icon, size=16, color=MUTED)
            if leading_icon is not None
            else ft.Container(width=16)
        )
        row = ft.Container(
            content=ft.Row(
                [
                    prefix,
                    ft.Icon(icon, size=16, color=color),
                    ft.Text(
                        label,
                        size=13,
                        color=TEXT if selected else color,
                        max_lines=1,
                        overflow=(
                            ft.TextOverflow.CLIP
                            if horizontal_scroll
                            else ft.TextOverflow.ELLIPSIS
                        ),
                        no_wrap=horizontal_scroll,
                        expand=not horizontal_scroll,
                    ),
                ],
                spacing=7,
                tight=horizontal_scroll,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.only(left=8 + depth * 14, right=7, top=5, bottom=5),
            bgcolor="#294a70" if selected else "transparent",
            border_radius=4,
            on_click=on_click if on_secondary_click is None else None,
            ink=on_click is not None,
            data=(label, depth),
        )
        if on_secondary_click is not None:
            detector = ft.GestureDetector(
                content=row,
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=on_click,
                on_secondary_tap_down=on_secondary_click,
                data=(label, depth),
            )
            return detector
        return row

    def crear_fila_arbol_sintactico(*args, **kwargs):
        return crear_fila_arbol(*args, **kwargs, horizontal_scroll=True)

    def iniciar_renombrado_en_linea(target_path: Path):
        nonlocal renaming_path
        renaming_path = target_path
        dibujar_arbol_directorios()

    def cancelar_renombrado_en_linea(_=None):
        nonlocal renaming_path
        if renaming_path is not None:
            renaming_path = None
            dibujar_arbol_directorios()

    def confirmar_renombrado_en_linea(target_path: Path, nuevo_texto: str | None):
        nonlocal active_path, renaming_path
        if renaming_path != target_path:
            return
        renaming_path = None
        nuevo_nombre = (nuevo_texto or "").strip()
        if not nuevo_nombre or nuevo_nombre == target_path.name:
            dibujar_arbol_directorios()
            return
        if nuevo_nombre in {".", ".."} or any(sep in nuevo_nombre for sep in ("/", "\\")):
            dibujar_arbol_directorios()
            establecer_estado("Nombre de archivo o carpeta inválido.", "#ff7c84")
            return

        nueva_ruta = target_path.with_name(nuevo_nombre).resolve()
        old_resolved = target_path.resolve()
        if nueva_ruta == old_resolved:
            dibujar_arbol_directorios()
            return
        if nueva_ruta.exists():
            dibujar_arbol_directorios()
            establecer_estado(f"Ya existe '{nuevo_nombre}' en esta carpeta.", "#ff7c84")
            return

        try:
            target_path.rename(nueva_ruta)
        except OSError as exc:
            dibujar_arbol_directorios()
            establecer_estado(f"No se pudo renombrar: {exc}", "#ff7c84")
            return

        for doc in documents:
            if doc["path"] is not None:
                doc_resolved = doc["path"].resolve()
                if doc_resolved == old_resolved:
                    doc["path"] = nueva_ruta
                    doc["name"] = nueva_ruta.name
                elif old_resolved in doc_resolved.parents:
                    rel = doc_resolved.relative_to(old_resolved)
                    doc["path"] = nueva_ruta / rel

        if active_path is not None:
            act_resolved = active_path.resolve()
            if act_resolved == old_resolved:
                active_path = nueva_ruta
            elif old_resolved in act_resolved.parents:
                active_path = nueva_ruta / act_resolved.relative_to(old_resolved)

        nuevas_expandidas: set[Path] = set()
        for exp_dir in expanded_directories:
            exp_resolved = exp_dir.resolve()
            if exp_resolved == old_resolved:
                nuevas_expandidas.add(nueva_ruta)
            elif old_resolved in exp_resolved.parents:
                nuevas_expandidas.add(nueva_ruta / exp_resolved.relative_to(old_resolved))
            else:
                nuevas_expandidas.add(exp_dir)
        expanded_directories.clear()
        expanded_directories.update(nuevas_expandidas)

        actualizar_metadatos_editor()
        dibujar_arbol_directorios()
        establecer_estado(f"Renombrado · {target_path.name} → {nueva_ruta.name}", "#56d68b")

    def crear_fila_renombrado_en_linea(
        target_path: Path,
        icon,
        depth: int,
        *,
        color: str = TEXT,
        leading_icon=None,
    ):
        prefix = (
            ft.Icon(leading_icon, size=16, color=MUTED)
            if leading_icon is not None
            else ft.Container(width=16)
        )
        inline_field = ft.TextField(
            value=target_path.name,
            autofocus=True,
            dense=True,
            height=26,
            width=max(150, len(target_path.name) * 8 + 36),
            text_size=12.5,
            color=TEXT,
            bgcolor="#111a28",
            cursor_color=ACCENT,
            content_padding=ft.Padding.symmetric(horizontal=6, vertical=3),
            border=crear_borde_campo(ACCENT, ACCENT, radio=4),
            on_submit=lambda ev, p=target_path: confirmar_renombrado_en_linea(
                p, ev.control.value
            ),
            on_blur=lambda ev, p=target_path: confirmar_renombrado_en_linea(
                p, ev.control.value
            ),
        )
        return ft.Container(
            content=ft.Row(
                [
                    prefix,
                    ft.Icon(icon, size=16, color=color),
                    inline_field,
                ],
                spacing=7,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.only(left=8 + depth * 14, right=7, top=2, bottom=2),
            bgcolor="#203149",
            border_radius=4,
            data=(target_path.name, depth),
        )

    def abrir_dialogo_eliminar_archivo(target_path: Path):
        nonlocal active_document, active_path, saved_content, previous_editor_text
        old_resolved = target_path.resolve()
        es_directorio = target_path.is_dir()

        def confirmar_eliminacion(_=None):
            nonlocal active_document, active_path, saved_content, previous_editor_text
            try:
                if es_directorio:
                    shutil.rmtree(target_path)
                else:
                    target_path.unlink()
            except OSError as exc:
                page.pop_dialog()
                establecer_estado(f"No se pudo eliminar {target_path.name}: {exc}", "#ff7c84")
                return

            expanded_directories.discard(old_resolved)

            # Si el archivo estaba abierto en el editor, cerrarlo y limpiar
            docs_a_remover = [
                doc for doc in documents
                if doc["path"] is not None
                and (
                    doc["path"].resolve() == old_resolved
                    or (es_directorio and old_resolved in doc["path"].resolve().parents)
                )
            ]
            estaba_activo = any(doc is active_document for doc in docs_a_remover)
            for doc in docs_a_remover:
                documents.remove(doc)

            if estaba_activo:
                active_document = None
                if documents:
                    activar_documento(documents[-1]["id"])
                else:
                    active_path = None
                    saved_content = ""
                    previous_editor_text = ""
                    editor.value = ""

            page.pop_dialog()
            actualizar_metadatos_editor()
            dibujar_arbol_directorios()
            establecer_estado(f"Eliminado · {target_path.name}", "#56d68b")
            actualizar_pagina_seguro()

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Confirmar eliminación", size=15, weight=ft.FontWeight.W_700),
                content=ft.Text(
                    f"¿Estás seguro de que deseas eliminar permanentemente '{target_path.name}' del disco?"
                ),
                actions=[
                    ft.TextButton("Cancelar", on_click=lambda _: page.pop_dialog()),
                    ft.FilledButton(
                        "Eliminar",
                        bgcolor="#d9534f",
                        color=ft.Colors.WHITE,
                        on_click=confirmar_eliminacion,
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def abrir_menu_contextual_explorador(target_path: Path, event=None):
        ruta_absoluta = str(target_path.resolve())

        async def accion_copiar_ruta(_):
            copiar_portapapeles_sistema(ruta_absoluta)
            try:
                await terminal_clipboard.set(ruta_absoluta)
            except Exception:
                pass
            establecer_estado(f"Ruta copiada · {ruta_absoluta}", "#56d68b")

        def accion_renombrar(_):
            iniciar_renombrado_en_linea(target_path)

        def accion_eliminar(_):
            abrir_dialogo_eliminar_archivo(target_path)

        mostrar_menu_contextual_flotante(
            event,
            items=[
                crear_item_menu_contextual(
                    "Copiar ruta",
                    ft.Icons.CONTENT_COPY,
                    accion_copiar_ruta,
                    color_icono=ACCENT,
                ),
                crear_item_menu_contextual(
                    "Renombrar",
                    ft.Icons.EDIT_OUTLINED,
                    accion_renombrar,
                    color_icono=BLUE,
                ),
                ft.Divider(height=5, thickness=1, color=BORDER),
                crear_item_menu_contextual(
                    "Eliminar",
                    ft.Icons.DELETE_OUTLINE,
                    accion_eliminar,
                    color_texto="#ff7c84",
                    color_icono="#ff7c84",
                ),
            ],
            width=240,
        )

    def dibujar_arbol_directorios():
        if app_cerrando:
            return
        rows = []

        def agregar_directorio(path: Path, depth: int, is_root: bool = False):
            is_expanded = path in expanded_directories

            def alternar_directorio(_):
                if path in expanded_directories:
                    expanded_directories.remove(path)
                else:
                    expanded_directories.add(path)
                dibujar_arbol_directorios()

            dir_icon = ft.Icons.FOLDER_OPEN if is_expanded else ft.Icons.FOLDER
            dir_leading = (
                ft.Icons.KEYBOARD_ARROW_DOWN
                if is_expanded
                else ft.Icons.CHEVRON_RIGHT
            )
            if not is_root and renaming_path is not None and path == renaming_path:
                rows.append(
                    crear_fila_renombrado_en_linea(
                        path,
                        dir_icon,
                        depth,
                        color="#f0c75e",
                        leading_icon=dir_leading,
                    )
                )
            else:
                rows.append(
                    crear_fila_arbol(
                        path.name or str(path),
                        dir_icon,
                        depth,
                        color="#f0c75e",
                        horizontal_scroll=True,
                        leading_icon=dir_leading,
                        on_click=alternar_directorio,
                        on_secondary_click=(
                            None
                            if is_root
                            else lambda ev, selected_dir=path: abrir_menu_contextual_explorador(
                                selected_dir, ev
                            )
                        ),
                    )
                )
            if not is_expanded:
                return

            try:
                entries = sorted(
                    path.iterdir(),
                    key=lambda entry: (
                        not (entry.is_dir() and not entry.is_symlink()),
                        entry.name.casefold(),
                    ),
                )
            except OSError as error:
                rows.append(
                    ft.Text(
                        f"No se pudo leer la carpeta: {error}",
                        size=11,
                        color="#ff7c84",
                    )
                )
                return

            for entry in entries:
                if entry.is_dir() and not entry.is_symlink():
                    agregar_directorio(entry, depth + 1)
                    continue
                file_icon = (
                    ft.Icons.CODE
                    if entry.suffix.lower() in {".py", ".sql", ".txt", ".json", ".yaml", ".yml"}
                    else ft.Icons.INSERT_DRIVE_FILE
                )
                file_color = BLUE if file_icon == ft.Icons.CODE else "#a9b8cb"
                if renaming_path is not None and entry == renaming_path:
                    rows.append(
                        crear_fila_renombrado_en_linea(
                            entry,
                            file_icon,
                            depth + 1,
                            color=file_color,
                        )
                    )
                else:
                    rows.append(
                        crear_fila_arbol(
                            entry.name,
                            file_icon,
                            depth + 1,
                            color=file_color,
                            selected=entry == active_path,
                            horizontal_scroll=True,
                            on_click=lambda _, selected_path=entry: abrir_ruta(selected_path),
                            on_secondary_click=lambda ev, selected_path=entry: abrir_menu_contextual_explorador(
                                selected_path, ev
                            ),
                        )
                    )

        agregar_directorio(root_directory, 0, is_root=True)
        explorer_body.controls = rows
        explorer_body.width = max(
            246,
            max(
                (
                    len(label) * 8 + 62 + depth * 14
                    for row in rows
                    if isinstance(row.data, tuple)
                    for label, depth in [row.data]
                ),
                default=246,
            ),
        )
        actualizar_control_seguro(explorer_body)

    def abrir_ruta(path: Path):
        path = path.resolve()
        existing_document = next(
            (document for document in documents if document["path"] == path),
            None,
        )
        if existing_document is not None:
            activar_documento(existing_document["id"])
            return

        try:
            raw_contents = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            establecer_estado(f"No se pudo abrir {path.name}: {error}", "#ff7c84")
            return
        # Reemplazar automáticamente todos los caracteres '\t' por 4 espacios explícitos
        contents = normalizar_tabulaciones(raw_contents)
        crear_documento(path, contents, contents)
        establecer_estado(f"Abierto · {path}", "#56d68b")

    def crear_documento(path: Path | None, contents: str, original_contents: str):
        nonlocal active_document, active_path, saved_content, next_document_id, previous_editor_text
        sincronizar_documento_activo()
        contents = normalizar_tabulaciones(contents)
        original_contents = normalizar_tabulaciones(original_contents)
        document = {
            "id": next_document_id,
            "path": path,
            "name": f"sin_titulo{next_document_id}.sql",
            "content": contents,
            "saved_content": original_contents,
        }
        next_document_id += 1
        documents.append(document)
        active_document = document
        active_path = path
        saved_content = original_contents
        previous_editor_text = contents
        editor.value = contents
        if contents.strip():
            session_symbol_table.merge_from(
                build_context_symbol_table(contents, fallback_table=session_symbol_table),
                overwrite=True,
            )
        actualizar_metadatos_editor()
        dibujar_arbol_directorios()
        actualizar_pagina_seguro()

    def activar_documento(document_id: int):
        nonlocal active_document, active_path, saved_content, previous_editor_text
        sincronizar_documento_activo()
        document = next(
            (item for item in documents if item["id"] == document_id),
            None,
        )
        if document is None:
            return
        document["content"] = normalizar_tabulaciones(document["content"])
        active_document = document
        active_path = document["path"]
        saved_content = document["saved_content"]
        previous_editor_text = document["content"]
        editor.value = document["content"]
        if document["content"].strip():
            session_symbol_table.merge_from(
                build_context_symbol_table(document["content"], fallback_table=session_symbol_table),
                overwrite=True,
            )
        actualizar_metadatos_editor()
        dibujar_arbol_directorios()
        actualizar_pagina_seguro()

    def cerrar_documento_ahora(document_id: int):
        nonlocal active_document, active_path, saved_content, previous_editor_text
        sincronizar_documento_activo()
        document_index = next(
            (
                index
                for index, document in enumerate(documents)
                if document["id"] == document_id
            ),
            None,
        )
        if document_index is None:
            return
        was_active = documents[document_index] is active_document
        documents.pop(document_index)
        if was_active:
            active_document = None
            if documents:
                next_index = min(document_index, len(documents) - 1)
                activar_documento(documents[next_index]["id"])
            else:
                active_path = None
                saved_content = ""
                previous_editor_text = ""
                editor.value = ""
                actualizar_metadatos_editor()
                dibujar_arbol_directorios()
                actualizar_pagina_seguro()
        else:
            actualizar_metadatos_editor()
            dibujar_arbol_directorios()
            actualizar_pagina_seguro()

    def cerrar_documento(document_id: int):
        sincronizar_documento_activo()
        document = next(
            (item for item in documents if item["id"] == document_id),
            None,
        )
        if document is None:
            return
        if document["content"] == document["saved_content"]:
            cerrar_documento_ahora(document_id)
            return

        def cancelar_cierre(_):
            page.pop_dialog()

        def descartar_y_cerrar(_):
            page.pop_dialog()
            cerrar_documento_ahora(document_id)

        async def guardar_y_cerrar(_):
            page.pop_dialog()
            if active_document is not document:
                activar_documento(document_id)
            await guardar_archivo(None)
            if document["content"] == document["saved_content"]:
                cerrar_documento_ahora(document_id)

        document_name = (
            document["path"].name
            if document["path"] is not None
            else document["name"]
        )
        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title="Cambios sin guardar",
                content=ft.Text(f"¿Guardar los cambios de {document_name} antes de cerrar?"),
                actions=[
                    ft.TextButton("Cancelar", on_click=cancelar_cierre),
                    ft.TextButton("Descartar", on_click=descartar_y_cerrar),
                    ft.TextButton("Guardar y cerrar", on_click=guardar_y_cerrar),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    async def elegir_carpeta(_):
        nonlocal root_directory
        selected = await file_picker.get_directory_path(
            dialog_title="Selecciona la carpeta raíz del proyecto",
            initial_directory=str(root_directory),
        )
        if not selected:
            return
        root_directory = Path(selected)
        root_name_label.value = root_directory.name or str(root_directory)
        expanded_directories.clear()
        expanded_directories.add(root_directory)
        dibujar_arbol_directorios()
        establecer_estado(f"Carpeta raíz · {root_directory}", "#56d68b")
        process = await iniciar_powershell()
        if process and process.isalive():
            command = str(root_directory).replace("'", "''")
            try:
                process.write(f"Set-Location -LiteralPath '{command}'\r")
            except (EOFError, OSError, WinptyError) as error:
                informar_error_terminal(f"No se pudo cambiar de carpeta en PowerShell: {error}")
        actualizar_pagina_seguro()

    async def elegir_archivo(_):
        picked_files = await file_picker.pick_files(
            dialog_title="Abrir archivo",
            initial_directory=str(root_directory),
            allow_multiple=False,
        )
        if picked_files and picked_files[0].path:
            abrir_ruta(Path(picked_files[0].path))

    async def guardar_archivo(_=None, desde_atajo: bool = False):
        nonlocal active_path, saved_content
        if active_document is None:
            establecer_estado("No hay ningún archivo abierto para guardar", "#f0b45b")
            return
        target = active_path
        if target is None:
            default_filename = active_document.get("name") or "consulta.sql"
            selected = await file_picker.save_file(
                dialog_title="Guardar archivo",
                file_name=default_filename,
                initial_directory=str(root_directory),
            )
            if selected is None or str(selected).strip() == "":
                return
            target = Path(selected)

        # Permitir guardar incluso cuando el archivo está completamente vacío ("")
        contenido_actual = editor.value if editor.value is not None else ""
        try:
            target.write_text(contenido_actual, encoding="utf-8")
        except OSError as error:
            establecer_estado(f"No se pudo guardar {target.name}: {error}", "#ff7c84")
            return

        active_path = target
        saved_content = contenido_actual
        active_document["path"] = target
        active_document["name"] = target.name
        active_document["content"] = saved_content
        active_document["saved_content"] = saved_content
        actualizar_metadatos_editor()
        dibujar_arbol_directorios()
        prefijo = "✓ Guardado (Ctrl+S)" if desde_atajo else "✓ Guardado"
        establecer_estado(f"{prefijo} · {target}", "#56d68b")
        actualizar_pagina_seguro()

    def crear_archivo_nuevo(_):
        crear_documento(None, "", "")
        establecer_estado("Nuevo archivo", MUTED)
        actualizar_pagina_seguro()

    async def animar_clic_boton(button, event, callback, pressed_color=None):
        if app_cerrando:
            return
        original_color = button.bgcolor
        button.scale = ft.Scale(scale=0.90)
        if pressed_color is not None:
            button.bgcolor = pressed_color
        actualizar_control_seguro(button)
        await asyncio.sleep(0.12)
        button.scale = ft.Scale(scale=1)
        button.bgcolor = original_color
        actualizar_control_seguro(button)
        if callback is not None:
            result = callback(event)
            if asyncio.iscoroutine(result):
                await result

    def crear_boton_icono(icon, tooltip, on_click=None, color=MUTED):
        button = configurar_sin_foco(
            ft.IconButton(
                icon=icon,
                icon_size=18,
                icon_color=color,
                tooltip=tooltip,
                animate_scale=ft.Animation(130, ft.AnimationCurve.EASE_OUT),
            )
        )

        async def manejar_clic(event):
            await animar_clic_boton(button, event, on_click)

        button.on_click = manejar_clic
        return button

    def crear_boton_accion(label, icon, color, on_click=None, pressed_color=None):
        button = configurar_sin_foco(
            ft.FilledButton(
                content=ft.Text(label, size=13, weight=ft.FontWeight.W_600),
                icon=icon,
                bgcolor=color,
                color=ft.Colors.WHITE,
                height=38,
                animate_scale=ft.Animation(130, ft.AnimationCurve.EASE_OUT),
            )
        )

        async def manejar_clic(event):
            await animar_clic_boton(button, event, on_click, pressed_color)

        button.on_click = manejar_clic
        return button

    def crear_encabezado_panel(icon, title, trailing=None):
        controls = [
            ft.Icon(icon, size=17, color="#c6d6e9"),
            ft.Text(title, size=12, weight=ft.FontWeight.W_700, color=TEXT),
        ]
        if trailing is not None:
            controls.append(trailing)
        return ft.Container(
            content=ft.Row(
                controls,
                spacing=9,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=HEADER,
            padding=ft.Padding.symmetric(horizontal=11, vertical=9),
        )

    # =====================================================================
    # 4.4 COMPILAR Y EJECUTAR SELECCIÓN DESDE EL PORTAPAPELES
    # =====================================================================

    def escribir_en_consola(texto: str):
        if app_cerrando:
            return
        escribir_salida_terminal(texto)

    def resumir_expresion_ast(nodo) -> str:
        if nodo is None:
            return ""
        if isinstance(nodo, Literal):
            if nodo.literal_type.upper() == "STRING_LITERAL":
                return f'"{nodo.value}"'
            return str(nodo.value)
        if isinstance(nodo, Identifier):
            return nodo.name
        if isinstance(nodo, Parameter):
            return f"{nodo.name} = {resumir_expresion_ast(nodo.value)}"
        if isinstance(nodo, UnaryOperation):
            op = f"{nodo.operator} " if nodo.operator.upper() == "NOT" else nodo.operator
            return f"{op}{resumir_expresion_ast(nodo.operand)}"
        if isinstance(nodo, BinaryOperation):
            return f"{resumir_expresion_ast(nodo.left)} {nodo.operator} {resumir_expresion_ast(nodo.right)}"
        return str(nodo)

    def actualizar_arbol_sintactico(ast_root: Program | None, errores_lista: list[str] | None = None):
        if app_cerrando:
            return
        nodos_ui = [
            crear_fila_arbol_sintactico(
                "Programa", ft.Icons.ACCOUNT_TREE, 0, color="#55a8ff"
            )
        ]

        if errores_lista:
            nodos_ui.append(
                crear_fila_arbol_sintactico(
                    f"Errores detectados ({len(errores_lista)})",
                    ft.Icons.ERROR_OUTLINE,
                    1,
                    color="#ff7c84",
                )
            )
            for err in errores_lista[:15]:
                nodos_ui.append(
                    crear_fila_arbol_sintactico(
                        err, ft.Icons.WARNING_AMBER, 2, color="#f0b45b"
                    )
                )

        if ast_root and getattr(ast_root, "statements", None):
            for stmt in ast_root.statements:
                if isinstance(stmt, ModelDeclaration):
                    nodos_ui.append(
                        crear_fila_arbol_sintactico(
                            "Modelo", ft.Icons.DATA_OBJECT, 1, color="#c084fc"
                        )
                    )
                    nodos_ui.append(
                        crear_fila_arbol_sintactico(
                            stmt.name, ft.Icons.TABLE_CHART, 2, color="#55a8ff"
                        )
                    )
                    nodos_ui.append(
                        crear_fila_arbol_sintactico(
                            "Atributos", ft.Icons.FOLDER, 3, color="#4ade80"
                        )
                    )
                    for campo in stmt.fields:
                        args_str = (
                            f"({', '.join(map(str, campo.data_type.args))})"
                            if campo.data_type.args
                            else ""
                        )
                        tipo_str = f"{campo.data_type.type_name.capitalize()}{args_str}"
                        restr_list = []
                        for c in campo.constraints:
                            if c.value is not None:
                                restr_list.append(
                                    f"{c.constraint_type.lower()}={resumir_expresion_ast(c.value)}"
                                )
                            else:
                                restr_list.append(c.constraint_type.lower())
                        restr_str = f" [{', '.join(restr_list)}]" if restr_list else ""
                        nodos_ui.append(
                            crear_fila_arbol_sintactico(
                                f"{campo.name} : {tipo_str}{restr_str}",
                                ft.Icons.CIRCLE,
                                4,
                                color="#57a9ff",
                            )
                        )
                elif isinstance(stmt, DbOperation):
                    cadena_resumen = ".".join(
                        f"{call.method}({', '.join(resumir_expresion_ast(a) for a in (call.arguments or []))})"
                        for call in stmt.calls
                    )
                    nodos_ui.append(
                        crear_fila_arbol_sintactico(
                            f"{stmt.model_name}.{cadena_resumen}",
                            ft.Icons.DATA_OBJECT,
                            1,
                            color="#c084fc",
                        )
                    )
                    for call in stmt.calls:
                        args_txt = ", ".join(
                            resumir_expresion_ast(a) for a in (call.arguments or [])
                        )
                        nodos_ui.append(
                            crear_fila_arbol_sintactico(
                                f".{call.method}({args_txt})",
                                ft.Icons.SUBDIRECTORY_ARROW_RIGHT,
                                2,
                                color="#56d9e8",
                            )
                        )

        syntax_tree.controls = nodos_ui
        ajustar_ancho_arbol_sintactico(nodos_ui)
        actualizar_control_seguro(syntax_tree)

    def recolectar_contexto_modelos(codigo_editor_actual: str) -> list[ModelDeclaration]:
        """
        Recolecta los modelos declarados en el editor activo y en cualquier otra
        pestaña abierta en `documents`, actualizando `session_symbol_table` para
        que la Tabla de Símbolos persistente conserve todos los esquemas de la sesión.
        """
        modelos_por_nombre: dict[str, ModelDeclaration] = {}

        # 1. Modelos de otras pestañas abiertas en la sesión
        for doc in documents:
            if doc is active_document:
                continue
            contenido_doc = doc.get("content") or ""
            if contenido_doc.strip():
                for m_node in extract_context_models(contenido_doc):
                    modelos_por_nombre[m_node.name.lower()] = m_node
                session_symbol_table.merge_from(
                    build_context_symbol_table(contenido_doc),
                    overwrite=True,
                )

        # 2. Modelos del editor activo (tienen prioridad si se redefinió algún modelo)
        if codigo_editor_actual and codigo_editor_actual.strip():
            for m_node in extract_context_models(codigo_editor_actual):
                modelos_por_nombre[m_node.name.lower()] = m_node
            session_symbol_table.merge_from(
                build_context_symbol_table(codigo_editor_actual),
                overwrite=True,
            )

        return list(modelos_por_nombre.values())

    def preparar_fragmento_portapapeles(fragmento: str) -> str:
        """
        Normaliza un fragmento copiado al portapapeles:
        - Convierte tabuladores en 4 espacios y normaliza saltos de línea.
        - Si solo contiene operaciones DML, elimina los espacios iniciales de cada línea
          para evitar tokens INDENT inesperados.
        - Si contiene bloques `model`, aplica dedent y normaliza la sangría interna a 4 espacios.
        """
        return normalize_dsl_fragment(fragmento)

    def formatear_error_compilacion(error: str) -> str:
        document_id = terminal_diagnostic_document_id
        if document_id is None:
            return error

        location = re.search(
            r"\blínea\s+(\d+)\s*,\s*columna\s+(\d+)",
            error,
            re.IGNORECASE,
        )
        line = int(location.group(1)) if location else None
        column = int(location.group(2)) if location else None
        has_column = location is not None
        if location is None:
            location = re.search(
                r"Error Semántico\s+\(Línea\s+(\d+)\)",
                error,
                re.IGNORECASE,
            )
            if location:
                line = int(location.group(1))
        if location is None:
            location = re.search(
                r"Error de indentación en la línea\s+(\d+)",
                error,
                re.IGNORECASE,
            )
            if location:
                line = int(location.group(1))
        if location is None and "fin de archivo inesperado" in error.lower():
            contents = editor.value or ""
            final_line = contents.rstrip("\n").rsplit("\n", 1)[-1]
            line = max(1, len(contents.rstrip("\n").split("\n")))
            column = len(final_line) + 1
            has_column = True
        if line is None:
            return error

        column = column or 1
        document = next(
            (item for item in documents if item["id"] == document_id),
            None,
        )
        if document is None:
            return error
        source_name = (
            document["path"].name
            if document["path"] is not None
            else document["name"]
        )
        link = f"[{source_name}:{line}"
        if has_column:
            link += f":{column}"
        link += "]"
        terminal_diagnostic_targets[link] = (line, column, document_id)
        return f"{link} {error}"

    def ejecutar_pipeline_compilacion(
        mostrar_en_consola: bool = True,
        codigo_override: str | None = None,
        usar_contexto_editor: bool = False,
        etiqueta_origen: str | None = None,
    ):
        nonlocal terminal_diagnostic_document_id
        sincronizar_documento_activo()
        terminal_diagnostic_document_id = (
            active_document["id"]
            if codigo_override is None and active_document is not None
            else None
        )
        codigo_editor_completo = editor.value or ""

        if codigo_override is not None:
            codigo_fuente = preparar_fragmento_portapapeles(codigo_override)
            nombre_doc = etiqueta_origen or "Selección (Portapapeles)"
            stem_doc = (
                f"{active_path.stem}_seleccion"
                if active_path is not None
                else "seleccion_portapapeles"
            )
        else:
            codigo_fuente = codigo_editor_completo
            nombre_doc = (
                active_path.name
                if active_path is not None
                else (active_document["name"] if active_document else "buffer.dsl")
            )
            stem_doc = (
                active_path.stem
                if active_path is not None
                else Path(nombre_doc).stem
            )

        if not codigo_fuente.strip():
            actualizar_arbol_sintactico(None, ["El código a compilar está vacío."])
            if mostrar_en_consola:
                escribir_en_consola("[!] No hay código DSL para compilar.")
                establecer_estado("Código vacío", "#f0b45b")
            return False, None, None

        if not codigo_fuente.endswith("\n"):
            codigo_fuente += "\n"

        # Recolectar modelos de contexto del editor activo y documentos abiertos
        modelos_contexto = recolectar_contexto_modelos(codigo_editor_completo)

        # 1. Fase Léxica
        errores_lexicos.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            lexer.input(codigo_fuente)
            tokens = []
            while True:
                tok = lexer.token()
                if tok is None:
                    break
                tokens.append(tok)

        if errores_lexicos:
            actualizar_arbol_sintactico(None, list(errores_lexicos))
            if mostrar_en_consola:
                lineas = [
                    "=" * 70,
                    f"COMPILANDO: {nombre_doc}",
                    "=" * 70,
                    f"[Fase Léxica] Se encontraron {len(errores_lexicos)} errores léxicos:",
                    *[
                        f"  • {formatear_error_compilacion(e)}"
                        for e in errores_lexicos
                    ],
                    "[Fase Sintáctica] Omitida debido a errores léxicos previos.",
                    "[Fase Semántica] Omitida debido a errores léxicos previos.",
                    "=" * 70,
                ]
                escribir_en_consola("\n".join(lineas))
                establecer_estado(f"Error léxico ({len(errores_lexicos)})", "#ff7c84")
            return False, None, None

        # 2. Fase Sintáctica
        errores_sintacticos.clear()
        token_iterator = iter(tokens)
        with contextlib.redirect_stdout(io.StringIO()):
            ast_resultado = parser.parse(tokenfunc=lambda: next(token_iterator, None))

        if errores_sintacticos:
            actualizar_arbol_sintactico(ast_resultado, list(errores_sintacticos))
            if mostrar_en_consola:
                lineas = [
                    "=" * 70,
                    f"COMPILANDO: {nombre_doc}",
                    "=" * 70,
                    "[Fase Léxica] ÉXITO (0 errores léxicos).",
                    f"[Fase Sintáctica] Se encontraron {len(errores_sintacticos)} errores sintácticos:",
                    *[
                        f"  • {formatear_error_compilacion(e)}"
                        for e in errores_sintacticos
                    ],
                    "[Fase Semántica] Omitida debido a errores sintácticos previos.",
                    "=" * 70,
                ]
                escribir_en_consola("\n".join(lineas))
                establecer_estado(f"Error sintáctico ({len(errores_sintacticos)})", "#ff7c84")
            return False, None, None

        # 3. Fase Semántica (inyectando modelos del editor + tabla de símbolos persistente de sesión)
        analizador_sem = SemanticAnalyzer()
        with contextlib.redirect_stdout(io.StringIO()):
            errores_sem, tabla_simbolos = analizador_sem.analyze(
                ast_resultado,
                context_models=modelos_contexto if usar_contexto_editor else None,
                context_code=codigo_editor_completo if usar_contexto_editor else None,
                persistent_symbols=session_symbol_table,
            )

        if tabla_simbolos and tabla_simbolos.models:
            session_symbol_table.merge_from(tabla_simbolos, overwrite=True)

        if errores_sem:
            actualizar_arbol_sintactico(ast_resultado, list(errores_sem))
            if mostrar_en_consola:
                lineas = [
                    "=" * 70,
                    f"COMPILANDO: {nombre_doc}",
                    "=" * 70,
                    "[Fase Léxica] ÉXITO (0 errores léxicos).",
                    "[Fase Sintáctica] ÉXITO (0 errores sintácticos).",
                    f"[Fase Semántica] Se encontraron {len(errores_sem)} errores semánticos:",
                    *[
                        f"  • {formatear_error_compilacion(e)}"
                        for e in errores_sem
                    ],
                    "=" * 70,
                ]
                escribir_en_consola("\n".join(lineas))
                establecer_estado(f"Error semántico ({len(errores_sem)})", "#ff7c84")
            return False, None, None

        # 4. Fase de Generación de Código SQL (PostgreSQL)
        # Filtrado estricto: solo se genera CREATE TABLE para modelos declarados explícitamente en ast_resultado
        actualizar_arbol_sintactico(ast_resultado, None)
        modelos_explicitos_ast = {
            stmt.name.lower()
            for stmt in (getattr(ast_resultado, "statements", None) or [])
            if isinstance(stmt, ModelDeclaration)
        }
        generador = SQLCodeGenerator(tabla_simbolos)
        sentencias_sql = generador.generate(
            ast_resultado,
            allowed_model_declarations=modelos_explicitos_ast if usar_contexto_editor else None,
        )
        script_sql = sentencias_sql.script

        carpeta_sql = root_directory / "sql_generado"
        carpeta_sql.mkdir(parents=True, exist_ok=True)
        ruta_sql = carpeta_sql / f"{stem_doc}.sql"
        try:
            ruta_sql.write_text(script_sql + ("\n" if script_sql else ""), encoding="utf-8")
        except OSError:
            pass
        dibujar_arbol_directorios()

        if mostrar_en_consola:
            total_modelos_ctx = len(tabla_simbolos.models)
            info_ctx = (
                f" (Contexto semántico: {total_modelos_ctx} modelo(s) en Tabla de Símbolos)"
                if usar_contexto_editor and total_modelos_ctx
                else ""
            )
            lineas = [
                "=" * 70,
                f"COMPILACIÓN EXITOSA: {nombre_doc}",
                "=" * 70,
                "[Fase Léxica] ÉXITO (0 errores).",
                "[Fase Sintáctica] ÉXITO (0 errores).",
                f"[Fase Semántica] ÉXITO (0 errores){info_ctx}.",
                f"[Fase Generación SQL] {len(sentencias_sql)} sentencia(s) PostgreSQL generada(s).",
                f"[Archivo guardado] {ruta_sql}",
                "",
                "--- Código SQL Generado (PostgreSQL) ---",
            ]
            for idx, stmt in enumerate(sentencias_sql, start=1):
                lineas.append(f"\n-- [{idx}]")
                lineas.append(stmt)
            lineas.append("=" * 70)
            escribir_en_consola("\n".join(lineas))
            establecer_estado(
                f"Compilado con éxito · {len(sentencias_sql)} sentencias SQL",
                "#56d68b",
            )

        return True, sentencias_sql, ruta_sql

    async def compilar_codigo(_=None):
        ejecutar_pipeline_compilacion(mostrar_en_consola=True)
        actualizar_pagina_seguro()

    async def ejecutar_sentencias_en_postgres(sentencias_sql):
        establecer_estado("Ejecutando SQL en PostgreSQL...", "#4da3ff")
        executor = PostgresExecutor()
        reporte = await asyncio.to_thread(
            executor.execute_statements,
            sentencias_sql,
            None,
            True,
        )
        escribir_en_consola(reporte.format_report())
        if not reporte.connected:
            establecer_estado("Error de conexión a PostgreSQL", "#ff7c84")
        elif reporte.error_count > 0:
            establecer_estado(
                f"Ejecutado con {reporte.error_count} error(es) en PostgreSQL",
                "#f0b45b",
            )
        else:
            establecer_estado(
                f"Ejecución PostgreSQL exitosa · {reporte.success_count} sentencias OK",
                "#56d68b",
            )
        actualizar_pagina_seguro()

    async def compilar_y_ejecutar_codigo(_=None):
        exito, sentencias_sql, _ = ejecutar_pipeline_compilacion(mostrar_en_consola=True)
        if not exito or sentencias_sql is None:
            actualizar_pagina_seguro()
            return
        await ejecutar_sentencias_en_postgres(sentencias_sql)

    async def obtener_texto_portapapeles() -> str:
        texto = leer_portapapeles_sistema()
        if texto and texto.strip():
            return texto
        try:
            clip_flet = await asyncio.wait_for(terminal_clipboard.get(), timeout=0.6)
            if isinstance(clip_flet, str) and clip_flet.strip():
                return clip_flet
        except Exception:
            pass
        return ""

    async def compilar_seleccion_portapapeles(_=None):
        fragmento = await obtener_texto_portapapeles()
        if not fragmento or not fragmento.strip():
            escribir_en_consola(
                "[!] El portapapeles está vacío. Selecciona el fragmento en el editor, "
                "presiona Ctrl+C y vuelve a intentarlo."
            )
            establecer_estado("Portapapeles vacío (usa Ctrl+C primero)", "#f0b45b")
            return
        ejecutar_pipeline_compilacion(
            mostrar_en_consola=True,
            codigo_override=fragmento,
            usar_contexto_editor=True,
            etiqueta_origen="Selección (Portapapeles)",
        )
        actualizar_pagina_seguro()

    async def compilar_y_ejecutar_seleccion_portapapeles(_=None):
        fragmento = await obtener_texto_portapapeles()
        if not fragmento or not fragmento.strip():
            escribir_en_consola(
                "[!] El portapapeles está vacío. Selecciona el fragmento en el editor, "
                "presiona Ctrl+C y vuelve a intentarlo."
            )
            establecer_estado("Portapapeles vacío (usa Ctrl+C primero)", "#f0b45b")
            return
        exito, sentencias_sql, _ = ejecutar_pipeline_compilacion(
            mostrar_en_consola=True,
            codigo_override=fragmento,
            usar_contexto_editor=True,
            etiqueta_origen="Selección (Portapapeles)",
        )
        if not exito or sentencias_sql is None:
            actualizar_pagina_seguro()
            return
        await ejecutar_sentencias_en_postgres(sentencias_sql)

    def abrir_menu_contextual_editor(event=None):
        mostrar_menu_contextual_flotante(
            event,
            items=[
                crear_item_menu_contextual(
                    "Compilar selección (Portapapeles)",
                    ft.Icons.PLAY_ARROW,
                    compilar_seleccion_portapapeles,
                    color_icono=ACCENT,
                ),
                crear_item_menu_contextual(
                    "Compilar y ejecutar selección",
                    ft.Icons.ROCKET_LAUNCH,
                    compilar_y_ejecutar_seleccion_portapapeles,
                    color_icono="#e98222",
                ),
                ft.Divider(height=5, thickness=1, color=BORDER),
                crear_item_menu_contextual(
                    "Buscar en el archivo",
                    ft.Icons.SEARCH,
                    abrir_busqueda,
                    atajo="Ctrl+F",
                    color_icono=BLUE,
                ),
            ],
            width=290,
        )

    # =====================================================================
    # 4.3 CONFIGURACIÓN DE POSTGRESQL CON CHECKBOXES OMITIR DDL Y OMITIR ALTER
    # =====================================================================

    def abrir_configuracion_bd(_=None):
        cfg = load_db_config()
        host_field = ft.TextField(
            label="Host",
            value=str(cfg.get("host", "localhost")),
            height=44,
            text_size=13,
            border=crear_borde_campo(BORDER, ACCENT),
        )
        port_field = ft.TextField(
            label="Puerto",
            value=str(cfg.get("port", 5432)),
            height=44,
            text_size=13,
            border=crear_borde_campo(BORDER, ACCENT),
        )
        user_field = ft.TextField(
            label="Usuario",
            value=str(cfg.get("user", "postgres")),
            height=44,
            text_size=13,
            border=crear_borde_campo(BORDER, ACCENT),
        )
        pass_field = ft.TextField(
            label="Contraseña",
            value=str(cfg.get("password", "postgres")),
            password=True,
            can_reveal_password=True,
            height=44,
            text_size=13,
            border=crear_borde_campo(BORDER, ACCENT),
        )
        db_field = ft.TextField(
            label="Base de datos",
            value=str(cfg.get("dbname", "compiladorsql_db")),
            height=44,
            text_size=13,
            border=crear_borde_campo(BORDER, ACCENT),
        )
        reset_check = ft.Checkbox(
            label="Reiniciar tablas del script antes de ejecutar (DROP CASCADE)",
            value=bool(cfg.get("reset_tables", True)),
        )

        omit_ddl_inicial = bool(cfg.get("omit_ddl", False))
        omit_alter_inicial = bool(cfg.get("omit_alter", True))

        omit_ddl_check = ft.Checkbox(
            label="Omitir DDL",
            value=omit_ddl_inicial,
            tooltip="Omite sentencias de definición de datos (CREATE, DROP, TRUNCATE) al ejecutar en PostgreSQL",
        )
        omit_alter_check = ft.Checkbox(
            label="Omitir ALTER",
            value=omit_alter_inicial if omit_ddl_inicial else True,
            disabled=not omit_ddl_inicial,
            tooltip="Si se desmarca, permite ejecutar sentencias ALTER aunque 'Omitir DDL' esté activo",
        )

        def al_cambiar_omit_ddl(_):
            if omit_ddl_check.value:
                omit_alter_check.disabled = False
                omit_alter_check.value = True
            else:
                omit_alter_check.disabled = True
            actualizar_control_seguro(omit_alter_check)

        omit_ddl_check.on_change = al_cambiar_omit_ddl

        feedback_text = ft.Text("", size=12, color=MUTED)

        async def probar_conexion_click(_):
            feedback_text.value = "Probando conexión..."
            feedback_text.color = "#4da3ff"
            actualizar_pagina_seguro()
            try:
                puerto_val = int(port_field.value or 5432)
            except ValueError:
                puerto_val = 5432
            exec_test = PostgresExecutor(
                host=host_field.value or "localhost",
                port=puerto_val,
                user=user_field.value or "postgres",
                password=pass_field.value or "",
                dbname=db_field.value or "compiladorsql_db",
            )
            ok, msg = await asyncio.to_thread(exec_test.test_connection, True)
            feedback_text.value = msg
            feedback_text.color = "#56d68b" if ok else "#ff7c84"
            actualizar_pagina_seguro()

        def guardar_cfg_click(_):
            try:
                puerto_val = int(port_field.value or 5432)
            except ValueError:
                puerto_val = 5432
            nueva_cfg = {
                "host": (host_field.value or "localhost").strip(),
                "port": puerto_val,
                "user": (user_field.value or "postgres").strip(),
                "password": pass_field.value or "",
                "dbname": (db_field.value or "compiladorsql_db").strip(),
                "reset_tables": bool(reset_check.value),
                "omit_ddl": bool(omit_ddl_check.value),
                "omit_alter": bool(omit_alter_check.value),
            }
            ruta_cfg = save_db_config(nueva_cfg)
            page.pop_dialog()
            establecer_estado(f"Configuración PostgreSQL guardada ({ruta_cfg.name})", "#56d68b")

        def cerrar_cfg_click(_):
            page.pop_dialog()

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Configuración de Conexión PostgreSQL", size=16, weight=ft.FontWeight.W_700),
                content=ft.Container(
                    content=ft.Column(
                        [
                            host_field,
                            port_field,
                            user_field,
                            pass_field,
                            db_field,
                            reset_check,
                            ft.Row(
                                [omit_ddl_check, omit_alter_check],
                                spacing=18,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            feedback_text,
                        ],
                        tight=True,
                        spacing=10,
                    ),
                    width=430,
                ),
                actions=[
                    ft.TextButton("Probar conexión", on_click=probar_conexion_click),
                    ft.TextButton("Cancelar", on_click=cerrar_cfg_click),
                    ft.FilledButton("Guardar", on_click=guardar_cfg_click),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    explorer_panel = ft.Container(
        content=ft.Column(
            [
                crear_encabezado_panel(
                    ft.Icons.FOLDER_OPEN,
                    "EXPLORADOR",
                    crear_boton_icono(ft.Icons.CREATE_NEW_FOLDER, "Abrir carpeta", elegir_carpeta),
                ),
                ft.Container(
                    content=explorer_horizontal_scroll,
                    padding=ft.Padding.only(top=5, bottom=6),
                    expand=True,
                ),
            ],
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
        ),
        width=248,
        bgcolor=PANEL,
        border=ft.Border.all(1, BORDER),
        border_radius=5,
    )

    editor_gesture_area = ft.GestureDetector(
        content=editor_scroll,
        on_secondary_tap_down=abrir_menu_contextual_editor,
        expand=True,
    )

    editor_options_menu = configurar_sin_foco(
        ft.PopupMenuButton(
            icon=ft.Icons.MORE_HORIZ,
            icon_color=MUTED,
            tooltip="Opciones del editor",
            items=[
                ft.PopupMenuItem(
                    content="Compilar selección (Portapapeles)",
                    icon=ft.Icons.PLAY_ARROW,
                    on_click=compilar_seleccion_portapapeles,
                ),
                ft.PopupMenuItem(
                    content="Compilar y ejecutar selección (Portapapeles)",
                    icon=ft.Icons.ROCKET_LAUNCH,
                    on_click=compilar_y_ejecutar_seleccion_portapapeles,
                ),
                ft.PopupMenuItem(),
                ft.PopupMenuItem(
                    content="Buscar texto  Ctrl+F",
                    icon=ft.Icons.SEARCH,
                    on_click=abrir_busqueda,
                ),
            ],
        )
    )

    editor_panel = ft.Container(
        content=ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            tabs_bar,
                            editor_options_menu,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor="#151e2b",
                    padding=ft.Padding.only(left=12, right=6, top=2, bottom=2),
                    height=39,
                ),
                search_bar,
                editor_gesture_area,
                ft.Container(
                    content=ft.Row(
                        [
                            language_label,
                            ft.Text("UTF-8", size=11, color=MUTED),
                            ft.Text("│", size=11, color=MUTED),
                            ft.Text("Indentación: 4 espacios ('>>' o Tab)", size=11, color=MUTED),
                        ],
                        spacing=12,
                    ),
                    padding=ft.Padding.only(left=12, top=5, bottom=5),
                    bgcolor="#151e2b",
                ),
            ],
            spacing=0,
            expand=True,
        ),
        expand=True,
        bgcolor=PANEL,
        border=ft.Border.all(1, BORDER),
        border_radius=5,
    )

    syntax_tree = ft.Column(
        [
            crear_fila_arbol_sintactico(label, icon, depth, color=color)
            for label, icon, color, depth in [
                ("Programa", ft.Icons.ACCOUNT_TREE, "#55a8ff", 0),
                ("Modelo", ft.Icons.DATA_OBJECT, "#c084fc", 1),
                ("estudiante", ft.Icons.DATA_OBJECT, "#55a8ff", 2),
                ("Atributos", ft.Icons.FOLDER, "#4ade80", 3),
                ("nombre : String", ft.Icons.CIRCLE, "#57a9ff", 4),
                ("matricula : Auto", ft.Icons.CIRCLE, "#57a9ff", 4),
                ("edad : Num", ft.Icons.CIRCLE, "#57a9ff", 4),
                ("peso : Decimal", ft.Icons.CIRCLE, "#57a9ff", 4),
                ("estudiante.find(...)", ft.Icons.DATA_OBJECT, "#c084fc", 1),
            ]
        ],
        spacing=1,
        scroll=ft.ScrollMode.AUTO,
        width=270,
    )
    syntax_tree_view = ft.Row(
        controls=[syntax_tree],
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    syntax_panel = ft.Container(
        content=ft.Column(
            [
                crear_encabezado_panel(ft.Icons.ACCOUNT_TREE, "ÁRBOL SINTÁCTICO"),
                ft.Container(
                    content=syntax_tree_view,
                    padding=ft.Padding.only(top=9, bottom=7),
                    expand=True,
                ),
            ],
            spacing=0,
            expand=True,
        ),
        width=270,
        bgcolor=PANEL,
        border=ft.Border.all(1, BORDER),
        border_radius=5,
    )

    def ajustar_ancho_arbol_sintactico(nodes):
        required_width = max(
            (
                len(label) * 8 + 62 + depth * 14
                for node in nodes
                if isinstance(node.data, tuple)
                for label, depth in [node.data]
            ),
            default=270,
        )
        syntax_tree.width = max(270, required_width)

    ajustar_ancho_arbol_sintactico(syntax_tree.controls)

    terminal_output.scroll = ft.ScrollMode.AUTO
    terminal_output.auto_scroll = False
    terminal_viewport = ft.Container(
        content=terminal_output,
        expand=True,
        bgcolor="#111a28",
        padding=ft.Padding.only(left=12, top=5, right=12, bottom=5),
        on_size_change=al_redimensionar_terminal,
    )

    terminal_listener = ft.KeyboardListener(
        content=ft.Container(
            content=terminal_viewport,
            expand=True,
            bgcolor="#111a28",
            on_click=enfocar_terminal,
        ),
        autofocus=True,
        on_key_down=al_pulsar_tecla_terminal,
        on_key_up=al_soltar_tecla_terminal,
        on_key_repeat=al_pulsar_tecla_terminal,
    )

    terminal_panel = ft.Container(
        content=ft.Column(
            [
                crear_encabezado_panel(
                    ft.Icons.TERMINAL,
                    "CONSOLA / RESULTADOS",
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.CIRCLE, size=9, color="#56d68b"),
                                ft.Text("PowerShell", size=11, color=MUTED),
                            ],
                            spacing=6,
                        ),
                        padding=ft.Padding.only(right=4),
                    ),
                ),
                ft.Container(
                    content=terminal_listener,
                    expand=True,
                ),
            ],
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
        ),
        height=terminal_height,
        bgcolor=PANEL,
        border=ft.Border.all(1, BORDER),
        border_radius=5,
    )

    terminal_divider = ft.GestureDetector(
        content=ft.Container(
            content=ft.Row(
                [
                    terminal_divider_bar,
                    terminal_divider_label,
                ],
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=12,
            alignment=ft.Alignment.CENTER,
        ),
        mouse_cursor=ft.MouseCursor.RESIZE_UP_DOWN,
        on_vertical_drag_start=iniciar_redimension_terminal,
        on_vertical_drag_update=redimensionar_terminal,
        on_vertical_drag_end=finalizar_redimension_terminal,
    )

    toolbar = ft.Container(
        content=ft.Row(
            [
                crear_boton_accion("Nuevo", ft.Icons.NOTE_ADD, "#2a3c53", crear_archivo_nuevo, "#52779b"),
                crear_boton_accion("Abrir archivo", ft.Icons.FOLDER_OPEN, "#2a3c53", elegir_archivo, "#52779b"),
                crear_boton_accion("Guardar", ft.Icons.SAVE, "#2a3c53", guardar_archivo, "#52779b"),
                ft.Container(width=4),
                crear_boton_accion("Compilar", ft.Icons.PLAY_ARROW, "#0b9f99", compilar_codigo, "#087f7a"),
                crear_boton_accion("Compilar y ejecutar", ft.Icons.PLAY_ARROW, "#e98222", compilar_y_ejecutar_codigo, "#c56b17"),
                crear_boton_accion("PostgreSQL", ft.Icons.STORAGE, "#2a3c53", abrir_configuracion_bd, "#52779b"),
                ft.Container(expand=True),
                root_name_label,
                crear_boton_icono(ft.Icons.FOLDER_OPEN, "Seleccionar carpeta raíz", elegir_carpeta),
            ],
            spacing=9,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=55,
        padding=ft.Padding.symmetric(horizontal=12),
        bgcolor="#1b293c",
        border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)),
    )

    app_header = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.STORAGE, size=22, color="#ff8a24"),
                ft.Text(
                    "CompiladorSQL",
                    size=16,
                    weight=ft.FontWeight.W_700,
                    color=TEXT,
                ),
                ft.Text("— Editor y compilador", size=14, color=MUTED),
                ft.Container(expand=True),
                ft.Text("●", size=10, color=ACCENT),
                ft.Text("INTERFAZ", size=10, color=MUTED, weight=ft.FontWeight.W_700),
            ],
            spacing=9,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=44,
        padding=ft.Padding.symmetric(horizontal=15),
        bgcolor="#111a28",
    )

    status_bar = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.CODE, size=17, color="#4da3ff"),
                ft.Text("Python 3", size=12, color=TEXT),
                ft.Text("│", size=12, color=MUTED),
                ft.Text("UTF-8", size=12, color=TEXT),
                ft.Container(expand=True),
                status_text,
                ft.Container(width=8),
                cursor_position_label,
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=31,
        padding=ft.Padding.symmetric(horizontal=12),
        bgcolor="#1b293c",
    )

    page.add(
        ft.Column(
            [
                app_header,
                toolbar,
                ft.Row(
                    [
                        explorer_panel,
                        editor_panel,
                        syntax_panel,
                    ],
                    spacing=7,
                    expand=True,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                    on_size_change=al_redimensionar_area_trabajo,
                ),
                terminal_divider,
                terminal_panel,
                status_bar,
            ],
            spacing=7,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
        )
    )

    expanded_directories.add(root_directory)
    dibujar_arbol_directorios()
    if active_path:
        initial_path = active_path
        active_path = None
        abrir_ruta(initial_path)
        ejecutar_pipeline_compilacion(mostrar_en_consola=False)
    else:
        actualizar_metadatos_editor()
    actualizar_pagina_seguro()
    page.run_task(iniciar_powershell)


if __name__ == "__main__":
    ft.run(iniciar_interfaz)
