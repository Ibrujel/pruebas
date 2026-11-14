# Crosshair Overlay

Mira (crosshair) superpuesta para cualquier juego. Se dibuja en una ventana propia,
transparente y que deja pasar los clics, **sin inyectar código, sin leer ni modificar la
memoria del juego y sin capturar la pantalla**.

**Plataforma elegida: Windows 10/11 + Python 3.10+ con Qt 6 (PySide6)**, porque Windows
concentra a la gran mayoría de jugadores de PC y Qt ofrece ventanas translúcidas con
DPI por monitor, mientras que la API Win32 (vía `ctypes`) aporta lo específico: clics a
través de la ventana, posición en píxeles físicos y atajos globales con `RegisterHotKey`.

## Arquitectura

```
main.py                    Arranque: DPI, instancia única, argumentos
crosshair/
  config.py                Modelo (Profile, AppConfig) + JSON con escritura atómica (sin Qt)
  renderer.py              Dibuja la mira en una QImage en píxeles físicos (compartido)
  overlay.py               Ventana superpuesta: translúcida, encima, sin foco, clic-through
  monitors.py              Monitores en píxeles físicos (Win32 EnumDisplayMonitors / Qt)
  hotkeys.py               Atajos globales: RegisterHotKey (Windows) / pynput (otros)
  win32.py                 Envoltorios ctypes mínimos de user32/shcore
  settings_ui.py           Ventana de ajustes + vista previa en tiempo real
  app.py                   Controlador: estado, guardado diferido, bandeja, señales
```

Flujo: la interfaz o un atajo llama al controlador → modifica el perfil activo → el
`renderer` regenera la imagen (solo entonces) → la superposición se recoloca y se repinta
una vez → el JSON se guarda 400 ms después (agrupando ráfagas de cambios).

Decisiones clave:

* **Consumo mínimo:** no hay bucle de render ni FPS. La ventana mide solo lo que ocupa la
  mira (p. ej. 35×35 px), no toda la pantalla, así que el compositor de Windows apenas
  trabaja. Único temporizador: cada 2 s reafirma "siempre encima" (microsegundos de CPU).
  En reposo el uso de CPU/GPU es prácticamente 0 %.
* **Nitidez y DPI:** el proceso es *Per-Monitor DPI Aware v2* (Qt 6). La mira se dibuja en
  píxeles físicos con rectángulos de coordenadas enteras y sin suavizado; la ventana se
  coloca con `SetWindowPos` en coordenadas físicas y el pintado usa su origen real
  (`GetWindowRect`), de modo que el píxel central es exactamente `(ancho/2, alto/2)` del
  monitor aunque Windows esté al 125 % o 150 %.
* **Multi-monitor:** se elige el monitor en *Posición* (por defecto el principal); si se
  desconecta, vuelve al principal. Cambios de resolución, escalado o monitores recolocan
  la mira automáticamente.
* **Clic a través:** `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`:
  el ratón y el teclado siguen yendo al juego y la ventana no aparece en Alt+Tab.
* **Atajos:** `RegisterHotKey` es la API oficial; no instala ganchos de teclado ni ve otras
  pulsaciones (menos intrusivo y menos sospechoso para antitrampas que un *keyboard hook*).

## Funciones

* Formas combinables: cruz, punto, círculo, T (cruz sin brazo superior) y cualquier
  combinación (plantillas incluidas: Cruz + punto, Círculo + punto, Cruz + círculo, T + punto…).
* Color, opacidad, longitud, grosor, separación central, contorno (grosor y color),
  punto central (tamaño), círculo (radio y grosor).
* Desplazamiento fino X/Y en píxeles (desde la interfaz, botones de 1 px o atajos).
* Perfiles ilimitados: crear, duplicar, renombrar, eliminar y cambiar con atajos.
* Vista previa 1:1 o ampliada (hasta 8×, sin suavizado) sobre varios fondos.
* Icono en la bandeja del sistema con menú (mostrar/ocultar, perfiles, ajustes, salir).
* Instancia única y guardado automático en JSON.

Deliberadamente **no** incluye nada que dé ventaja más allá de mostrar una mira: no hay
apuntado automático, lectura de píxeles de la pantalla, detección de enemigos, macros ni
acceso a otros procesos.

## Instalación y ejecución (Windows)

1. Instala Python 3.10 o superior desde <https://www.python.org/downloads/> (marca
   *Add python.exe to PATH*).
2. Abre PowerShell en la carpeta del proyecto y crea un entorno virtual:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Instala las dependencias:

   ```powershell
   pip install -r requirements.txt
   ```

4. Ejecuta:

   ```powershell
   python main.py
   ```

   Opciones: `--minimized` (arranca solo en la bandeja) y `--config RUTA` (usa otro
   archivo de configuración, útil para una versión portable en un USB).

## Empaquetar como ejecutable (.exe)

```powershell
.\build.ps1
```

El script crea el entorno virtual, instala PyInstaller y genera `dist\CrosshairOverlay.exe`
(un único archivo, sin consola). Equivale a:

```powershell
pip install -r requirements-build.txt
pyinstaller --noconfirm --clean --onefile --windowed --name CrosshairOverlay main.py
```

Notas: con `--onefile` el arranque tarda 1-2 s (se descomprime en una carpeta temporal);
usa `--onedir` en su lugar si prefieres arranque instantáneo. Para que se inicie con
Windows, pon un acceso directo a `CrosshairOverlay.exe --minimized` en
`shell:startup` (Win+R → `shell:startup`).

Dependencias: `PySide6-Essentials` (Qt 6: QtCore, QtGui, QtWidgets), `pynput` solo fuera de
Windows y `pyinstaller` solo para empaquetar. En Windows no hacen falta más librerías.

## Atajos de teclado predeterminados

| Acción | Atajo |
|---|---|
| Mostrar / ocultar la mira | `Ctrl+Alt+X` |
| Perfil siguiente | `Ctrl+Alt+AvPág` (`PgDown`) |
| Perfil anterior | `Ctrl+Alt+RePág` (`PgUp`) |
| Mover la mira 1 px arriba / abajo / izquierda / derecha | `Ctrl+Alt+↑ / ↓ / ← / →` |
| Restablecer desplazamiento a (0, 0) | `Ctrl+Alt+Inicio` (`Home`) |
| Abrir los ajustes | `Ctrl+Alt+S` |

Se cambian en la pestaña **Atajos** (o en el JSON; `""` desactiva un atajo). Si otra
aplicación ya usa una combinación, la pestaña lo indica. En teclados con AltGr (como el
español), `Ctrl+Alt` equivale a AltGr: evita `Ctrl+Alt+número` u otras teclas que escriban
símbolos. Algunos controladores gráficos antiguos usaban `Ctrl+Alt+flechas` para rotar la
pantalla; si te pasa, cambia esos atajos o desactívalo en el panel del controlador.

## Archivo de configuración

Ubicación: `%APPDATA%\CrosshairOverlay\config.json` (macOS:
`~/Library/Application Support/CrosshairOverlay/`, Linux: `~/.config/crosshair-overlay/`).
Se guarda solo; puedes editarlo con la aplicación cerrada. Los valores fuera de rango se
corrigen al cargar y, si el archivo está dañado, se guarda una copia `config.json.bak` y se
usan los valores por defecto. Todas las medidas son píxeles físicos de pantalla. `gap` es
la distancia desde el centro hasta el inicio de cada brazo (0 = cruz sólida). `monitor`
vacío = monitor principal.

Ejemplo (con dos perfiles):

```json
{
  "version": 1,
  "visible": true,
  "show_settings_on_start": true,
  "monitor": "",
  "active_profile": 0,
  "hotkeys": {
    "toggle": "Ctrl+Alt+X",
    "next_profile": "Ctrl+Alt+PgDown",
    "prev_profile": "Ctrl+Alt+PgUp",
    "nudge_up": "Ctrl+Alt+Up",
    "nudge_down": "Ctrl+Alt+Down",
    "nudge_left": "Ctrl+Alt+Left",
    "nudge_right": "Ctrl+Alt+Right",
    "reset_offset": "Ctrl+Alt+Home",
    "open_settings": "Ctrl+Alt+S"
  },
  "profiles": [
    {
      "name": "Clásica",
      "color": "#00FF00",
      "opacity": 1.0,
      "arms": true,
      "t_style": false,
      "circle": false,
      "dot": false,
      "length": 6,
      "thickness": 2,
      "gap": 3,
      "dot_size": 2,
      "circle_radius": 10,
      "circle_thickness": 1,
      "outline": true,
      "outline_thickness": 1,
      "outline_color": "#000000",
      "offset_x": 0,
      "offset_y": 0
    },
    {
      "name": "Punto",
      "color": "#FF3030",
      "opacity": 1.0,
      "arms": false,
      "t_style": false,
      "circle": false,
      "dot": true,
      "length": 6,
      "thickness": 2,
      "gap": 3,
      "dot_size": 4,
      "circle_radius": 10,
      "circle_thickness": 1,
      "outline": true,
      "outline_thickness": 1,
      "outline_color": "#000000",
      "offset_x": 0,
      "offset_y": 0
    }
  ]
}
```

## Limitaciones y avisos importantes

* **Pantalla completa exclusiva:** en ese modo el juego toma el control directo de la
  pantalla y ninguna ventana normal se dibuja encima, así que la mira **no se verá**.
  Usa el modo **ventana sin bordes**: en las opciones de vídeo del juego busca
  *Pantalla completa (ventana)*, *Ventana sin bordes*, *Borderless* o *Windowed
  Fullscreen*. Pon la resolución del juego igual a la del escritorio para que el centro
  coincida. En Windows 11 los juegos DirectX 12/Vulkan en ventana sin bordes tienen un
  rendimiento y latencia prácticamente iguales a la pantalla completa.
* Si el juego renderiza a otra resolución o con barras negras y su centro no coincide con
  el de la pantalla, corrige con el desplazamiento X/Y.
* Algunos juegos (o su antitrampas) pueden ocultar u ordenar ventanas por encima de la suya;
  la app reafirma "siempre encima" cada 2 s, pero no puede forzarlo si el juego lo impide.
* **Seguridad y normas:** esta aplicación **no lee ni modifica la memoria del juego**, no
  inyecta DLL, no usa ganchos de teclado y no captura la pantalla: solo dibuja su propia
  ventana. Aun así, **algunos juegos competitivos, torneos o sistemas antitrampas
  prohíben las miras externas o cualquier superposición**. Revisa las normas de cada juego
  antes de usarla; la responsabilidad del uso es del usuario.

## Otras plataformas

* **Linux:** funciona en X11 (instala `pynput` para atajos; los clics atraviesan la
  ventana gracias a `WindowTransparentForInput`). En Wayland las ventanas no pueden
  posicionarse de forma absoluta ni registrar atajos globales: ejecuta con
  `QT_QPA_PLATFORM=xcb` (XWayland) o usa la superposición del compositor. Los juegos de
  Proton en ventana sin bordes funcionan igual que en Windows.
* **macOS:** funciona con `pynput` (requiere permiso de *Accesibilidad / Monitorización de
  entrada*). Para verse sobre apps en pantalla completa (Spaces) habría que fijar
  `NSWindowCollectionBehaviorCanJoinAllSpaces | FullScreenAuxiliary` vía PyObjC.
* Lo que cambiaría en un port: `win32.py` se sustituye por las APIs equivalentes (Xlib
  shape/XFixes, NSWindow `ignoresMouseEvents`), y `monitors.py` usa Qt directamente; el
  resto del código (configuración, render, interfaz) es común.
