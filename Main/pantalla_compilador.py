import asyncio
import queue
import re
import shutil
import threading
from pathlib import Path

import flet as ft
import pyte
from winpty import PtyProcess, WinptyError


BACKGROUND = "#101722"
PANEL = "#172232"
PANEL_LIGHT = "#203149"
HEADER = "#1c2b40"
BORDER = "#2d405b"
TEXT = "#e5edf7"
MUTED = "#93a4ba"
ACCENT = "#24b8ad"
BLUE = "#4da3ff"


def iniciar_interfaz(page: ft.Page):
    page.title = "CompiladorSQL — Editor y compilador"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BACKGROUND
    page.padding = 0
    page.spacing = 0

    root_directory = Path(__file__).resolve().parent.parent
    active_path = root_directory / "Prueba.txt"
    if not active_path.is_file():
        active_path = None
    saved_content = ""
    documents: list[dict] = []
    active_document: dict | None = None
    next_document_id = 1
    expanded_directories: set[Path] = set()
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
    workspace_height = 0
    terminal_has_focus = True
    terminal_refocus_pending = False
    rendered_history_count = -1
    rendered_history_ids: tuple[int, ...] = ()
    terminal_row_controls: list[ft.Text] = []
    terminal_selections: dict[int, str] = {}
    terminal_resize_handle: asyncio.TimerHandle | None = None
    pending_terminal_size: tuple[int, int, float] | None = None
    editor_scroll_offset = 0.0
    editor_viewport_height = 0.0
    editor_line_height = 18

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
        expand=False,
        border=ft.InputBorder.NONE,
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

    editor_preview = ft.Text(
        value="",
        size=14,
        font_family="Consolas",
        style=ft.TextStyle(
            height=editor_line_height / 14,
            color=TEXT,
        ),
        expand=True,
    )
    editor_preview_container = ft.Container(
        content=editor_preview,
        padding=ft.Padding.only(left=8, top=10, right=12, bottom=12),
        expand=True,
        ignore_interactions=True,
        visible=False,
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
                content=ft.Stack(
                    controls=[
                        editor_preview_container,
                        editor,
                    ],
                    fit=ft.StackFit.EXPAND,
                    expand=True,
                ),
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
        auto_scroll=False,
        expand=True,
        build_controls_on_demand=True,
        item_extent=18,
        reverse=True,
        width=terminal_content_width,
    )
    explorer_body = ft.Column(
        spacing=1,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    def establecer_estado(message: str, color: str = MUTED):
        status_text.value = message
        status_text.color = color
        page.update()

    def sincronizar_documento_activo():
        if active_document is not None:
            active_document["content"] = editor.value or ""
            active_document["saved_content"] = saved_content

    def dibujar_pestanas():
        tab_controls = []
        for document in documents:
            document_id = document["id"]
            path = document["path"]
            filename = path.name if path is not None else document["name"]
            is_dirty = document["content"] != document["saved_content"]
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
                            ft.IconButton(
                                icon=ft.Icons.CLOSE,
                                icon_size=15,
                                icon_color=MUTED,
                                tooltip="Cerrar archivo",
                                on_click=lambda _, selected_id=document_id: cerrar_documento(
                                    selected_id
                                ),
                            ),
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
        is_dirty = (editor.value or "") != saved_content
        language_label.value = (
            active_path.suffix[1:].upper()
            if active_path and active_path.suffix
            else "SQL"
        )
        contents = editor.value or ""
        line_count = contents.count("\n") + 1
        editor.max_lines = line_count + 1
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
        content_height = line_count * editor_line_height + 30
        line_numbers.height = content_height
        editor.height = content_height
        editor_content.height = content_height
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

    async def al_cambiar_seleccion_editor(event):
        actualizar_posicion_cursor(event.selection)
        preceding_text = (editor.value or "")[:event.selection.extent_offset]
        line = preceding_text.count("\n") + 1
        line_top = (line - 1) * editor_line_height + 10
        if editor_viewport_height and line_top < editor_scroll_offset:
            await editor_scroll.scroll_to(offset=max(0, line_top), duration=120)
        elif (
            editor_viewport_height
            and line_top + editor_line_height
            > editor_scroll_offset + editor_viewport_height
        ):
            target = line_top - editor_viewport_height + editor_line_height
            await editor_scroll.scroll_to(offset=max(0, target), duration=120)
        page.update(cursor_position_label)

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
        if not search_matches:
            return
        active_search_match = index % len(search_matches)
        start, end = search_matches[active_search_match]
        editor.selection = ft.TextSelection(start, end)
        search_status.value = (
            f"{active_search_match + 1} de {len(search_matches)}"
        )
        actualizar_vista_busqueda()
        line = (editor.value or "")[:start].count("\n") + 1
        line_top = (line - 1) * editor_line_height + 10
        if editor_viewport_height and line_top < editor_scroll_offset:
            await editor_scroll.scroll_to(offset=max(0, line_top), duration=120)
        elif (
            editor_viewport_height
            and line_top + editor_line_height
            > editor_scroll_offset + editor_viewport_height
        ):
            target = line_top - editor_viewport_height + editor_line_height
            await editor_scroll.scroll_to(offset=max(0, target), duration=120)
        page.update(editor_preview, editor_preview_container, search_status)

    async def actualizar_busqueda(_=None):
        nonlocal search_matches, active_search_match
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
            page.update(editor_preview, editor_preview_container, search_status)

    async def abrir_busqueda(_=None):
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
        page.update()
        await actualizar_busqueda()
        await search_field.focus()

    async def buscar_siguiente(_=None):
        if search_matches:
            await seleccionar_coincidencia(active_search_match + 1)

    async def buscar_anterior(_=None):
        if search_matches:
            await seleccionar_coincidencia(active_search_match - 1)

    async def cerrar_busqueda(_=None):
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
        await editor.focus()
        page.update(editor, editor_preview_container, search_bar)

    search_field = ft.TextField(
        hint_text="Buscar en el archivo",
        height=38,
        content_padding=ft.Padding.symmetric(horizontal=10, vertical=6),
        border_color=BORDER,
        focused_border_color=ACCENT,
        text_size=13,
        expand=True,
        on_change=actualizar_busqueda,
        on_submit=buscar_siguiente,
    )
    search_bar = ft.Container(
        content=ft.Row(
            [
                search_field,
                search_status,
                ft.IconButton(
                    icon=ft.Icons.KEYBOARD_ARROW_UP,
                    tooltip="Coincidencia anterior",
                    icon_color=MUTED,
                    on_click=buscar_anterior,
                ),
                ft.IconButton(
                    icon=ft.Icons.KEYBOARD_ARROW_DOWN,
                    tooltip="Coincidencia siguiente",
                    icon_color=MUTED,
                    on_click=buscar_siguiente,
                ),
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    tooltip="Cerrar búsqueda",
                    icon_color=MUTED,
                    on_click=cerrar_busqueda,
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
        if event.ctrl and event.key.lower() == "f":
            page.run_task(abrir_busqueda)

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
        return ft.Text(
            spans=dibujar_linea_terminal(row, cursor_x),
            size=13,
            font_family="Consolas",
            color="#d5deeb",
            selectable=True,
            show_selection_cursor=True,
            no_wrap=True,
            max_lines=1,
            width=terminal_content_width,
            key=key,
            on_tap=enfocar_terminal,
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
        current_control_ids = {id(control) for control in terminal_row_controls}
        for control_id in terminal_selections.keys() - current_control_ids:
            del terminal_selections[control_id]

    def dibujar_terminal():
        nonlocal rendered_history_count, rendered_history_ids
        nonlocal terminal_refocus_pending
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
                    )
                ]
            else:
                rebuild = True

        if rebuild:
            reconstruir_filas_terminal(history_rows)
        if len(terminal_row_controls) != expected_row_count:
            rebuild = True
            reconstruir_filas_terminal(history_rows)

        current_control_ids = {id(control) for control in terminal_row_controls}
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

        if rebuild or history_ids != previous_history_ids or changed_rows:
            terminal_output.controls = list(reversed(terminal_row_controls))
            page.update(terminal_output)
            if terminal_refocus_pending and terminal_has_focus:
                terminal_refocus_pending = False
                page.run_task(terminal_listener.focus)
        terminal_screen.dirty.clear()

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
        status_text.value = message
        status_text.color = "#ff7c84"
        terminal_stream.feed(f"\r\n{message}\r\n")
        dibujar_terminal()
        page.update()

    def leer_salida_terminal(
        process: PtyProcess,
        output_queue: queue.Queue[str | Exception | None],
    ):
        while process.isalive():
            try:
                output_queue.put(process.read())
            except EOFError:
                break
            except WinptyError as error:
                output_queue.put(error)
                break
            except OSError as error:
                output_queue.put(error)
                break
        output_queue.put(None)

    async def procesar_salida_terminal(
        process: PtyProcess,
        output_queue: queue.Queue[str | Exception | None],
    ):
        while shell_process is process:
            try:
                output = output_queue.get_nowait()
            except queue.Empty:
                if not process.isalive():
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

            if chunks:
                terminal_stream.feed("".join(chunks))
                dibujar_terminal()
            for error in errors:
                informar_error_terminal(f"Error al leer PowerShell: {error}")
            if finished:
                break

        if shell_process is process:
            establecer_estado("PowerShell finalizó", "#f0b45b")

    async def iniciar_powershell():
        nonlocal shell_process, terminal_stream
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
            informar_error_terminal(f"No se pudo iniciar PowerShell: {error}")
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
        page.run_task(procesar_salida_terminal, process, output_queue)
        return process

    def enviar_entrada_terminal(text: str):
        if not shell_process or not shell_process.isalive():
            establecer_estado("PowerShell no está activo", "#f0b45b")
            return
        try:
            shell_process.write(text)
        except (EOFError, OSError, WinptyError) as error:
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
        await terminal_clipboard.set(text)
        status_text.value = "Texto copiado"
        status_text.color = "#56d68b"
        page.update(status_text)

    def manejar_tecla_terminal(key: str):
        nonlocal terminal_refocus_pending
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
                for control in terminal_row_controls
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
        terminal_resize_handle = None
        if pending_terminal_size is None:
            return
        columns, rows, content_width = pending_terminal_size
        dimensions_changed = (columns, rows) != (terminal_columns, terminal_rows)
        width_changed = content_width != rendered_terminal_width
        if not dimensions_changed and not width_changed:
            return

        if dimensions_changed:
            terminal_columns, terminal_rows = columns, rows
            terminal_screen.resize(lines=rows, columns=columns)
        terminal_content_width = content_width
        rendered_terminal_width = content_width
        terminal_output.width = content_width
        if width_changed:
            if terminal_row_controls:
                reconstruir_filas_terminal(list(terminal_screen.history.top))
                terminal_output.controls = list(reversed(terminal_row_controls))
                page.update(terminal_output)

        if dimensions_changed and shell_process and shell_process.isalive():
            try:
                shell_process.setwinsize(rows, columns)
            except WinptyError as error:
                informar_error_terminal(f"No se pudo redimensionar PowerShell: {error}")
        if dimensions_changed:
            dibujar_terminal()

    def al_redimensionar_terminal(event):
        nonlocal pending_terminal_size, terminal_resize_handle
        content_width = max(1, int(event.width) - 24)
        columns = max(20, min(240, int(content_width / 7.8)))
        rows = max(3, min(80, int(event.height / 18)))
        pending_terminal_size = (columns, rows, content_width)

        if terminal_resize_handle is not None:
            terminal_resize_handle.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            aplicar_redimension_terminal()
        else:
            terminal_resize_handle = loop.call_later(0.12, aplicar_redimension_terminal)

    def finalizar_redimension_terminal(_):
        nonlocal terminal_resize_handle
        if terminal_resize_handle is not None:
            terminal_resize_handle.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            aplicar_redimension_terminal()
        else:
            terminal_resize_handle = loop.call_later(0.08, aplicar_redimension_terminal)

    def obtener_altura_maxima_terminal():
        return max(130, workspace_height + terminal_height - 130)

    def al_redimensionar_area_trabajo(event):
        nonlocal workspace_height, terminal_height
        workspace_height = event.height
        maximum = obtener_altura_maxima_terminal()
        if terminal_height > maximum:
            terminal_height = maximum
            terminal_panel.height = terminal_height
            page.update()

    def redimensionar_terminal(event):
        nonlocal terminal_height
        delta = event.primary_delta
        if delta is None and event.local_delta is not None:
            delta = event.local_delta.dy
        if delta is None:
            return
        maximum = obtener_altura_maxima_terminal()
        terminal_height = max(
            130,
            min(maximum, terminal_height - delta),
        )
        terminal_panel.height = terminal_height
        terminal_panel.update()

    async def enfocar_terminal(_):
        nonlocal terminal_has_focus, terminal_refocus_pending
        pressed_modifiers.clear()
        terminal_has_focus = True
        terminal_refocus_pending = False
        await terminal_listener.focus()
        status_text.value = "Consola enfocada"
        status_text.color = "#56d68b"
        page.update(status_text)

    def al_enfocar_editor(_):
        nonlocal terminal_has_focus, terminal_refocus_pending
        terminal_has_focus = False
        terminal_refocus_pending = False

    def detener_powershell(_):
        if shell_process and shell_process.isalive():
            shell_process.close(force=True)

    page.on_close = detener_powershell

    async def al_cambiar_editor(event):
        contents = event.data if isinstance(event.data, str) else editor.value or ""
        editor.value = contents
        actualizar_metadatos_editor()
        if search_bar.visible:
            await actualizar_busqueda()
        page.update()

    editor.on_change = al_cambiar_editor
    editor.on_focus = al_enfocar_editor
    editor.on_selection_change = al_cambiar_seleccion_editor

    def crear_fila_arbol(
        label: str,
        icon,
        depth: int,
        *,
        color: str = TEXT,
        selected: bool = False,
        on_click=None,
        leading_icon=None,
    ):
        prefix = (
            ft.Icon(leading_icon, size=16, color=MUTED)
            if leading_icon is not None
            else ft.Container(width=16)
        )
        return ft.Container(
            content=ft.Row(
                [
                    prefix,
                    ft.Icon(icon, size=16, color=color),
                    ft.Text(
                        label,
                        size=13,
                        color=TEXT if selected else color,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        expand=True,
                    ),
                ],
                spacing=7,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.only(left=8 + depth * 14, right=7, top=5, bottom=5),
            bgcolor="#294a70" if selected else "transparent",
            border_radius=4,
            on_click=on_click,
            ink=on_click is not None,
        )

    def dibujar_arbol_directorios():
        rows = []

        def agregar_directorio(path: Path, depth: int, is_root: bool = False):
            is_expanded = path in expanded_directories

            def alternar_directorio(_):
                if path in expanded_directories:
                    expanded_directories.remove(path)
                else:
                    expanded_directories.add(path)
                dibujar_arbol_directorios()

            rows.append(
                crear_fila_arbol(
                    path.name or str(path),
                    ft.Icons.FOLDER_OPEN if is_expanded else ft.Icons.FOLDER,
                    depth,
                    color="#f0c75e",
                    leading_icon=(
                        ft.Icons.KEYBOARD_ARROW_DOWN
                        if is_expanded
                        else ft.Icons.CHEVRON_RIGHT
                    ),
                    on_click=alternar_directorio,
                )
            )
            if not is_expanded:
                return

            try:
                entries = sorted(
                    path.iterdir(),
                    key=lambda entry: (not (entry.is_dir() and not entry.is_symlink()), entry.name.casefold()),
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
                rows.append(
                    crear_fila_arbol(
                        entry.name,
                        file_icon,
                        depth + 1,
                        color=BLUE if file_icon == ft.Icons.CODE else "#a9b8cb",
                        selected=entry == active_path,
                        on_click=lambda _, selected_path=entry: abrir_ruta(selected_path),
                    )
                )

        agregar_directorio(root_directory, 0, is_root=True)
        explorer_body.controls = rows
        explorer_body.update()

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
            contents = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            establecer_estado(f"No se pudo abrir {path.name}: {error}", "#ff7c84")
            return
        crear_documento(path, contents, contents)
        establecer_estado(f"Abierto · {path}", "#56d68b")

    def crear_documento(path: Path | None, contents: str, original_contents: str):
        nonlocal active_document, active_path, saved_content, next_document_id
        sincronizar_documento_activo()
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
        editor.value = contents
        actualizar_metadatos_editor()
        dibujar_arbol_directorios()
        page.update()

    def activar_documento(document_id: int):
        nonlocal active_document, active_path, saved_content
        sincronizar_documento_activo()
        document = next(
            (item for item in documents if item["id"] == document_id),
            None,
        )
        if document is None:
            return
        active_document = document
        active_path = document["path"]
        saved_content = document["saved_content"]
        editor.value = document["content"]
        actualizar_metadatos_editor()
        dibujar_arbol_directorios()
        page.update()

    def cerrar_documento_ahora(document_id: int):
        nonlocal active_document, active_path, saved_content
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
                editor.value = ""
                actualizar_metadatos_editor()
                dibujar_arbol_directorios()
                page.update()
        else:
            actualizar_metadatos_editor()
            dibujar_arbol_directorios()
            page.update()

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
        page.update()

    async def elegir_archivo(_):
        picked_files = await file_picker.pick_files(
            dialog_title="Abrir archivo",
            initial_directory=str(root_directory),
            allow_multiple=False,
        )
        if picked_files and picked_files[0].path:
            abrir_ruta(Path(picked_files[0].path))

    async def guardar_archivo(_):
        nonlocal active_path, saved_content
        if active_document is None:
            establecer_estado("No hay ningún archivo abierto", "#f0b45b")
            return
        target = active_path
        if target is None:
            selected = await file_picker.guardar_archivo(
                dialog_title="Guardar archivo",
                file_name="consulta.sql",
                initial_directory=str(root_directory),
            )
            if not selected:
                return
            target = Path(selected)
        try:
            target.write_text(editor.value or "", encoding="utf-8")
        except OSError as error:
            establecer_estado(f"No se pudo guardar {target.name}: {error}", "#ff7c84")
            return
        active_path = target
        saved_content = editor.value or ""
        active_document["path"] = target
        active_document["name"] = target.name
        active_document["content"] = saved_content
        active_document["saved_content"] = saved_content
        actualizar_metadatos_editor()
        dibujar_arbol_directorios()
        establecer_estado(f"Guardado · {target}", "#56d68b")
        page.update()

    def crear_archivo_nuevo(_):
        crear_documento(None, "", "")
        establecer_estado("Nuevo archivo", MUTED)
        page.update()

    async def animar_clic_boton(button, event, callback, pressed_color=None):
        original_color = button.bgcolor
        button.scale = ft.Scale(scale=0.90)
        if pressed_color is not None:
            button.bgcolor = pressed_color
        button.update()
        await asyncio.sleep(0.12)
        button.scale = ft.Scale(scale=1)
        button.bgcolor = original_color
        button.update()
        if callback is not None:
            result = callback(event)
            if asyncio.iscoroutine(result):
                await result

    def crear_boton_icono(icon, tooltip, on_click=None, color=MUTED):
        button = ft.IconButton(
            icon=icon,
            icon_size=18,
            icon_color=color,
            tooltip=tooltip,
            animate_scale=ft.Animation(130, ft.AnimationCurve.EASE_OUT),
        )

        async def manejar_clic(event):
            await animar_clic_boton(button, event, on_click)

        button.on_click = manejar_clic
        return button

    def crear_boton_accion(label, icon, color, on_click=None, pressed_color=None):
        button = ft.FilledButton(
            content=ft.Text(label, size=13, weight=ft.FontWeight.W_600),
            icon=icon,
            bgcolor=color,
            color=ft.Colors.WHITE,
            height=38,
            animate_scale=ft.Animation(130, ft.AnimationCurve.EASE_OUT),
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

    explorer_panel = ft.Container(
        content=ft.Column(
            [
                crear_encabezado_panel(
                    ft.Icons.FOLDER_OPEN,
                    "EXPLORADOR",
                    crear_boton_icono(ft.Icons.CREATE_NEW_FOLDER, "Abrir carpeta", elegir_carpeta),
                ),
                ft.Container(
                    content=explorer_body,
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

    editor_panel = ft.Container(
        content=ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            tabs_bar,
                            ft.PopupMenuButton(
                                icon=ft.Icons.MORE_HORIZ,
                                icon_color=MUTED,
                                tooltip="Opciones del editor",
                                items=[
                                    ft.PopupMenuItem(
                                        content="Buscar texto  Ctrl+F",
                                        icon=ft.Icons.SEARCH,
                                        on_click=abrir_busqueda,
                                    )
                                ],
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor="#151e2b",
                    padding=ft.Padding.only(left=12, right=6, top=2, bottom=2),
                    height=39,
                ),
                search_bar,
                editor_scroll,
                ft.Container(
                    content=ft.Row(
                        [
                            language_label,
                            ft.Text("UTF-8", size=11, color=MUTED),
                        ],
                        spacing=15,
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
            crear_fila_arbol(label, icon, depth, color=color)
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
        expand=True,
    )

    syntax_panel = ft.Container(
        content=ft.Column(
            [
                crear_encabezado_panel(ft.Icons.ACCOUNT_TREE, "ÁRBOL SINTÁCTICO"),
                ft.Container(
                    content=syntax_tree,
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
                ft.Container(
                    content=ft.Text(
                        "Escribe un comando de PowerShell y pulsa Enter",
                        size=10,
                        color=MUTED,
                    ),
                    padding=ft.Padding.only(left=12, top=3, bottom=4),
                    border=ft.Border.only(top=ft.BorderSide(1, BORDER)),
                    on_click=enfocar_terminal,
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
            content=ft.Container(
                height=2,
                bgcolor=BORDER,
                border_radius=2,
                width=64,
            ),
            height=8,
            alignment=ft.Alignment.CENTER,
        ),
        mouse_cursor=ft.MouseCursor.RESIZE_UP_DOWN,
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
                crear_boton_accion("Compilar", ft.Icons.PLAY_ARROW, "#0b9f99"),
                crear_boton_accion("Compilar y ejecutar", ft.Icons.PLAY_ARROW, "#e98222"),
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
    else:
        actualizar_metadatos_editor()
    page.update()
    page.run_task(iniciar_powershell)


if __name__ == "__main__":
    ft.run(iniciar_interfaz)