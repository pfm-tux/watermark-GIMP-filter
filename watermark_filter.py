#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WATERMARK FILTER per GIMP 3.2.x (Python-Fu)
============================================
Installazione:
  ~/.config/GIMP/3.2/plug-ins/watermark_filter/watermark_filter.py

  La cartella contenitrice deve avere lo stesso nome del file .py.
  Linux/macOS: chmod +x watermark_filter.py
  Riavvia GIMP → Filtri > Watermark > Aggiungi Watermark…

Log degli errori: ~/watermark_filter_errors.log
"""

import gi
gi.require_version("Gimp",   "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gtk",    "3.0")
gi.require_version("Gegl",   "0.4")
from gi.repository import Gimp, GimpUi, GLib, Gtk, Gdk, Gegl, Gio
import os
import sys
import math
import traceback

# ---------------------------------------------------------------------------
# LOG SU FILE  (utile per debug, scrive in ~/watermark_filter_errors.log)
# ---------------------------------------------------------------------------
LOG_PATH = os.path.join(GLib.get_home_dir(), "watermark_filter_errors.log")

def _log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# COSTANTI
# ---------------------------------------------------------------------------
POSIZIONI = [
    "In alto a sinistra",   "In alto al centro",   "In alto a destra",
    "Al centro a sinistra", "Al centro",            "Al centro a destra",
    "In basso a sinistra",  "In basso al centro",  "In basso a destra",
]

MARGIN       = 20   # margine in pixel dai bordi
TILE_PADDING = 40   # spazio extra tra ripetizioni in modalità tiled

ESTENSIONI_SUPPORTATE = {
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".webp"
}


# ---------------------------------------------------------------------------
# HELPERS API GIMP 3
# ---------------------------------------------------------------------------

def _set_foreground(r, g, b):
    """Imposta il colore di primo piano (API GIMP 3 via Gegl.Color)."""
    color = Gegl.Color.new("black")
    color.set_rgba(r / 255.0, g / 255.0, b / 255.0, 1.0)
    Gimp.context_set_foreground(color)


def _gimp_load(fpath):
    """
    Carica un file immagine.
    GIMP 3 API → Gimp.file_load(run_mode, GFile)   [2 argomenti]
    """
    gfile = Gio.File.new_for_path(fpath)
    return Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, gfile)


def _gimp_export(image, out_path):
    """
    Esporta/sovrascrive un file tramite PDB gimp-file-save (GIMP 3.2).
    Parametri: run-mode, image, file, options (opzionale).
    """
    gfile = Gio.File.new_for_path(out_path)

    pdb = Gimp.get_pdb()
    proc = pdb.lookup_procedure('gimp-file-save')
    if proc is None:
        raise RuntimeError("Procedura PDB 'gimp-file-save' non trovata.")

    config = proc.create_config()
    config.set_property('run-mode', Gimp.RunMode.NONINTERACTIVE)
    config.set_property('image',    image)
    config.set_property('file',     gfile)
    result = proc.run(config)
    if result.index(0) != Gimp.PDBStatusType.SUCCESS:
        raise RuntimeError(f"Errore PDB nell'export di: {out_path}")


def _crea_text_layer(image, testo, font_name, font_size, opacita):
    """
    Crea un layer di testo e lo inserisce nell'immagine.
    GIMP 3.2 API → Gimp.TextLayer.new(image, text, Gimp.Font, size, unit)
    Il font va recuperato come oggetto Gimp.Font tramite get_by_name().
    """
    # Gimp.Font.get_by_name() richiede il nome ESATTO del font registrato in GIMP.
    # Gtk.FontButton restituisce nomi Pango tipo "Sans Bold" o "DejaVu Sans Bold":
    # proviamo prima il nome completo, poi rimuovendo gli stili finali uno alla volta,
    # e infine cerchiamo il match più vicino nella lista completa dei font disponibili.
    STILI_PANGO = ("Bold Italic", "Bold Oblique", "Italic", "Oblique",
                   "Bold", "Light", "Thin", "Black", "Medium",
                   "Condensed", "Regular")

    font_obj = Gimp.Font.get_by_name(font_name)

    if font_obj is None:
        # Prova a rimuovere lo stile finale per trovare il font base
        for stile in STILI_PANGO:
            if font_name.endswith(" " + stile):
                base = font_name[: -(len(stile) + 1)]
                font_obj = Gimp.Font.get_by_name(base)
                if font_obj is not None:
                    break

    if font_obj is None:
        # Cerca nella lista completa dei font un nome che contenga font_name
        # (es. "Sans Bold" potrebbe matchare "Sans Bold" nella lista GIMP)
        try:
            tutti = Gimp.fonts_get_list("")   # funzione globale, non metodo di Font
            nome_lower = font_name.lower()
            for f in (tutti or []):
                if f.get_name().lower() == nome_lower:
                    font_obj = f
                    break
            if font_obj is None:
                # match parziale: il nome GIMP contiene la stringa cercata
                for f in (tutti or []):
                    if nome_lower in f.get_name().lower():
                        font_obj = f
                        break
        except Exception:
            pass

    if font_obj is None:
        font_obj = Gimp.Font.get_by_name("Sans")   # ultimo fallback
    layer = Gimp.TextLayer.new(image, testo, font_obj,
                               font_size, Gimp.Unit.pixel())
    layer.set_opacity(opacita)
    layer.set_mode(Gimp.LayerMode.NORMAL)
    # Il layer va inserito esplicitamente (non è automatico)
    image.insert_layer(layer, None, -1)
    return layer


def _ruota_layer(layer, gradi):
    """
    Ruota il layer attorno al proprio centro.
    GIMP 3 API → layer.transform_rotate_simple(rad, auto_center, cx, cy)
    get_offsets() restituisce (success, x, y) come tupla.
    """
    if gradi == 0:
        return
    rad     = math.radians(gradi)
    offsets = layer.get_offsets()   # (True/False, x, y)
    cx = offsets[1] + layer.get_width()  / 2
    cy = offsets[2] + layer.get_height() / 2
    layer.transform_rotate_simple(rad, True, cx, cy)


def _calcola_posizione(pos_idx, img_w, img_h, lw, lh):
    """Restituisce (x, y) secondo la griglia 3×3."""
    col = pos_idx % 3
    row = pos_idx // 3
    x = (MARGIN if col == 0
         else (img_w - lw) // 2 if col == 1
         else img_w - lw - MARGIN)
    y = (MARGIN if row == 0
         else (img_h - lh) // 2 if row == 1
         else img_h - lh - MARGIN)
    return x, y


# ---------------------------------------------------------------------------
# LOGICA WATERMARK
# ---------------------------------------------------------------------------

def applica_watermark(image, testo, font_name, font_size,
                      colore_rgb, opacita, posizione_idx, tiled):
    """
    Aggiunge il watermark all'immagine e fa il flatten.
    Lancia eccezione in caso di errore (gestita dai chiamanti).
    """
    _set_foreground(*colore_rgb)

    if tiled:
        _applica_tiled(image, testo, font_name, font_size, opacita)
    else:
        _applica_singolo(image, testo, font_name, font_size, opacita,
                         posizione_idx)
    image.flatten()


def _applica_singolo(image, testo, font_name, font_size,
                     opacita, posizione_idx):
    img_w = image.get_width()
    img_h = image.get_height()

    layer = _crea_text_layer(image, testo, font_name, font_size, opacita)

    lw = layer.get_width()
    lh = layer.get_height()
    x, y = _calcola_posizione(posizione_idx, img_w, img_h, lw, lh)
    layer.set_offsets(x, y)


def _applica_tiled(image, testo, font_name, font_size, opacita):
    img_w = image.get_width()
    img_h = image.get_height()

    # Layer temporaneo per misurare le dimensioni del testo
    tmp = _crea_text_layer(image, testo, font_name, font_size, opacita)
    tw  = tmp.get_width()
    th  = tmp.get_height()
    image.remove_layer(tmp)

    step_x   = tw + TILE_PADDING
    step_y   = th + TILE_PADDING
    offset_x = (img_w % step_x) // 2
    offset_y = (img_h % step_y) // 2

    y = offset_y - step_y
    while y < img_h + step_y:
        x = offset_x - step_x
        while x < img_w + step_x:
            tl = _crea_text_layer(image, testo, font_name, font_size, opacita)
            tl.set_offsets(x, y)
            x += step_x
        y += step_y


# ---------------------------------------------------------------------------
# ELABORAZIONE BATCH (cartella)
# ---------------------------------------------------------------------------

def elabora_cartella(params):
    cartella = params["cartella"]
    if not cartella or not os.path.isdir(cartella):
        Gimp.message("Cartella non valida o non selezionata.")
        return

    files = [
        f for f in os.listdir(cartella)
        if os.path.splitext(f)[1].lower() in ESTENSIONI_SUPPORTATE
    ]
    if not files:
        Gimp.message("Nessun file immagine trovato nella cartella.")
        return

    ok, errori = 0, []
    _log(f"\n--- Elaborazione cartella: {cartella} ---")

    for fname in files:
        fpath = os.path.join(cartella, fname)
        try:
            image = _gimp_load(fpath)
            applica_watermark(
                image,
                params["testo"],
                params["font_name"],
                params["font_size"],
                params["colore_rgb"],
                params["opacita"],
                params["posizione_idx"],
                params["tiled"],
            )
            if params["sovrascrivi"]:
                out_path = fpath
            else:
                base, ext = os.path.splitext(fpath)
                out_path  = base + params["suffisso"] + ext

            _gimp_export(image, out_path)
            Gimp.Image.delete(image)
            _log(f"  OK: {fname} → {os.path.basename(out_path)}")
            ok += 1

        except Exception as e:
            tb = traceback.format_exc()
            errori.append(f"{fname}: {e}")
            _log(f"  ERRORE: {fname}\n{tb}")

    msg = f"Watermark applicato a {ok} file su {len(files)}."
    if errori:
        msg += "\n\nErrori:\n" + "\n".join(errori)
        msg += f"\n\nDettagli nel log: {LOG_PATH}"
    Gimp.message(msg)


# ---------------------------------------------------------------------------
# ELABORAZIONE IMMAGINE APERTA
# ---------------------------------------------------------------------------

def elabora_immagine_aperta(params, image):
    """Applica il watermark sull'immagine corrente già aperta in GIMP."""
    _log(f"\n--- Immagine aperta: {image} ---")
    try:
        applica_watermark(
            image,
            params["testo"],
            params["font_name"],
            params["font_size"],
            params["colore_rgb"],
            params["opacita"],
            params["posizione_idx"],
            params["tiled"],
        )

        if not params["sovrascrivi"]:
            uri = image.get_uri()
            if uri:
                path      = GLib.filename_from_uri(uri)[0]
                base, ext = os.path.splitext(path)
                out_path  = base + params["suffisso"] + ext
                _gimp_export(image, out_path)
                Gimp.message(f"Watermark applicato e salvato come:\n{out_path}")
            else:
                Gimp.message(
                    "Watermark applicato.\n"
                    "L'immagine non ha ancora un percorso su disco:\n"
                    "usa File > Esporta come… per salvarla."
                )
        else:
            Gimp.message(
                "Watermark applicato.\n"
                "Usa File > Sovrascrivi (o Esporta come…) per salvare."
            )

    except Exception as e:
        tb = traceback.format_exc()
        _log(f"ERRORE immagine aperta:\n{tb}")
        Gimp.message(f"Errore durante l'applicazione del watermark:\n{e}\n\nDettagli: {LOG_PATH}")

    Gimp.displays_flush()


# ---------------------------------------------------------------------------
# DIALOG PRINCIPALE
# ---------------------------------------------------------------------------

class WatermarkDialog:

    def __init__(self):
        self.result = None
        self._build_ui()

    def _build_ui(self):
        self.dialog = Gtk.Dialog(title="Aggiungi Watermark")
        self.dialog.set_modal(True)
        self.dialog.set_border_width(12)
        self.dialog.set_default_size(560, -1)

        self.dialog.add_button("Annulla", Gtk.ResponseType.CANCEL)
        btn_ok = self.dialog.add_button("Applica", Gtk.ResponseType.OK)
        btn_ok.get_style_context().add_class("suggested-action")

        box  = self.dialog.get_content_area()
        box.set_spacing(6)
        grid = Gtk.Grid(column_spacing=12, row_spacing=10,
                        margin_top=8, margin_bottom=8)
        box.pack_start(grid, True, True, 0)
        row = 0

        # --- Testo ---
        grid.attach(self._lbl("Testo watermark:"), 0, row, 1, 1)
        self.entry_testo = Gtk.Entry(text="© Il Mio Nome", hexpand=True)
        grid.attach(self.entry_testo, 1, row, 2, 1);  row += 1

        # --- Font ---
        grid.attach(self._lbl("Font:"), 0, row, 1, 1)
        self.font_button = Gtk.FontButton(font="Sans Bold 48", hexpand=True)
        grid.attach(self.font_button, 1, row, 2, 1);  row += 1

        # --- Colore ---
        grid.attach(self._lbl("Colore:"), 0, row, 1, 1)
        self.color_button = Gtk.ColorButton()
        rgba = Gdk.RGBA(); rgba.parse("rgba(255,255,255,1)")
        self.color_button.set_rgba(rgba)
        grid.attach(self.color_button, 1, row, 1, 1);  row += 1

        # --- Opacità ---
        grid.attach(self._lbl("Opacità (%):"), 0, row, 1, 1)
        self.spin_opacita = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.spin_opacita.set_value(20)
        grid.attach(self.spin_opacita, 1, row, 1, 1);  row += 1

        # --- Posizione ---
        grid.attach(self._lbl("Posizione:"), 0, row, 1, 1)
        self.combo_pos = Gtk.ComboBoxText()
        for p in POSIZIONI:
            self.combo_pos.append_text(p)
        self.combo_pos.set_active(8)   # default: in basso a destra
        grid.attach(self.combo_pos, 1, row, 2, 1);  row += 1

        # --- Tiled ---
        grid.attach(self._lbl("Ripeti su tutta l'immagine:"), 0, row, 1, 1)
        self.check_tiled = Gtk.CheckButton(active=False)
        self.check_tiled.connect("toggled", self._on_tiled_toggled)
        grid.attach(self.check_tiled, 1, row, 1, 1);  row += 1

        grid.attach(Gtk.Separator(), 0, row, 3, 1);  row += 1

        # --- Sorgente ---
        grid.attach(self._lbl("Applica su:"), 0, row, 1, 1)
        self.radio_singolo  = Gtk.RadioButton.new_with_label(None, "Immagine aperta")
        self.radio_cartella = Gtk.RadioButton.new_with_label_from_widget(
            self.radio_singolo, "Cartella di file…"
        )
        self.radio_cartella.connect("toggled", self._on_cartella_toggled)
        hbox_r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        hbox_r.pack_start(self.radio_singolo,  False, False, 0)
        hbox_r.pack_start(self.radio_cartella, False, False, 0)
        grid.attach(hbox_r, 1, row, 2, 1);  row += 1

        # --- Selettore cartella ---
        grid.attach(self._lbl("Cartella:"), 0, row, 1, 1)
        self.btn_cartella = Gtk.FileChooserButton(
            title="Seleziona cartella",
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            hexpand=True, sensitive=False
        )
        grid.attach(self.btn_cartella, 1, row, 2, 1);  row += 1

        grid.attach(Gtk.Separator(), 0, row, 3, 1);  row += 1

        # --- Output ---
        grid.attach(self._lbl("Salvataggio:"), 0, row, 1, 1)
        self.radio_sovrascrivi = Gtk.RadioButton.new_with_label(
            None, "Sovrascrivi originali"
        )
        self.radio_copia = Gtk.RadioButton.new_with_label_from_widget(
            self.radio_sovrascrivi, "Salva copie con suffisso:"
        )
        self.entry_suffisso = Gtk.Entry(text="_wm", width_chars=8)
        vbox_out = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vbox_out.pack_start(self.radio_sovrascrivi, False, False, 0)
        hbox_suf = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hbox_suf.pack_start(self.radio_copia,    False, False, 0)
        hbox_suf.pack_start(self.entry_suffisso, False, False, 0)
        vbox_out.pack_start(hbox_suf, False, False, 0)
        grid.attach(vbox_out, 1, row, 2, 1)

        self.dialog.show_all()

    def _lbl(self, testo):
        l = Gtk.Label(label=testo)
        l.set_halign(Gtk.Align.END)
        return l

    def _on_tiled_toggled(self, w):
        self.combo_pos.set_sensitive(not w.get_active())

    def _on_cartella_toggled(self, w):
        self.btn_cartella.set_sensitive(w.get_active())

    def run(self):
        response = self.dialog.run()
        if response == Gtk.ResponseType.OK:
            # Gtk.FontButton.get_font() restituisce una stringa Pango come
            # "Sans Bold 48" oppure "Sans Bold Italic 36".
            # L'ultimo token numerico è la dimensione; tutto il resto è il nome font.
            # ATTENZIONE: Gimp.Font.get_by_name() cerca il nome ESATTO nel
            # registro font di GIMP (es. "Sans Bold"), non la stringa Pango completa.
            font_desc = self.font_button.get_font()
            parts = font_desc.rsplit(" ", 1)
            try:
                font_size = float(parts[1])
                font_name = parts[0]   # es. "Sans Bold"
            except (IndexError, ValueError):
                font_size = 48.0
                font_name = font_desc
            # Pulizia: rimuovi eventuali stili Pango finali non riconosciuti da GIMP
            # (Italic, Oblique, ecc.) cercando prima il nome completo, poi senza stile
            font_name = font_name.strip()

            rgba = self.color_button.get_rgba()
            self.result = {
                "testo":             self.entry_testo.get_text(),
                "font_name":         font_name,
                "font_size":         font_size,
                "colore_rgb":        (int(rgba.red   * 255),
                                      int(rgba.green * 255),
                                      int(rgba.blue  * 255)),
                "opacita":           self.spin_opacita.get_value(),
                "posizione_idx":     self.combo_pos.get_active(),
"tiled":             self.check_tiled.get_active(),
                "modalita_cartella": self.radio_cartella.get_active(),
                "cartella":          self.btn_cartella.get_filename() or "",
                "sovrascrivi":       self.radio_sovrascrivi.get_active(),
                "suffisso":          self.entry_suffisso.get_text(),
            }
        self.dialog.destroy()
        return self.result


# ---------------------------------------------------------------------------
# ENTRY POINT PLUG-IN
# ---------------------------------------------------------------------------

class WatermarkPlugin(Gimp.PlugIn):

    def do_query_procedures(self):
        return ["plug-in-watermark-testo"]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name,
            Gimp.PDBProcType.PLUGIN,
            self.run, None
        )
        procedure.set_image_types("*")
        procedure.set_sensitivity_mask(
            Gimp.ProcedureSensitivityMask.DRAWABLE
        )
        procedure.set_menu_label("Aggiungi Watermark…")
        procedure.add_menu_path("<Image>/Filtri/Watermark")
        procedure.set_documentation(
            "Aggiunge un watermark testuale personalizzabile",
            "Font, colore, opacità, posizione, tiled, batch.",
            name,
        )
        procedure.set_attribution("Filtro personalizzato", "", "2025")
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, run_data):
        if run_mode == Gimp.RunMode.INTERACTIVE:
            GimpUi.init("watermark_filter")
            dlg    = WatermarkDialog()
            params = dlg.run()

            if params is None:
                return procedure.new_return_values(
                    Gimp.PDBStatusType.CANCEL, GLib.Error()
                )

            if params["modalita_cartella"]:
                elabora_cartella(params)
            else:
                elabora_immagine_aperta(params, image)

        return procedure.new_return_values(
            Gimp.PDBStatusType.SUCCESS, GLib.Error()
        )


Gimp.main(WatermarkPlugin.__gtype__, sys.argv)
