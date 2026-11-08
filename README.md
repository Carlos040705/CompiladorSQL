# CompiladorSQL
Proyecto de la materia Compiladores 

## Pantalla del compilador

Para abrir la interfaz visual desde la carpeta del proyecto:

```powershell
python Main\pantalla_compilador.py
```

La pantalla permite explorar una carpeta, abrir y guardar archivos y usar una
terminal PowerShell interactiva integrada en Windows. La terminal usa ConPTY,
admite autocompletado con `Tab`, historial con las flechas, scrollback con la rueda
del ratón con la posición preservada al llegar al final, y altura ajustable
arrastrando el separador superior. Los botones de
compilación y el árbol sintáctico son solamente visuales por ahora. En la terminal,
`Ctrl+C` copia el texto seleccionado o interrumpe el proceso si no hay selección.
Las líneas largas del editor no se ajustan automáticamente y pueden recorrerse
horizontalmente; el explorador y el árbol sintáctico también permiten desplazarse
hacia los lados cuando su contenido excede el ancho del panel.

Instala las dependencias con `python -m pip install -r requirements.txt` antes de
abrir la interfaz. La terminal integrada requiere Windows.

## Analizador del lenguaje

Para analizar los archivos de prueba desde la raíz del proyecto:

```powershell
python Main\main.py
```

También se pueden pasar rutas de archivos DSL como argumentos. El flujo valida
errores léxicos antes de continuar con el análisis sintáctico y semántico. La
generación de SQL todavía no está implementada.

Las pruebas del analizador semántico se ejecutan con:

```powershell
python -m unittest discover -s Main -p "test_*.py"
```
























































































































































