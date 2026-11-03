import asyncio
import shutil
import subprocess
from pathlib import Path

import flet as ft


BACKGROUND = "#101722"
PANEL = "#172232"
PANEL_LIGHT = "#203149"
HEADER = "#1c2b40"
BORDER = "#2d405b"
TEXT = "#e5edf7"
MUTED = "#93a4ba"
ACCENT = "#24b8ad"
BLUE = "#4da3ff"


def main(page: ft.Page):
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
    expanded_directories: set[Path] = set()
    shell_process = None

    file_picker = ft.FilePicker()
    page.services.append(file_picker)

    status_text = ft.Text(
        "Listo",
        size=12,
        color=MUTED,
        font_family="Segoe UI",
    )
    active_file_label = ft.Text(
        "sin_titulo.sql",
        size=13,
        color=TEXT,
        font_family="Segoe UI",
    )
    language_label = ft.Text("SQL", size=11, color=MUTED)
    root_name_label = ft.Text(
        root_directory.name,
        size=12,
        color=MUTED,
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS,
    )
    line_numbers = ft.Text(
        "1",
        size=14,
        color="#61738c",
        font_family="Consolas",
        text_align=ft.TextAlign.RIGHT,
        selectable=False,
    )
    editor = ft.TextField(
        value="",
        multiline=True,
        min_lines=1,
        max_lines=None,
        expand=True,
        border=ft.InputBorder.NONE,
        bgcolor="transparent",
        color=TEXT,
        cursor_color=ACCENT,
        selection_color="#315275",
        content_padding=ft.Padding.only(left=8, top=10, right=12, bottom=12),
        text_style=ft.TextStyle(
            font_family="Consolas",
            size=14,
            color=TEXT,
        ),
        on_change=None,
    )
    terminal_log = ft.TextField(
        value="",
        multiline=True,
        min_lines=1,
        max_lines=None,
        expand=True,
        read_only=True,
        border=ft.InputBorder.NONE,
        bgcolor="transparent",
        color="#d5deeb",
        content_padding=ft.Padding.only(left=12, top=4, right=12, bottom=4),
        text_style=ft.TextStyle(
            font_family="Consolas",
            size=13,
            color="#d5deeb",
        ),
    )
    terminal_input = ft.TextField(
        value="",
        hint_text="Escribe un comando de PowerShell y presiona Enter",
        expand=True,
        dense=True,
        border=ft.InputBorder.NONE,
        bgcolor="transparent",
        color=TEXT,
        cursor_color=ACCENT,
        content_padding=ft.Padding.only(left=8, top=7, right=8, bottom=7),
        text_style=ft.TextStyle(font_family="Consolas", size=13, color=TEXT),
    )
    explorer_body = ft.Column(
        spacing=1,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    def set_status(message: str, color: str = MUTED):
        status_text.value = message
        status_text.color = color
        page.update()

    def update_editor_metadata():
        current_path = active_path.name if active_path else "sin_titulo.sql"
        is_dirty = (editor.value or "") != saved_content
        active_file_label.value = f"{current_path}{'  ●' if is_dirty else ''}"
        language_label.value = (
            active_path.suffix[1:].upper()
            if active_path and active_path.suffix
            else "SQL"
        )
        contents = editor.value or ""
        line_numbers.value = "\n".join(
            str(number) for number in range(1, max(1, len(contents.splitlines()) + 1))
        )

    def append_terminal(text: str):
        current_lines = (terminal_log.value or "").splitlines()
        current_lines.extend(text.rstrip("\r\n").splitlines())
        terminal_log.value = "\n".join(current_lines[-400:])
        terminal_log.update()

    async def read_shell_output(process):
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            append_terminal(line.decode(errors="replace"))
        if process.returncode is None:
            await process.wait()
        if shell_process is process:
            set_status(
                f"PowerShell finalizó (código {process.returncode})",
                "#f0b45b",
            )

    async def start_powershell():
        nonlocal shell_process
        if shell_process and shell_process.returncode is None:
            return shell_process

        executable = (
            shutil.which("powershell.exe")
            or shutil.which("powershell")
            or shutil.which("pwsh")
        )
        if not executable:
            message = "No se encontró PowerShell en este equipo."
            append_terminal(message)
            set_status(message, "#ff7c84")
            return None

        try:
            shell_process = await asyncio.create_subprocess_exec(
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NoExit",
                cwd=str(root_directory),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            message = f"No se pudo iniciar PowerShell: {error}"
            append_terminal(message)
            set_status(message, "#ff7c84")
            return None

        set_status(f"PowerShell activo · {root_directory}", "#56d68b")
        page.run_task(read_shell_output, shell_process)
        return shell_process

    async def submit_terminal_command(_):
        command = (terminal_input.value or "").strip()
        if not command:
            return
        terminal_input.value = ""
        append_terminal(f"PS> {command}")
        process = await start_powershell()
        if process is None or process.stdin is None:
            page.update()
            return
        try:
            process.stdin.write((command + "\n").encode())
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as error:
            message = f"No se pudo enviar el comando a PowerShell: {error}"
            append_terminal(message)
            set_status(message, "#ff7c84")
        page.update()

    terminal_input.on_submit = submit_terminal_command

    def stop_powershell(_):
        if shell_process and shell_process.returncode is None:
            shell_process.terminate()

    page.on_close = stop_powershell

    def editor_changed(_):
        update_editor_metadata()
        page.update()

    editor.on_change = editor_changed

    def make_tree_row(
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

    def render_directory_tree():
        rows = []

        def append_directory(path: Path, depth: int, is_root: bool = False):
            is_expanded = path in expanded_directories

            def toggle_directory(_):
                if path in expanded_directories:
                    expanded_directories.remove(path)
                else:
                    expanded_directories.add(path)
                render_directory_tree()

            rows.append(
                make_tree_row(
                    path.name or str(path),
                    ft.Icons.FOLDER_OPEN if is_expanded else ft.Icons.FOLDER,
                    depth,
                    color="#f0c75e",
                    leading_icon=(
                        ft.Icons.KEYBOARD_ARROW_DOWN
                        if is_expanded
                        else ft.Icons.CHEVRON_RIGHT
                    ),
                    on_click=toggle_directory,
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
                    append_directory(entry, depth + 1)
                    continue
                file_icon = (
                    ft.Icons.CODE
                    if entry.suffix.lower() in {".py", ".sql", ".txt", ".json", ".yaml", ".yml"}
                    else ft.Icons.INSERT_DRIVE_FILE
                )
                rows.append(
                    make_tree_row(
                        entry.name,
                        file_icon,
                        depth + 1,
                        color=BLUE if file_icon == ft.Icons.CODE else "#a9b8cb",
                        selected=entry == active_path,
                        on_click=lambda _, selected_path=entry: open_path(selected_path),
                    )
                )

        append_directory(root_directory, 0, is_root=True)
        explorer_body.controls = rows
        explorer_body.update()

    def open_path(path: Path):
        nonlocal active_path, saved_content
        try:
            contents = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            set_status(f"No se pudo abrir {path.name}: {error}", "#ff7c84")
            return
        active_path = path
        saved_content = contents
        editor.value = contents
        update_editor_metadata()
        render_directory_tree()
        set_status(f"Abierto · {path}", "#56d68b")
        page.update()

    async def choose_folder(_):
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
        render_directory_tree()
        set_status(f"Carpeta raíz · {root_directory}", "#56d68b")
        process = await start_powershell()
        if process and process.stdin:
            command = str(root_directory).replace("'", "''")
            process.stdin.write(f"Set-Location -LiteralPath '{command}'\n".encode())
            await process.stdin.drain()
        page.update()

    async def choose_file(_):
        picked_files = await file_picker.pick_files(
            dialog_title="Abrir archivo",
            initial_directory=str(root_directory),
            allow_multiple=False,
        )
        if picked_files and picked_files[0].path:
            open_path(Path(picked_files[0].path))

    async def save_file(_):
        nonlocal active_path, saved_content
        target = active_path
        if target is None:
            selected = await file_picker.save_file(
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
            set_status(f"No se pudo guardar {target.name}: {error}", "#ff7c84")
            return
        active_path = target
        saved_content = editor.value or ""
        update_editor_metadata()
        render_directory_tree()
        set_status(f"Guardado · {target}", "#56d68b")
        page.update()

    def new_file(_):
        nonlocal active_path, saved_content
        active_path = None
        saved_content = ""
        editor.value = ""
        update_editor_metadata()
        render_directory_tree()
        set_status("Nuevo archivo", MUTED)
        page.update()

    def icon_button(icon, tooltip, on_click=None, color=MUTED):
        return ft.IconButton(
            icon=icon,
            icon_size=18,
            icon_color=color,
            tooltip=tooltip,
            on_click=on_click,
        )

    def action_button(label, icon, color, on_click=None):
        return ft.FilledButton(
            content=ft.Text(label, size=13, weight=ft.FontWeight.W_600),
            icon=icon,
            bgcolor=color,
            color=ft.Colors.WHITE,
            height=38,
            on_click=on_click,
        )

    def panel_heading(icon, title, trailing=None):
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
                panel_heading(
                    ft.Icons.FOLDER_OPEN,
                    "EXPLORADOR",
                    icon_button(ft.Icons.CREATE_NEW_FOLDER, "Abrir carpeta", choose_folder),
                ),
                ft.Container(
                    content=explorer_body,
                    padding=ft.Padding.only(top=5, bottom=6),
                    expand=True,
                ),
            ],
            spacing=0,
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
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.CODE, size=16, color=BLUE),
                                    active_file_label,
                                    icon_button(ft.Icons.CLOSE, "Cerrar archivo"),
                                ],
                                spacing=8,
                            ),
                            ft.Text("⋯", size=20, color=MUTED),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor="#151e2b",
                    padding=ft.Padding.only(left=12, right=6, top=2, bottom=2),
                    height=39,
                ),
                ft.Row(
                    [
                        ft.Container(
                            content=line_numbers,
                            width=42,
                            padding=ft.Padding.only(top=12, right=8),
                            alignment=ft.Alignment.TOP_RIGHT,
                        ),
                        ft.Container(
                            content=editor,
                            expand=True,
                            bgcolor="transparent",
                        ),
                    ],
                    spacing=0,
                    expand=True,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
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
            make_tree_row(label, icon, depth, color=color)
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
                panel_heading(ft.Icons.ACCOUNT_TREE, "ÁRBOL SINTÁCTICO"),
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

    terminal_panel = ft.Container(
        content=ft.Column(
            [
                panel_heading(
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
                    content=terminal_log,
                    expand=True,
                    padding=ft.Padding.only(top=3, bottom=2),
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text("PS>", size=13, color="#56d68b", font_family="Consolas"),
                            terminal_input,
                            icon_button(
                                ft.Icons.ARROW_UPWARD,
                                "Ejecutar comando",
                                submit_terminal_command,
                                ACCENT,
                            ),
                        ],
                        spacing=5,
                    ),
                    padding=ft.Padding.only(left=11, right=7, top=2, bottom=2),
                    border=ft.Border.only(top=ft.BorderSide(1, BORDER)),
                ),
            ],
            spacing=0,
            expand=True,
        ),
        height=250,
        bgcolor=PANEL,
        border=ft.Border.all(1, BORDER),
        border_radius=5,
    )

    toolbar = ft.Container(
        content=ft.Row(
            [
                action_button("Nuevo", ft.Icons.NOTE_ADD, "#2a3c53", new_file),
                action_button("Abrir archivo", ft.Icons.FOLDER_OPEN, "#2a3c53", choose_file),
                action_button("Guardar", ft.Icons.SAVE, "#2a3c53", save_file),
                ft.Container(width=4),
                action_button("Compilar", ft.Icons.PLAY_ARROW, "#0b9f99"),
                action_button("Compilar y ejecutar", ft.Icons.PLAY_ARROW, "#e98222"),
                ft.Container(expand=True),
                root_name_label,
                icon_button(ft.Icons.FOLDER_OPEN, "Seleccionar carpeta raíz", choose_folder),
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
                ft.Text("Ln 1, Col 1", size=12, color=MUTED),
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
                ),
                terminal_panel,
                status_bar,
            ],
            spacing=7,
            expand=True,
        )
    )

    expanded_directories.add(root_directory)
    render_directory_tree()
    if active_path:
        try:
            saved_content = active_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            active_path = None
            saved_content = ""
            set_status(f"No se pudo abrir el archivo inicial: {error}", "#ff7c84")
        else:
            editor.value = saved_content
    update_editor_metadata()
    page.update()
    page.run_task(start_powershell)


if __name__ == "__main__":
    ft.run(main)
