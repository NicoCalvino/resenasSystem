"""
Interfaz gráfica del sistema de reseñas negativas.
Layout de dos columnas: configuración (izq) | estado + log + acciones (der)
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading, os, sys, json
from pathlib import Path
from datetime import datetime, timedelta

try:
    from PIL import Image as PILImage, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

sys.path.insert(0, str(Path(__file__).parent))

CONFIG_FILE = Path(__file__).parent / "config_gui.json"

# ── Paleta ────────────────────────────────────────────────────────────────────
BG        = "#F5F5F3"
WHITE     = "#FFFFFF"
DARK      = "#1A1A2E"
BORDER    = "#E0E0DC"
INNER_SEP = "#F0F0EE"
FIELD_BG  = "#FAFAF9"
MUTED     = "#AAAAAA"
C_RAPPI   = "#FF6900"
C_PEYA    = "#FA0050"
C_ML      = "#C49A00"
C_LOG_BG  = "#1A1A1A"
C_LOG_OK  = "#78C142"
C_LOG_WARN= "#FFAA44"
C_LOG_ERR = "#FF6666"
C_LOG_HEAD= "#FFFFFF"
FONT      = "Arial"


MESES_ES = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
            "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]


class CalendarPopup(tk.Toplevel):
    """
    Popup de calendario para elegir una fecha.
    target_var almacena la fecha en formato YYYY-MM-DD.
    Se abre anclado al widget 'anchor' y se cierra al elegir una fecha,
    presionar Escape, o hacer clic fuera del popup.
    """

    def __init__(self, anchor: tk.Widget, target_var: tk.StringVar):
        self._app_win    = anchor.winfo_toplevel()
        super().__init__(self._app_win)
        self.target_var  = target_var
        self._anchor     = anchor
        self._click_bind = None

        self.transient(self._app_win)
        self.resizable(False, False)
        self.wm_attributes("-topmost", True)
        self.title("")                      # sin texto en la barra de título
        self.configure(bg=WHITE)

        # Leer fecha actual del var
        try:
            cur = datetime.strptime(target_var.get(), "%Y-%m-%d")
        except ValueError:
            cur = datetime.now()

        self.sel_year   = cur.year
        self.sel_month  = cur.month
        self.sel_day    = cur.day
        self.view_year  = cur.year
        self.view_month = cur.month

        self._build()
        self._render_days()

        # Renderizar antes de posicionar para conocer el tamaño real
        self.update_idletasks()
        self._posicionar(anchor)
        self.lift()

        # Cerrar con Escape o cuando pierde el foco
        self.bind("<Escape>", lambda _: self._cerrar())
        self.bind("<FocusOut>", self._on_focus_out)
        self.protocol("WM_DELETE_WINDOW", self._cerrar)

        # Dar foco después de que el event-loop haya procesado el clic de apertura
        self.after(50, self.focus_force)

    # ── Construcción ──────────────────────────────────────────────────────────

    def _build(self):
        outer = tk.Frame(self, bg=WHITE,
                         highlightbackground=BORDER, highlightthickness=1)
        outer.pack(padx=1, pady=1)

        # Barra de navegación
        nav = tk.Frame(outer, bg=DARK)
        nav.pack(fill="x")

        tk.Button(nav, text="‹", font=(FONT, 13, "bold"),
                  bg=DARK, fg=WHITE, relief="flat", bd=0,
                  padx=10, pady=4, cursor="hand2",
                  activebackground="#2d2d4e", activeforeground=WHITE,
                  command=self._prev_month).pack(side="left")

        self.lbl_mes = tk.Label(nav, bg=DARK, fg=WHITE,
                                font=(FONT, 10, "bold"), width=18)
        self.lbl_mes.pack(side="left", expand=True)

        tk.Button(nav, text="›", font=(FONT, 13, "bold"),
                  bg=DARK, fg=WHITE, relief="flat", bd=0,
                  padx=10, pady=4, cursor="hand2",
                  activebackground="#2d2d4e", activeforeground=WHITE,
                  command=self._next_month).pack(side="right")

        # Cabecera de días de la semana
        hdr = tk.Frame(outer, bg=WHITE)
        hdr.pack(fill="x", padx=6, pady=(6, 2))
        dias = ["Lu", "Ma", "Mi", "Ju", "Vi", "Sá", "Do"]
        for i, d in enumerate(dias):
            color = "#CC6600" if i >= 5 else MUTED
            tk.Label(hdr, text=d, bg=WHITE, fg=color,
                     font=(FONT, 8, "bold"), width=4,
                     anchor="center").grid(row=0, column=i, padx=1)

        # Grid de días (se reconstruye cada vez que cambia el mes)
        self.grid_frame = tk.Frame(outer, bg=WHITE)
        self.grid_frame.pack(padx=6, pady=(0, 8))

        # Pie: botón Hoy
        pie = tk.Frame(outer, bg=WHITE,
                       highlightbackground=INNER_SEP, highlightthickness=1)
        pie.pack(fill="x")
        tk.Button(pie, text="Hoy", font=(FONT, 8),
                  bg=WHITE, fg="#555555", relief="flat", bd=0,
                  padx=0, pady=4, cursor="hand2",
                  activebackground=INNER_SEP,
                  command=self._ir_hoy).pack()

    def _render_days(self):
        import calendar
        for w in self.grid_frame.winfo_children():
            w.destroy()

        self.lbl_mes.config(
            text=f"{MESES_ES[self.view_month - 1]}  {self.view_year}")

        hoy = datetime.now()
        semanas = calendar.monthcalendar(self.view_year, self.view_month)

        for s_i, semana in enumerate(semanas):
            for d_i, dia in enumerate(semana):
                if dia == 0:
                    tk.Label(self.grid_frame, text="", bg=WHITE,
                             width=4, font=(FONT, 9)).grid(
                             row=s_i, column=d_i, padx=1, pady=1)
                    continue

                es_hoy = (dia == hoy.day and
                          self.view_month == hoy.month and
                          self.view_year  == hoy.year)
                es_sel = (dia == self.sel_day and
                          self.view_month == self.sel_month and
                          self.view_year  == self.sel_year)

                if es_sel:
                    bg_d, fg_d, fnt = DARK,    WHITE,     (FONT, 9, "bold")
                elif es_hoy:
                    bg_d, fg_d, fnt = C_RAPPI, WHITE,     (FONT, 9, "bold")
                else:
                    bg_d, fg_d, fnt = WHITE,   "#222222", (FONT, 9)

                btn = tk.Button(
                    self.grid_frame, text=str(dia),
                    font=fnt, bg=bg_d, fg=fg_d,
                    relief="flat", bd=0, padx=0, pady=3,
                    width=4, cursor="hand2",
                    activebackground=INNER_SEP,
                    command=lambda d=dia: self._elegir(d),
                )
                btn.grid(row=s_i, column=d_i, padx=1, pady=1)

                if not es_sel and not es_hoy:
                    btn.bind("<Enter>", lambda e, b=btn: b.config(bg=INNER_SEP))
                    btn.bind("<Leave>", lambda e, b=btn: b.config(bg=WHITE))

    # ── Navegación ────────────────────────────────────────────────────────────

    def _prev_month(self):
        if self.view_month == 1:
            self.view_month, self.view_year = 12, self.view_year - 1
        else:
            self.view_month -= 1
        self._render_days()

    def _next_month(self):
        if self.view_month == 12:
            self.view_month, self.view_year = 1, self.view_year + 1
        else:
            self.view_month += 1
        self._render_days()

    def _ir_hoy(self):
        hoy = datetime.now()
        self.view_year, self.view_month = hoy.year, hoy.month
        self._render_days()

    # ── Selección ─────────────────────────────────────────────────────────────

    def _elegir(self, dia):
        self.sel_day   = dia
        self.sel_month = self.view_month
        self.sel_year  = self.view_year
        self.target_var.set(
            f"{self.sel_year:04d}-{self.sel_month:02d}-{self.sel_day:02d}")
        self._cerrar()

    # ── Cierre limpio ─────────────────────────────────────────────────────────

    def _cerrar(self):
        """Destruye el popup de forma segura."""
        try:
            self.destroy()
        except tk.TclError:
            pass

    def _on_focus_out(self, event):
        """
        Cierra el popup cuando el foco sale de él.
        Usa un pequeño delay para que los clics sobre sus propios
        widgets (botones de día, navegación) no lo cierren prematuramente.
        """
        self.after(120, self._check_foco)

    def _check_foco(self):
        """Destruye el popup solo si el foco realmente salió de él."""
        try:
            foco = self.focus_get()
            # Recorrer la jerarquía del widget con foco
            w = foco
            while w is not None:
                if w is self:
                    return          # el foco sigue dentro del popup
                w = getattr(w, "master", None)
            self._cerrar()
        except tk.TclError:
            pass

    # ── Posicionamiento ───────────────────────────────────────────────────────

    def _posicionar(self, anchor: tk.Widget):
        self.update_idletasks()
        ax = anchor.winfo_rootx()
        ay = anchor.winfo_rooty() + anchor.winfo_height() + 2
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        pw = self.winfo_reqwidth()
        ph = self.winfo_reqheight()
        # Ajustar para no salirse de pantalla
        x = min(ax, sw - pw - 4)
        y = ay if ay + ph < sh else anchor.winfo_rooty() - ph - 2
        self.geometry(f"+{x}+{y}")


# ── Helper: campo de fecha con selector de calendario ─────────────────────────

def date_picker_field(parent, label_text: str, var: tk.StringVar) -> tk.Frame:
    """
    Devuelve un Frame con label + campo readonly + botón de calendario.
    var almacena la fecha en YYYY-MM-DD; se muestra en DD/MM/YYYY.
    """
    f = tk.Frame(parent, bg=WHITE)
    f.columnconfigure(0, weight=1)

    tk.Label(f, text=label_text.upper(), bg=WHITE, fg=MUTED,
             font=(FONT, 8, "bold")).pack(anchor="w")

    row2 = tk.Frame(f, bg=WHITE)
    row2.pack(fill="x")
    row2.columnconfigure(0, weight=1)

    # StringVar de visualización (DD/MM/YYYY)
    disp = tk.StringVar()

    def _sync_display(*_):
        try:
            d = datetime.strptime(var.get(), "%Y-%m-%d")
            disp.set(d.strftime("%d / %m / %Y"))
        except ValueError:
            disp.set(var.get())

    var.trace_add("write", _sync_display)
    _sync_display()

    entry = tk.Entry(row2, textvariable=disp,
                     font=(FONT, 11), bg=FIELD_BG, fg="#222222",
                     relief="flat",
                     highlightbackground=BORDER, highlightthickness=1,
                     state="readonly", readonlybackground=FIELD_BG,
                     cursor="hand2")
    entry.grid(row=0, column=0, sticky="ew", ipady=5)

    _popup_ref = [None]   # referencia mutable para evitar doble apertura

    def _abrir(anchor=entry):
        # Si ya hay un popup abierto para este campo, cerrarlo primero
        if _popup_ref[0] is not None:
            try:
                _popup_ref[0]._cerrar()
            except Exception:
                pass
        popup = CalendarPopup(anchor, var)
        _popup_ref[0] = popup
        # Limpiar referencia cuando el popup se destruya
        popup.bind("<Destroy>", lambda _: _popup_ref.__setitem__(0, None))

    cal_btn = tk.Button(row2, text="▦", font=(FONT, 11),
                        bg=DARK, fg=WHITE,
                        relief="flat", bd=0,
                        padx=9, pady=0, cursor="hand2",
                        activebackground="#2d2d4e", activeforeground=WHITE,
                        highlightthickness=0,
                        command=_abrir)
    cal_btn.grid(row=0, column=1, padx=(4, 0), ipady=5)

    # Clic en el entry también abre el calendario
    entry.bind("<Button-1>", lambda _: _abrir())

    return f


def _load_img(path, max_h=24):
    """Carga una imagen PNG y la redimensiona manteniendo aspecto."""
    if not _PIL_OK:
        return None
    try:
        img = PILImage.open(path).convert("RGBA")
        w, h = img.size
        new_w = max(1, int(w * max_h / h))
        img = img.resize((new_w, max_h), PILImage.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def _set_widgets_state(frame, state):
    """Activa o desactiva recursivamente todos los widgets de un frame."""
    bg = WHITE if state == "normal" else "#F0F0EE"
    try:
        frame.configure(bg=bg)
    except Exception:
        pass
    for child in frame.winfo_children():
        try:
            child.configure(state=state)
        except Exception:
            pass
        try:
            child.configure(bg=bg)
        except Exception:
            pass
        _set_widgets_state(child, state)


class Card(tk.Frame):
    """Card con header coloreado y cuerpo blanco. Soporta toggle de activación."""
    def __init__(self, parent, title, dot_color, logo_photo=None,
                 enabled_var=None, **kwargs):
        super().__init__(parent, bg=WHITE, relief="flat",
                         highlightbackground=BORDER, highlightthickness=1,
                         **kwargs)
        self._enabled_var = enabled_var

        # Header
        self.hdr = tk.Frame(self, bg=WHITE,
                            highlightbackground=INNER_SEP, highlightthickness=1)
        self.hdr.pack(fill="x")
        hdr = self.hdr
        tk.Canvas(hdr, width=8, height=8, bg=WHITE,
                  highlightthickness=0).pack(side="left", padx=(12,4), pady=10)
        # dot
        c = tk.Canvas(hdr, width=8, height=8, bg=WHITE, highlightthickness=0)
        c.pack(side="left", padx=(0,6), pady=10)
        c.create_oval(1, 1, 7, 7, fill=dot_color, outline=dot_color)
        tk.Label(hdr, text=title, bg=WHITE, fg="#555555",
                 font=(FONT, 9, "bold")).pack(side="left", pady=10)

        # Toggle opcional en el header
        if enabled_var is not None:
            tk.Checkbutton(hdr, text="Activado", variable=enabled_var,
                           bg=WHITE, fg=MUTED, font=(FONT, 8),
                           activebackground=WHITE, selectcolor=WHITE,
                           cursor="hand2",
                           command=self._on_toggle).pack(side="right", padx=12)

        # Logo opcional en el lado derecho del header
        if logo_photo:
            lbl = tk.Label(hdr, image=logo_photo, bg=WHITE)
            lbl.image = logo_photo
            lbl.pack(side="right", padx=(12 if enabled_var is None else 0), pady=6)

        # Body frame
        self.body = tk.Frame(self, bg=WHITE)
        self.body.pack(fill="both", expand=True, padx=14, pady=10)

    def _on_toggle(self):
        """Activa o desactiva visualmente el cuerpo de la card."""
        if self._enabled_var is None:
            return
        state = "normal" if self._enabled_var.get() else "disabled"
        _set_widgets_state(self.body, state)


def labeled_entry(parent, label_text, var, row, show=None, colspan=1):
    """Campo con label pequeño arriba."""
    f = tk.Frame(parent, bg=WHITE)
    f.grid(row=row, column=0, columnspan=colspan, sticky="ew",
           pady=(0, 8))
    parent.columnconfigure(0, weight=1)
    tk.Label(f, text=label_text.upper(), bg=WHITE, fg=MUTED,
             font=(FONT, 8, "bold")).pack(anchor="w")
    kwargs = dict(textvariable=var, font=(FONT, 11), bg=FIELD_BG,
                  fg="#222222", relief="flat",
                  highlightbackground=BORDER, highlightthickness=1)
    if show:
        kwargs["show"] = show
    e = tk.Entry(f, **kwargs)
    e.pack(fill="x", ipady=5)
    return e


def labeled_file(parent, label_text, var, row, is_dir=False):
    """Campo con label y botón Elegir."""
    f = tk.Frame(parent, bg=WHITE)
    f.grid(row=row, column=0, sticky="ew", pady=(0, 8))
    parent.columnconfigure(0, weight=1)
    tk.Label(f, text=label_text.upper(), bg=WHITE, fg=MUTED,
             font=(FONT, 8, "bold")).pack(anchor="w")
    row2 = tk.Frame(f, bg=WHITE)
    row2.pack(fill="x")
    row2.columnconfigure(0, weight=1)
    e = tk.Entry(row2, textvariable=var, font=(FONT, 10), bg=FIELD_BG,
                 fg="#888888", relief="flat",
                 highlightbackground=BORDER, highlightthickness=1)
    e.grid(row=0, column=0, sticky="ew", ipady=4)

    def elegir():
        if is_dir:
            p = filedialog.askdirectory(title=label_text)
        else:
            p = filedialog.askopenfilename(title=label_text,
                                           filetypes=[("CSV", "*.csv"), ("Todos", "*")])
        if p:
            var.set(p)

    tk.Button(row2, text="Elegir", command=elegir,
              font=(FONT, 9), bg=BG, fg="#444444",
              relief="flat", highlightbackground=BORDER,
              highlightthickness=1, padx=10, cursor="hand2").grid(
              row=0, column=1, padx=(5,0))


# ── Diálogo de edición / creación de un local ────────────────────────────────

class EditDialog(tk.Toplevel):
    """Diálogo modal para crear o editar un local."""

    MARCAS = ["Las Gracias", "Tea Connection", "Green Eat"]

    def __init__(self, parent, data, on_save):
        super().__init__(parent)
        self.on_save = on_save
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.configure(bg=WHITE)

        is_new = data is None
        self.title("Nuevo local" if is_new else "Editar local")

        self._vars = {
            "nombre":    tk.StringVar(value=data.get("nombre", "")      if data else ""),
            "marca":     tk.StringVar(value=data.get("marca", "")       if data else ""),
            "grupo":     tk.StringVar(value=data.get("grupo", "")       if data else ""),
            "py_id":     tk.StringVar(value=str(data.get("py_id") or "")    if data else ""),
            "rappi_id":  tk.StringVar(value=str(data.get("rappi_id") or "") if data else ""),
            "mp_nombre": tk.StringVar(value=data.get("mp_nombre") or ""     if data else ""),
        }

        self._build()
        self.update_idletasks()
        pw = parent.winfo_rootx() + parent.winfo_width()  // 2
        ph = parent.winfo_rooty() + parent.winfo_height() // 2
        w  = self.winfo_reqwidth()
        h  = self.winfo_reqheight()
        self.geometry(f"+{pw - w//2}+{ph - h//2}")

    def _build(self):
        f = tk.Frame(self, bg=WHITE, padx=26, pady=20)
        f.pack()

        fields = [
            ("Nombre",       "nombre",    False),
            ("Marca",        "marca",     True),
            ("Grupo",        "grupo",     False),
            ("PedidosYa ID", "py_id",     False),
            ("Rappi ID",     "rappi_id",  False),
            ("Nombre en MP", "mp_nombre", False),
        ]

        for row, (label, key, is_combo) in enumerate(fields):
            top_pad = (10, 0) if row > 0 else (0, 0)
            tk.Label(f, text=label.upper(), bg=WHITE, fg=MUTED,
                     font=(FONT, 8, "bold")).grid(
                     row=row * 2, column=0, sticky="w", pady=top_pad)
            if is_combo:
                cb = ttk.Combobox(f, textvariable=self._vars[key],
                                  values=self.MARCAS, state="normal",
                                  font=(FONT, 10), width=37)
                cb.grid(row=row * 2 + 1, column=0, sticky="ew", ipady=3)
            else:
                tk.Entry(f, textvariable=self._vars[key],
                         font=(FONT, 10), bg=FIELD_BG, fg="#222",
                         relief="flat", highlightbackground=BORDER,
                         highlightthickness=1, width=40).grid(
                         row=row * 2 + 1, column=0, sticky="ew", ipady=5)

        btn_f = tk.Frame(f, bg=WHITE)
        btn_f.grid(row=len(fields) * 2 + 1, column=0, sticky="ew", pady=(18, 0))
        btn_f.columnconfigure(0, weight=1)
        btn_f.columnconfigure(1, weight=1)

        tk.Button(btn_f, text="Cancelar", font=(FONT, 10),
                  bg=WHITE, fg="#555", relief="flat",
                  highlightbackground=BORDER, highlightthickness=1,
                  padx=16, pady=7, cursor="hand2",
                  command=self.destroy).grid(row=0, column=0, padx=(0, 8), sticky="ew")

        tk.Button(btn_f, text="Guardar", font=(FONT, 10, "bold"),
                  bg=DARK, fg=WHITE, relief="flat", bd=0,
                  padx=16, pady=7, cursor="hand2",
                  activebackground="#2d2d4e", activeforeground=WHITE,
                  command=self._save).grid(row=0, column=1, sticky="ew")

    def _save(self):
        nombre = self._vars["nombre"].get().strip()
        if not nombre:
            messagebox.showerror("Falta nombre", "El nombre es obligatorio.", parent=self)
            return

        def _to_int(v):
            v = v.strip()
            if not v:
                return None
            try:
                return int(v)
            except ValueError:
                messagebox.showerror("ID inválido",
                                     f"'{v}' no es un número entero válido.", parent=self)
                return "ERR"

        py_id    = _to_int(self._vars["py_id"].get())
        rappi_id = _to_int(self._vars["rappi_id"].get())
        if py_id == "ERR" or rappi_id == "ERR":
            return

        data = {
            "nombre":    nombre,
            "marca":     self._vars["marca"].get().strip(),
            "grupo":     self._vars["grupo"].get().strip(),
            "py_id":     py_id,
            "rappi_id":  rappi_id,
            "mp_nombre": self._vars["mp_nombre"].get().strip() or None,
        }
        self.on_save(data)
        self.destroy()


# ── Ventana de gestión de locales ─────────────────────────────────────────────

class LocalesWindow(tk.Toplevel):
    """
    Ventana de consulta de locales (solo lectura).
    Los datos se obtienen desde Google Sheets via sheets_sync (caché → hardcoded).
    Para modificar los locales, editar directamente el Google Sheet configurado.
    """

    COLS = [
        ("nombre",    "Nombre",        300),
        ("marca",     "Marca",         130),
        ("grupo",     "Grupo",         120),
        ("py_id",     "PedidosYa ID",   95),
        ("rappi_id",  "Rappi ID",        85),
        ("mp_nombre", "Nombre MP",      220),
    ]

    _CACHE_FILE  = Path(__file__).parent / "config" / "cache_sheets.json"
    _CONFIG_FILE = Path(__file__).parent / "config_gui.json"

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Locales")
        self.geometry("1060x620")
        self.minsize(800, 440)
        self.configure(bg=BG)
        self.transient(parent)

        self._load_data()
        self._build_ui()

    # ── Datos ─────────────────────────────────────────────────────────────────

    def _load_data(self):
        sys.path.insert(0, str(Path(__file__).parent))
        from config.locales import TIENDAS
        self._tiendas = list(TIENDAS)

    def _sheets_status(self) -> tuple[str, str, str]:
        """Devuelve (icono, color, texto) para el label de fuente."""
        # ¿Hay sheets_id configurado?
        sheets_id = ""
        if self._CONFIG_FILE.exists():
            try:
                cfg = json.loads(self._CONFIG_FILE.read_text(encoding="utf-8"))
                sheets_id = cfg.get("sheets_id", "").strip()
            except Exception:
                pass

        if not sheets_id:
            return ("⚠", "#993300",
                    "Google Sheets no configurado — usando datos hardcodeados. "
                    "Agregá SHEETS_ID=<id> en el archivo .env para activarlo.")

        if self._CACHE_FILE.exists():
            try:
                cache = json.loads(self._CACHE_FILE.read_text(encoding="utf-8"))
                ts = cache.get("ultima_actualizacion", "fecha desconocida")
                return ("🌐", "#1a6b2a",
                        f"Datos desde Google Sheets  ·  última actualización: {ts}")
            except Exception:
                pass

        return ("⚠", "#7A5500",
                "Google Sheets configurado — sin caché aún (se actualizará al próximo proceso)")

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=WHITE,
                       highlightbackground=BORDER, highlightthickness=1)
        hdr.pack(fill="x", padx=14, pady=(14, 0))

        logo = tk.Frame(hdr, bg=DARK, width=34, height=34)
        logo.pack(side="left", padx=14, pady=10)
        logo.pack_propagate(False)
        tk.Label(logo, text="GL", bg=DARK, fg=WHITE,
                 font=(FONT, 9, "bold")).pack(expand=True)

        tk.Label(hdr, text="Locales", bg=WHITE, fg=DARK,
                 font=(FONT, 12, "bold")).pack(side="left")

        tk.Label(hdr, text="· solo lectura  ·  para editar, modificar el Google Sheet",
                 bg=WHITE, fg=MUTED, font=(FONT, 9)).pack(side="left", padx=8)

        # ── Barra de estado de fuente ──────────────────────────────────────────
        self._fuente_frame = tk.Frame(self, bg=BG)
        self._fuente_frame.pack(fill="x", padx=14, pady=(6, 0))
        ico, color, txt = self._sheets_status()
        tk.Label(self._fuente_frame, text=f"{ico}  {txt}",
                 bg=BG, fg=color, font=(FONT, 8), anchor="w").pack(side="left")

        # ── Barra de búsqueda ─────────────────────────────────────────────────
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=14, pady=(6, 6))

        tk.Label(bar, text="Buscar:", bg=BG, fg="#555",
                 font=(FONT, 9)).pack(side="left", padx=(0, 6))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter())
        tk.Entry(bar, textvariable=self._search_var, font=(FONT, 10),
                 bg=FIELD_BG, fg="#222", relief="flat",
                 highlightbackground=BORDER, highlightthickness=1,
                 width=32).pack(side="left", ipady=4)

        self._lbl_count = tk.Label(bar, bg=BG, fg=MUTED, font=(FONT, 9))
        self._lbl_count.pack(side="left", padx=12)

        # ── Tabla ─────────────────────────────────────────────────────────────
        tree_f = tk.Frame(self, bg=BG)
        tree_f.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        style = ttk.Style()
        style.configure("Loc.Treeview",         font=(FONT, 9),  rowheight=26)
        style.configure("Loc.Treeview.Heading", font=(FONT, 9, "bold"))
        style.map("Loc.Treeview",
                  background=[("selected", DARK)],
                  foreground=[("selected", WHITE)])

        self.tree = ttk.Treeview(
            tree_f,
            columns=[c[0] for c in self.COLS],
            show="headings",
            style="Loc.Treeview",
            selectmode="browse",
        )
        for col_id, col_label, col_w in self.COLS:
            self.tree.heading(col_id, text=col_label,
                              command=lambda c=col_id: self._sort(c))
            self.tree.column(col_id, width=col_w, minwidth=60)

        vsb = ttk.Scrollbar(tree_f, orient="vertical",   command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_f, orient="horizontal",  command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_f.rowconfigure(0, weight=1)
        tree_f.columnconfigure(0, weight=1)

        self._populate()

    # ── Tabla ─────────────────────────────────────────────────────────────────

    def _row_vals(self, t):
        return (
            t.get("nombre", ""),
            t.get("marca",  ""),
            t.get("grupo",  ""),
            "" if t.get("py_id")     is None else t["py_id"],
            "" if t.get("rappi_id")  is None else t["rappi_id"],
            "" if t.get("mp_nombre") is None else t["mp_nombre"],
        )

    def _populate(self, filter_str=""):
        for item in self.tree.get_children():
            self.tree.delete(item)
        f = filter_str.lower()
        count = 0
        for i, t in enumerate(self._tiendas):
            if f and not any(f in str(v).lower() for v in t.values() if v):
                continue
            self.tree.insert("", "end", iid=str(i), values=self._row_vals(t))
            count += 1
        total = len(self._tiendas)
        self._lbl_count.config(
            text=f"{count} de {total} local{'es' if total != 1 else ''}")

    def _filter(self):
        self._populate(self._search_var.get())

    def _sort(self, col):
        data = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        data.sort(key=lambda x: str(x[0]).lower())
        for idx, (_, k) in enumerate(data):
            self.tree.move(k, "", idx)



class KeywordsGravesWindow(tk.Toplevel):
    """
    Ventana de consulta de palabras clave de errores graves (solo lectura).
    Los datos se obtienen desde Google Sheets via sheets_sync (caché → hardcoded).
    Para modificar las palabras clave, editar directamente el Google Sheet configurado.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Palabras de Errores Graves")
        self.geometry("460x500")
        self.minsize(360, 360)
        self.configure(bg=BG)
        self.transient(parent)

        sys.path.insert(0, str(Path(__file__).parent))
        from config.locales import KEYWORDS_GRAVES
        self._keywords = sorted(set(KEYWORDS_GRAVES))
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=WHITE,
                       highlightbackground=BORDER, highlightthickness=1)
        hdr.pack(fill="x", padx=14, pady=(14, 0))

        logo = tk.Frame(hdr, bg="#CC3333", width=34, height=34)
        logo.pack(side="left", padx=14, pady=10)
        logo.pack_propagate(False)
        tk.Label(logo, text="EG", bg="#CC3333", fg=WHITE,
                 font=(FONT, 9, "bold")).pack(expand=True)

        tk.Label(hdr, text="Palabras de Errores Graves", bg=WHITE, fg=DARK,
                 font=(FONT, 12, "bold")).pack(side="left")

        tk.Label(hdr, text="· solo lectura",
                 bg=WHITE, fg=MUTED, font=(FONT, 9)).pack(side="left", padx=8)

        # Info
        info_f = tk.Frame(self, bg="#FFF3E0",
                          highlightbackground="#FFCC80", highlightthickness=1)
        info_f.pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(
            info_f,
            text=(
                "⚠  Las reseñas que contengan estas palabras (o prefijos) se marcarán\n"
                "   como errores graves y se resaltarán en el informe Excel.\n"
                "   Para modificar la lista, editá la hoja Keywords en el Google Sheet."
            ),
            bg="#FFF3E0", fg="#7A4000", font=(FONT, 9),
            justify="left",
        ).pack(padx=12, pady=8, anchor="w")

        # Contador
        self._lbl_count = tk.Label(self, bg=BG, fg=MUTED, font=(FONT, 9), anchor="w")
        self._lbl_count.pack(fill="x", padx=14, pady=(8, 2))

        # Listbox
        list_f = tk.Frame(self, bg=BG)
        list_f.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        self._listbox = tk.Listbox(
            list_f,
            font=(FONT, 10),
            bg=WHITE,
            fg="#222222",
            selectbackground=DARK,
            selectforeground=WHITE,
            relief="flat",
            highlightbackground=BORDER,
            highlightthickness=1,
            activestyle="none",
            bd=0,
        )
        vsb = ttk.Scrollbar(list_f, orient="vertical", command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=vsb.set)
        self._listbox.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self._populate()

    # ── Tabla ─────────────────────────────────────────────────────────────────

    def _populate(self):
        self._listbox.delete(0, "end")
        for kw in sorted(self._keywords):
            self._listbox.insert("end", f"  {kw}")
        n = len(self._keywords)
        self._lbl_count.config(text=f"{n} palabra{'s' if n != 1 else ''}")


class ResenaApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Informes de Reseñas")
        self.geometry("1220x750")
        self.minsize(860, 560)
        self.configure(bg=BG)

        self.rappi_enabled  = tk.BooleanVar(value=True)
        self.peya_enabled   = tk.BooleanVar(value=True)
        self.ml_enabled     = tk.BooleanVar(value=True)
        self.rappi_email    = tk.StringVar()
        self.rappi_password = tk.StringVar()
        self.recordar_pass  = tk.BooleanVar(value=False)
        self.peya_email     = tk.StringVar()
        self.peya_password  = tk.StringVar()
        self.recordar_peya  = tk.BooleanVar(value=False)
        self.fecha_desde    = tk.StringVar()
        self.fecha_hasta    = tk.StringVar()
        self.ml_resenas     = tk.StringVar()
        self.ml_totales     = tk.StringVar()
        self.ml_reclamos    = tk.StringVar()
        self.output_dir     = tk.StringVar(value="./informes")
        self.excel_path     = tk.StringVar()
        self.running        = False
        self._proc          = None
        self._peya_proc     = None

        self._cargar_config()
        ayer = datetime.now() - timedelta(days=1)
        dia_semana_ayer = ayer.weekday()  # 0=Lun … 4=Vie, 5=Sab, 6=Dom
        if dia_semana_ayer == 5:          # ayer fue sábado → DESDE = viernes
            ultimo_habil = ayer - timedelta(days=1)
        elif dia_semana_ayer == 6:        # ayer fue domingo → DESDE = viernes
            ultimo_habil = ayer - timedelta(days=2)
        else:
            ultimo_habil = ayer
        self.fecha_desde.set(ultimo_habil.strftime("%Y-%m-%d"))
        self.fecha_hasta.set(ayer.strftime("%Y-%m-%d"))

        self._build_ui()

    # ── Config ────────────────────────────────────────────────────────────────

    def _cargar_config(self):
        if CONFIG_FILE.exists():
            try:
                cfg = json.loads(CONFIG_FILE.read_text())
                self.rappi_email.set(cfg.get("rappi_email", ""))
                if cfg.get("recordar_pass") and cfg.get("rappi_password"):
                    self.rappi_password.set(cfg["rappi_password"])
                    self.recordar_pass.set(True)
                self.peya_email.set(cfg.get("peya_email", ""))
                if cfg.get("recordar_peya") and cfg.get("peya_password"):
                    self.peya_password.set(cfg["peya_password"])
                    self.recordar_peya.set(True)
                self.output_dir.set(cfg.get("output_dir", "./informes"))
                self.fecha_desde.set(cfg.get("fecha_desde", ""))
                self.fecha_hasta.set(cfg.get("fecha_hasta", ""))
            except Exception:
                pass

    def _guardar_config(self):
        # Leer config existente para no perder claves desconocidas (ej: sheets_id)
        cfg = {}
        if CONFIG_FILE.exists():
            try:
                cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass

        cfg.update({
            "rappi_email":   self.rappi_email.get(),
            "output_dir":    self.output_dir.get(),
            "recordar_pass": self.recordar_pass.get(),
            "peya_email":    self.peya_email.get(),
            "recordar_peya": self.recordar_peya.get(),
            "fecha_desde":   self.fecha_desde.get(),
            "fecha_hasta":   self.fecha_hasta.get(),
        })
        if self.recordar_pass.get():
            cfg["rappi_password"] = self.rappi_password.get()
        if self.recordar_peya.get():
            cfg["peya_password"] = self.peya_password.get()
        CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False))

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Cargar logos ──────────────────────────────────────────────────────
        self._photos = {}  # mantener refs para evitar GC
        _logos_dir = Path(__file__).parent / "logos"

        def _limg(name, h=24):
            p = _logos_dir / f"{name}.png"
            if p.exists():
                photo = _load_img(p, h)
                if photo:
                    self._photos[name] = photo
                    return photo
            return None

        logo_rappi   = _limg("rappi",         26)
        logo_peya    = _limg("pedidosya",      26)
        logo_ml      = _limg("mercadolibre",   26)
        logo_lg      = _limg("lasgracias",     22)
        logo_tc      = _limg("teaconnection",  22)
        logo_ge      = _limg("greeneat",       22)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=WHITE,
                       highlightbackground=BORDER, highlightthickness=1)
        hdr.pack(fill="x", padx=14, pady=(14,10))
        logo = tk.Frame(hdr, bg=DARK, width=38, height=38)
        logo.pack(side="left", padx=14, pady=10)
        logo.pack_propagate(False)
        tk.Label(logo, text="IR", bg=DARK, fg=WHITE,
                 font=(FONT, 10, "bold")).pack(expand=True)
        tk.Label(hdr, text="Informes de Reseñas", bg=WHITE, fg=DARK,
                 font=(FONT, 13, "bold")).pack(side="left")

        # Botón Gestión de Locales (lado derecho del header)
        tk.Button(
            hdr, text="⚙  Locales",
            font=(FONT, 9), bg=BG, fg="#555555",
            relief="flat",
            highlightbackground=BORDER, highlightthickness=1,
            padx=12, pady=5, cursor="hand2",
            command=self._abrir_locales,
        ).pack(side="right", padx=14, pady=10)

        # Botón Palabras clave (a la izquierda del botón Locales)
        tk.Button(
            hdr, text="◈  Palabras clave",
            font=(FONT, 9), bg=BG, fg="#555555",
            relief="flat",
            highlightbackground=BORDER, highlightthickness=1,
            padx=12, pady=5, cursor="hand2",
            command=self._abrir_keywords_graves,
        ).pack(side="right", padx=(0, 0), pady=10)

        # Logos de marcas en el header
        brands_f = tk.Frame(hdr, bg=WHITE)
        brands_f.pack(side="left", padx=10)
        for i, (brand_name, brand_logo) in enumerate([
                ("Las Gracias",    logo_lg),
                ("Tea Connection", logo_tc),
                ("Green Eat",      logo_ge)]):
            if i > 0:
                tk.Label(brands_f, text="·", bg=WHITE, fg=MUTED,
                         font=(FONT, 9)).pack(side="left", padx=5)
            bf = tk.Frame(brands_f, bg=WHITE)
            bf.pack(side="left")
            if brand_logo:
                lbl = tk.Label(bf, image=brand_logo, bg=WHITE)
                lbl.image = brand_logo
                lbl.pack(side="left", padx=(0, 4))
            tk.Label(bf, text=brand_name, bg=WHITE, fg=MUTED,
                     font=(FONT, 9)).pack(side="left")

        # Columnas
        cols = tk.Frame(self, bg=BG)
        cols.pack(fill="both", expand=True, padx=14, pady=(0,14))
        cols.columnconfigure(0, weight=40)
        cols.columnconfigure(1, weight=60)

        # ── Columna izquierda ──────────────────────────────────────────────
        left = tk.Frame(cols, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0,6))

        # Badges de estado — se alojan en el header de cada tarjeta
        self._badges = {}

        # PedidosYa
        c_peya = Card(left, "PEDIDOSYA", C_PEYA, logo_photo=logo_peya,
                      enabled_var=self.peya_enabled)
        c_peya.pack(fill="x", pady=(0,8))
        _peya_badge = tk.Label(c_peya.hdr, font=(FONT, 8, "bold"), padx=7, pady=2)
        _peya_badge.pack(side="right", padx=(4, 0))
        self._badges["PedidosYa"] = _peya_badge
        self._set_badge("PedidosYa", "Automático", "#EAF3DE", "#3B6D11")
        bp = c_peya.body
        bp.columnconfigure(0, weight=1)
        bp.columnconfigure(1, weight=1)

        fpe = tk.Frame(bp, bg=WHITE)
        fpe.grid(row=0, column=0, sticky="ew", padx=(0,6), pady=(0,6))
        fpe.columnconfigure(0, weight=1)
        tk.Label(fpe, text="EMAIL", bg=WHITE, fg=MUTED,
                 font=(FONT, 8, "bold")).pack(anchor="w")
        tk.Entry(fpe, textvariable=self.peya_email, font=(FONT, 11),
                 bg=FIELD_BG, fg="#222", relief="flat",
                 highlightbackground=BORDER, highlightthickness=1).pack(
                 fill="x", ipady=5)

        fpp = tk.Frame(bp, bg=WHITE)
        fpp.grid(row=0, column=1, sticky="ew", padx=(6,0), pady=(0,6))
        fpp.columnconfigure(0, weight=1)
        tk.Label(fpp, text="CONTRASEÑA", bg=WHITE, fg=MUTED,
                 font=(FONT, 8, "bold")).pack(anchor="w")
        tk.Entry(fpp, textvariable=self.peya_password, show="●",
                 font=(FONT, 11), bg=FIELD_BG, fg="#222", relief="flat",
                 highlightbackground=BORDER, highlightthickness=1).pack(
                 fill="x", ipady=5)

        save_peya = tk.Frame(bp, bg=WHITE)
        save_peya.grid(row=1, column=0, columnspan=2, sticky="w")
        tk.Checkbutton(save_peya, text="Recordar contraseña",
                       variable=self.recordar_peya,
                       bg=WHITE, fg=MUTED, font=(FONT, 9),
                       activebackground=WHITE,
                       selectcolor=WHITE).pack(side="left")

        # Rappi
        c_rappi = Card(left, "RAPPI", C_RAPPI, logo_photo=logo_rappi,
                       enabled_var=self.rappi_enabled)
        c_rappi.pack(fill="x", pady=(0,8))
        _rappi_badge = tk.Label(c_rappi.hdr, font=(FONT, 8, "bold"), padx=7, pady=2)
        _rappi_badge.pack(side="right", padx=(4, 0))
        self._badges["Rappi"] = _rappi_badge
        self._set_badge("Rappi", "Automático", "#EAF3DE", "#3B6D11")
        b = c_rappi.body
        b.columnconfigure(0, weight=1)
        b.columnconfigure(1, weight=1)

        # email y password lado a lado
        fe = tk.Frame(b, bg=WHITE)
        fe.grid(row=0, column=0, sticky="ew", padx=(0,6), pady=(0,6))
        fe.columnconfigure(0, weight=1)
        tk.Label(fe, text="EMAIL", bg=WHITE, fg=MUTED,
                 font=(FONT, 8, "bold")).pack(anchor="w")
        tk.Entry(fe, textvariable=self.rappi_email, font=(FONT, 11),
                 bg=FIELD_BG, fg="#222", relief="flat",
                 highlightbackground=BORDER, highlightthickness=1).pack(
                 fill="x", ipady=5)

        fp = tk.Frame(b, bg=WHITE)
        fp.grid(row=0, column=1, sticky="ew", padx=(6,0), pady=(0,6))
        fp.columnconfigure(0, weight=1)
        tk.Label(fp, text="CONTRASEÑA", bg=WHITE, fg=MUTED,
                 font=(FONT, 8, "bold")).pack(anchor="w")
        tk.Entry(fp, textvariable=self.rappi_password, show="●",
                 font=(FONT, 11), bg=FIELD_BG, fg="#222", relief="flat",
                 highlightbackground=BORDER, highlightthickness=1).pack(
                 fill="x", ipady=5)

        save_f = tk.Frame(b, bg=WHITE)
        save_f.grid(row=1, column=0, columnspan=2, sticky="w")
        tk.Checkbutton(save_f, text="Recordar contraseña",
                       variable=self.recordar_pass,
                       bg=WHITE, fg=MUTED, font=(FONT, 9),
                       activebackground=WHITE,
                       selectcolor=WHITE).pack(side="left")

        # Mercado Libre
        c_ml = Card(left, "MERCADO LIBRE", C_ML, logo_photo=logo_ml,
                    enabled_var=self.ml_enabled)
        c_ml.pack(fill="x", pady=(0,8))
        _ml_badge = tk.Label(c_ml.hdr, font=(FONT, 8, "bold"), padx=7, pady=2)
        _ml_badge.pack(side="right", padx=(4, 0))
        self._badges["Mercado Libre"] = _ml_badge
        self._set_badge("Mercado Libre", "Sin CSV", "#F5F5F3", "#888888")
        labeled_file(c_ml.body, "CSV reseñas",   self.ml_resenas,  row=0)
        labeled_file(c_ml.body, "CSV totales",   self.ml_totales,  row=1)

        # Período
        c_per = Card(left, "PERÍODO", DARK)
        c_per.pack(fill="x")
        c_per.body.columnconfigure(0, weight=1)
        c_per.body.columnconfigure(1, weight=1)

        fd = date_picker_field(c_per.body, "Desde", self.fecha_desde)
        fd.grid(row=0, column=0, sticky="ew", padx=(0,6), pady=(0,6))

        fh = date_picker_field(c_per.body, "Hasta", self.fecha_hasta)
        fh.grid(row=0, column=1, sticky="ew", padx=(6,0), pady=(0,6))

        # ── Columna derecha ────────────────────────────────────────────────
        right = tk.Frame(cols, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(6,0))

        # Carpeta de salida
        c_salida = Card(right, "CARPETA DE SALIDA", DARK)
        c_salida.pack(fill="x", pady=(0,8))
        c_salida.body.columnconfigure(0, weight=1)
        labeled_file(c_salida.body, "Carpeta de salida",
                     self.output_dir, row=0, is_dir=True)

        # Log
        c_log = Card(right, "REGISTRO", "#888888")
        c_log.pack(fill="both", expand=True, pady=(0,8))
        self.log = tk.Text(c_log.body, height=12,
                           font=("Consolas", 9),
                           bg=C_LOG_BG, fg="#AAAAAA",
                           relief="flat", bd=0,
                           insertbackground="white",
                           state="disabled")
        self.log.pack(fill="both", expand=True)
        self.log.tag_config("ok",   foreground=C_LOG_OK)
        self.log.tag_config("warn", foreground=C_LOG_WARN)
        self.log.tag_config("error",foreground=C_LOG_ERR)
        self.log.tag_config("head", foreground=C_LOG_HEAD)
        self.log.tag_config("info", foreground="#AAAAAA")

        # Barra de progreso
        prog_f = tk.Frame(c_log.body, bg=WHITE)
        prog_f.pack(fill="x", pady=(6,0))
        self.progress_var = tk.DoubleVar()
        self.progress = ttk.Progressbar(prog_f, variable=self.progress_var,
                                        maximum=100)
        self.progress.pack(fill="x")
        self.status_lbl = tk.Label(prog_f, text="Listo para iniciar.",
                                   bg=WHITE, fg=MUTED, font=(FONT, 9),
                                   anchor="w")
        self.status_lbl.pack(fill="x", pady=(3,0))

        # Botones — grilla 2×2
        btn_frame = tk.Frame(right, bg=BG)
        btn_frame.pack(fill="x")
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)

        self.btn = tk.Button(
            btn_frame, text="▶  Generar informes",
            bg=DARK, fg=WHITE, font=(FONT, 10, "bold"),
            relief="flat", bd=0, pady=6, cursor="hand2",
            activebackground="#2d2d4e", activeforeground=WHITE,
            command=self._iniciar)
        self.btn.grid(row=0, column=0, sticky="ew", padx=(0,3), pady=(0,4))

        self.btn_continuar = tk.Button(
            btn_frame, text="✓  Verificación OK",
            bg=C_PEYA, fg=WHITE, font=(FONT, 10, "bold"),
            relief="flat", bd=0, pady=6, cursor="hand2",
            activebackground="#c0003a", activeforeground=WHITE,
            state="disabled", command=self._continuar_peya)
        self.btn_continuar.grid(row=0, column=1, sticky="ew", padx=(3,0), pady=(0,4))

        self.btn_cancel = tk.Button(
            btn_frame, text="✕  Cancelar",
            bg=WHITE, fg="#888888", font=(FONT, 10),
            relief="flat", bd=0, pady=6, cursor="hand2",
            highlightbackground=BORDER, highlightthickness=1,
            state="disabled", command=self._cancelar)
        self.btn_cancel.grid(row=1, column=0, columnspan=2, sticky="ew")

        # Actualizar badge ML al escribir la ruta
        self.ml_resenas.trace_add("write",   lambda *_: self._update_ml_badge())

    # ── Helpers UI ────────────────────────────────────────────────────────────

    def _abrir_locales(self):
        """Abre (o trae al frente) la ventana de gestión de locales."""
        if hasattr(self, "_locales_win") and self._locales_win.winfo_exists():
            self._locales_win.lift()
            self._locales_win.focus_force()
        else:
            self._locales_win = LocalesWindow(self)

    def _abrir_keywords_graves(self):
        """Abre (o trae al frente) la ventana de edición de palabras de errores graves."""
        if hasattr(self, "_keywords_win") and self._keywords_win.winfo_exists():
            self._keywords_win.lift()
            self._keywords_win.focus_force()
        else:
            self._keywords_win = KeywordsGravesWindow(self)

    def _set_badge(self, app, text, bg, fg):
        b = self._badges[app]
        b.config(text=text, bg=bg, fg=fg)

    def _update_ml_badge(self):
        if self.ml_resenas.get():
            self._set_badge("Mercado Libre", "CSV cargado", "#EAF3DE", "#3B6D11")
        else:
            self._set_badge("Mercado Libre", "Sin CSV", "#F5F5F3", "#888888")

    def _log(self, msg, tag="info"):
        def _w():
            self.log.config(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            prefix = {"ok":"✓ ","error":"✗ ","warn":"! ","head":"─ "}.get(tag,"  ")
            self.log.insert("end", f"{ts}  {prefix}{msg}\n", tag)
            self.log.see("end")
            self.log.config(state="disabled")
        self.after(0, _w)

    def _set_status(self, msg, pct=None):
        def _u():
            self.status_lbl.config(text=msg)
            if pct is not None:
                self.progress_var.set(pct)
        self.after(0, _u)

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _continuar_peya(self):
        flag = Path(__file__).parent / ".peya_login_ok"
        flag.touch()
        self.btn_continuar.config(state="disabled")
        self._log("Login de PedidosYa confirmado — continuando...", "ok")
        self._set_status("PedidosYa: continuando...", 25)
        self._set_badge("PedidosYa", "OK", "#EAF3DE", "#3B6D11")

    def _cancelar(self):
        if self._peya_proc and self._peya_proc.poll() is None:
            self._peya_proc.terminate()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        flag = Path(__file__).parent / ".peya_login_ok"
        flag.touch()
        self._log("Proceso cancelado.", "warn")
        self._set_status("Cancelado.", 0)
        self.running = False
        self.after(0, lambda: self.btn.config(state="normal",
                                              text="▶  Generar informes"))
        self.after(0, lambda: self.btn_cancel.config(state="disabled"))
        self.after(0, lambda: self.btn_continuar.config(state="disabled"))

    def _iniciar(self):
        if self.running:
            return
        if not self.rappi_email.get() or not self.rappi_password.get():
            messagebox.showerror("Faltan datos",
                                 "Ingresá el email y contraseña de Rappi.")
            return
        desde = self.fecha_desde.get()
        hasta = self.fecha_hasta.get()
        if datetime.strptime(desde, "%Y-%m-%d") > datetime.strptime(hasta, "%Y-%m-%d"):
            messagebox.showerror("Período inválido",
                                 "La fecha 'Desde' no puede ser mayor que 'Hasta'.")
            return

        self._guardar_config()
        self.running = True
        self.btn.config(state="disabled", text="Procesando...")
        self.btn_cancel.config(state="normal")
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")
        self.progress_var.set(0)
        if self.peya_enabled.get():
            self._set_badge("PedidosYa", "Conectando...", "#FAEEDA", "#854F0B")
        else:
            self._set_badge("PedidosYa", "Omitido", "#F5F5F3", "#888888")
        if self.rappi_enabled.get():
            self._set_badge("Rappi", "Esperando...", "#F5F5F3", "#888888")
        else:
            self._set_badge("Rappi", "Omitido", "#F5F5F3", "#888888")

        threading.Thread(target=self._run_proceso, daemon=True).start()

    def _hacer_login_peya(self, desde: str, hasta: str):
        """
        Corre el helper de PedidosYa con Popen para leer señales en tiempo real.
        El helper intenta login automático; si detecta 2FA imprime {"status":"2fa_required"}
        y espera el flag file — en ese momento habilitamos btn_continuar.
        Devuelve (token, totales_dict, device_token, reclamos_data) o (None, {}, "", []).
        """
        import subprocess as _sp, json as _json
        flag_path  = Path(__file__).parent / ".peya_login_ok"
        state_path = Path(__file__).parent / ".peya_browser_state.json"
        flag_path.unlink(missing_ok=True)
        helper = Path(__file__).parent / "peya_login_helper.py"

        email = self.peya_email.get()
        pwd   = self.peya_password.get()

        # Armar lista de tiendas con grupo y marca para calcular totales en el helper
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from config.locales import TIENDAS
            tiendas_list = [
                {"vc": f"PY_AR;{t['py_id']}", "grupo": t["grupo"], "marca": t.get("marca", "")}
                for t in TIENDAS if t.get("py_id")
            ]
        except Exception:
            tiendas_list = []

        try:
            self._peya_proc = _sp.Popen(
                [sys.executable, str(helper),
                 str(flag_path), str(state_path),
                 desde, hasta,
                 _json.dumps(tiendas_list),
                 email, pwd],
                stdout=_sp.PIPE, stderr=_sp.PIPE,
                text=True, encoding="utf-8", errors="replace",
                creationflags=_sp.CREATE_NO_WINDOW if sys.platform == "win32" else 0)

            last_data = None
            for line in self._peya_proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = _json.loads(line)
                    if obj.get("status") == "2fa_required":
                        # Pedir al usuario que complete la verificación en el browser
                        self._log("PedidosYa: se requiere verificación adicional — "
                                  "completá el proceso en el browser y hacé clic en Continuar.", "warn")
                        self._set_status("PedidosYa: completá la verificación en el browser...", 8)
                        self.after(0, lambda: self.btn_continuar.config(state="normal"))
                    elif obj.get("token") is not None:
                        last_data = obj
                except Exception:
                    pass  # líneas no-JSON se ignoran

            self._peya_proc.wait()

            stderr_out = self._peya_proc.stderr.read()
            if stderr_out and not last_data:
                self._log(f"PedidosYa error: {stderr_out[-300:]}", "error")

            if last_data:
                token         = last_data.get("token")
                totales       = last_data.get("totales", {})
                totales_marca = last_data.get("totales_marca", {})
                device_token  = last_data.get("device_token", "")
                reclamos_data = last_data.get("reclamos_data", [])
                if token:
                    return token, totales, totales_marca, device_token, reclamos_data

            return None, {}, {}, "", []

        except Exception as e:
            self._log(f"PedidosYa error: {e}", "error")
            return None, {}, {}, "", []
        finally:
            self._peya_proc = None

    def _run_proceso(self):
        import subprocess
        desde  = self.fecha_desde.get()
        hasta  = self.fecha_hasta.get()
        email  = self.rappi_email.get()
        pwd    = self.rappi_password.get()
        ml_csv      = self.ml_resenas.get()
        ml_tot      = self.ml_totales.get()
        ml_reclamos = self.ml_reclamos.get()
        out         = self.output_dir.get() or "./informes"

        use_rappi = self.rappi_enabled.get()
        use_peya  = self.peya_enabled.get()
        use_ml    = self.ml_enabled.get()

        self._log("Iniciando proceso...", "head")
        self._log(f"Período: {desde} → {hasta}", "info")
        plataformas = [n for n, v in [("Rappi", use_rappi), ("PedidosYa", use_peya), ("ML", use_ml)] if v]
        self._log(f"Plataformas activas: {', '.join(plataformas) if plataformas else 'ninguna'}", "info")
        self._set_status("Iniciando...", 2)

        # ── Login PedidosYa (solo si está activado) ────────────────────────
        peya_token = peya_totales = peya_totales_marca = peya_device_token = None
        if use_peya:
            self._log("PedidosYa: iniciando login automático...", "info")
            self._set_status("PedidosYa: iniciando sesión...", 5)

            peya_token, peya_totales, peya_totales_marca, peya_device_token, _ = self._hacer_login_peya(desde, hasta)
            if not peya_token:
                self._log("PedidosYa: login cancelado o fallido.", "warn")
                self.running = False
                self.after(0, lambda: self.btn.config(state="normal",
                                                      text="▶  Generar informes"))
                self.after(0, lambda: self.btn_cancel.config(state="disabled"))
                self.after(0, lambda: self.btn_continuar.config(state="disabled"))
                return

            self._log(f"PedidosYa: token OK ({len(peya_token)} chars)", "ok")
            self._set_status("PedidosYa: OK — iniciando extracción...", 15)
            self.after(0, lambda: self.btn_continuar.config(state="disabled"))
            self._set_badge("PedidosYa", "OK", "#EAF3DE", "#3B6D11")
        else:
            self._log("PedidosYa: desactivado, se omite.", "warn")
            self._set_badge("PedidosYa", "Omitido", "#F5F5F3", "#888888")
            self.after(0, lambda: self.btn_continuar.config(state="disabled"))

        # ── Subprocess principal ───────────────────────────────────────────
        cmd = [sys.executable, str(Path(__file__).parent / "main.py"),
               "--desde", desde, "--hasta", hasta,
               "--headless", "true", "--output", out]
        if ml_csv:      cmd += ["--mp-csv",      ml_csv]
        if ml_tot:      cmd += ["--mp-totales",  ml_tot]
        if ml_reclamos: cmd += ["--ml-reclamos", ml_reclamos]
        if not use_rappi: cmd += ["--skip-rappi"]
        if not use_peya:  cmd += ["--skip-peya"]
        if not use_ml:    cmd += ["--skip-ml"]

        env = os.environ.copy()
        env_file = Path(__file__).parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env.setdefault(k.strip(), v.strip())
        env["RAPPI_EMAIL"]    = email
        env["RAPPI_PASSWORD"] = pwd
        if peya_token:
            env["PEYA_TOKEN"] = peya_token
        if peya_device_token:
            env["PEYA_DEVICE_TOKEN"] = peya_device_token
        if peya_totales:
            import json as _json
            env["PEYA_TOTALES"] = _json.dumps(peya_totales)
        if peya_totales_marca:
            import json as _json
            env["PEYA_TOTALES_MARCA"] = _json.dumps(peya_totales_marca)
        state_path = Path(__file__).parent / ".peya_browser_state.json"
        if state_path.exists():
            env["PEYA_STATE_FILE"] = str(state_path)
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            self._proc = subprocess.Popen(
                cmd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0)
            self.after(0, lambda: self.btn_cancel.config(state="normal"))

            for line in self._proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                tag = "info"
                if "ERROR" in line:   tag = "error"
                elif "WARNING" in line: tag = "warn"
                elif "──" in line or "===" in line: tag = "head"
                self._log(line, tag)

                l = line.lower()
                if "extrayendo rappi" in l:
                    self._set_status("Rappi: extrayendo...", 40)
                    self._set_badge("Rappi", "Extrayendo...", "#FAEEDA", "#854F0B")
                elif "rappi:" in l and ("extraccion completada ok" in l or "reseñas" in l):
                    self._set_status("Rappi: completado", 65)
                    self._set_badge("Rappi", "OK", "#EAF3DE", "#3B6D11")
                elif "rappi:" in l and "extraccion fallida" in l:
                    self._set_badge("Rappi", "Error", "#FDECEA", "#A52A2A")
                elif "mercado libre" in l and "procesando" in l:
                    self._set_status("Mercado Libre: procesando...", 72)
                elif "excel:" in l:
                    self._set_status("Generando Excel...", 95)
                elif "completado" in l:
                    self._set_status("¡Informe generado!", 100)

            self._proc.wait()
            if self._proc.returncode == 0:
                self._log("Proceso finalizado correctamente.", "ok")
                self._set_status("¡Informe Excel generado correctamente!", 100)
                self.after(0, lambda: messagebox.showinfo(
                    "Completado",
                    f"El informe Excel se generó en:\n{Path(out).resolve()}"))
            else:
                self._log(f"El proceso terminó con errores.", "error")
                self._set_status("Proceso con errores — revisá el log.", 100)

        except Exception as e:
            self._log(f"Error inesperado: {e}", "error")

        finally:
            self.running = False
            self.after(0, lambda: self.btn.config(state="normal",
                                                  text="▶  Generar informes"))
            self.after(0, lambda: self.btn_cancel.config(state="disabled"))
            self.after(0, lambda: self.btn_continuar.config(state="disabled"))
            self._proc = None


if __name__ == "__main__":
    app = ResenaApp()
    app.mainloop()
