#!/usr/bin/env python3
"""
PDF Signer
----------
Drag a PDF onto the window. Draw a new signature (saved as a PNG), load a
previously-saved one, or type your name — each drops onto the page
automatically, and you can add as many signatures, typed names, and dates
as you like (each click adds another). Drag any one to reposition, drag its
small corner handle to resize, and hover over it + press Delete/Backspace
to remove just that one. Then save the signed PDF.

Dependencies (auto-installed on first run if missing):
    pymupdf, pillow, tkinterdnd2
"""

import subprocess
import sys


def _ensure_deps():
    """Install any missing dependencies before importing them."""
    required = {"fitz": "pymupdf", "PIL": "pillow", "tkinterdnd2": "tkinterdnd2"}
    missing = []
    for module_name, pip_name in required.items():
        try:
            __import__(module_name)
        except ImportError:
            missing.append(pip_name)
    if missing:
        print(f"Installing missing packages: {', '.join(missing)} ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--break-system-packages", *missing]
        )


_ensure_deps()

import datetime
import json
import math
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageTk
from tkinterdnd2 import DND_FILES, TkinterDnD

SIGNATURE_DEFAULT_WIDTH_PX = 150  # default on-canvas signature width, in pixels
TEXT_DEFAULT_FONT_PT = 6           # default font size for dates/typed names, in PDF points (50% of the previous 12pt default)
CANVAS_TARGET_WIDTH = 800         # rendered page width in pixels
PLACEMENT_STAGGER_PX = 20         # offset each successive auto-placed item so they don't stack

# Where the script itself lives — signature/name asset files (PNGs, saved
# name .txt files) default here, distinct from the PDF's own folder (which
# the final "Save Signed PDF As..." dialog defaults to instead).
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Remembered layout (where you last put the name / signature / date and how
# big they were) lives next to the script. Delete this file to go back to
# the built-in default layout.
SETTINGS_PATH = os.path.join(SCRIPT_DIR, "pdf_signer_settings.json")

# "date" and "name" (typed name) are both simple text overlays that behave
# identically — same drag/resize/delete/save mechanics — so they share the
# same generic code path, keyed by kind. Only "signature" (image-based) has
# its own separate implementation below.
TEXT_KINDS = ("date", "name")


# --------------------------------------------------------------------------- #
# Signature pad
# --------------------------------------------------------------------------- #
class SignaturePad(tk.Toplevel):
    """A small popup window for scribbling a signature with the mouse."""

    PAD_WIDTH = 500
    PAD_HEIGHT = 200

    def __init__(self, master, on_saved):
        super().__init__(master)
        self.title("Draw your signature")
        self.resizable(False, False)
        self.on_saved = on_saved
        self._last_xy = None

        # Real image we draw into in parallel with the on-screen canvas,
        # so we can save an accurate PNG without doing a screen grab.
        self._image = Image.new("RGBA", (self.PAD_WIDTH, self.PAD_HEIGHT), (255, 255, 255, 0))
        self._draw = ImageDraw.Draw(self._image)

        self.canvas = tk.Canvas(
            self, width=self.PAD_WIDTH, height=self.PAD_HEIGHT,
            bg="white", cursor="pencil", highlightthickness=1, highlightbackground="#999"
        )
        self.canvas.pack(padx=10, pady=10)
        self.canvas.bind("<ButtonPress-1>", self._start_stroke)
        self.canvas.bind("<B1-Motion>", self._draw_stroke)
        self.canvas.bind("<ButtonRelease-1>", self._end_stroke)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=(0, 10))
        ttk.Button(btn_frame, text="Clear", command=self._clear).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Save Signature", command=self._save).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="left", padx=5)

        self.transient(master)
        self.grab_set()

    def _start_stroke(self, event):
        self._last_xy = (event.x, event.y)

    def _draw_stroke(self, event):
        if self._last_xy is None:
            self._last_xy = (event.x, event.y)
            return
        x0, y0 = self._last_xy
        x1, y1 = event.x, event.y
        self.canvas.create_line(x0, y0, x1, y1, width=3, fill="black",
                                 capstyle=tk.ROUND, smooth=True)
        self._draw.line([x0, y0, x1, y1], fill=(0, 0, 0, 255), width=3, joint="curve")
        self._last_xy = (x1, y1)

    def _end_stroke(self, _event):
        self._last_xy = None

    def _clear(self):
        self.canvas.delete("all")
        self._image = Image.new("RGBA", (self.PAD_WIDTH, self.PAD_HEIGHT), (255, 255, 255, 0))
        self._draw = ImageDraw.Draw(self._image)

    def _has_content(self):
        bbox = self._image.getbbox()
        return bbox is not None

    def _save(self):
        if not self._has_content():
            messagebox.showwarning("Nothing drawn", "Draw a signature before saving.", parent=self)
            return
        # Crop to the drawn content plus a small margin so we don't place a
        # huge transparent box on the page.
        bbox = self._image.getbbox()
        margin = 6
        l, t, r, b = bbox
        l = max(0, l - margin)
        t = max(0, t - margin)
        r = min(self.PAD_WIDTH, r + margin)
        b = min(self.PAD_HEIGHT, b + margin)
        cropped = self._image.crop((l, t, r, b))

        save_path = filedialog.asksaveasfilename(
            parent=self,
            title="Save signature as PNG",
            defaultextension=".png",
            initialdir=SCRIPT_DIR,
            initialfile="signature.png",
            filetypes=[("PNG image", "*.png")],
        )
        if not save_path:
            return
        cropped.save(save_path, "PNG")
        self.on_saved(save_path, cropped.size)
        self.destroy()


# --------------------------------------------------------------------------- #
# Main application
# --------------------------------------------------------------------------- #
class PDFSignerApp(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF Signer")
        self.geometry("900x750")

        self.pdf_path = None
        self.doc = None
        self.page_index = 0
        self.zoom = 1.0
        self.page_photo = None  # keep a reference so Tk doesn't garbage-collect it

        # Every placed signature/date/typed-name is its own independent
        # instance so any number can exist at once, each draggable/
        # resizable/removable on its own.
        self.signature_items = []
        self.text_items = {kind: [] for kind in TEXT_KINDS}  # "date", "name"

        self._drag_type = None       # None | "signature" | "date" | "name", set while dragging
        self._drag_canvas_id = None  # the specific canvas item id being dragged

        self._resize_type = None       # None | "signature" | "date" | "name", set while resizing
        self._resize_handle_id = None  # the specific handle's canvas item id being dragged
        self._resize_start_dist = 0.0
        self._resize_start_value = 0.0

        self.modified = False  # True whenever there's an unsaved change to warn about on close

        # Layout remembered from earlier sessions, keyed by kind ("name",
        # "signature", "date"); and, for this session, the item of each kind
        # the user most recently placed, moved or resized (that's the one
        # whose position/size gets remembered on save).
        self.layout_memory = self._load_layout_memory()
        self._last_touched = {}
        # Most recent name text / signature PNG path, used by "Add All".
        # Restored from the settings file so it works across sessions.
        self._last_name, self._last_sig_path = self._load_last_used()

        self._build_ui()

    # ---------------------------------------------------------------- UI ---
    def _build_ui(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(side="top", fill="x", padx=8, pady=6)

        self.open_btn = ttk.Button(toolbar, text="Open PDF...", command=self._open_dialog)
        self.open_btn.pack(side="left", padx=4)

        self.name_btn = ttk.Button(toolbar, text="Type Name...", command=self._add_name,
                                    state="disabled")
        self.name_btn.pack(side="left", padx=4)

        self.load_name_btn = ttk.Button(toolbar, text="Load Name...", command=self._load_name_file,
                                         state="disabled")
        self.load_name_btn.pack(side="left", padx=4)

        self.sign_btn = ttk.Button(toolbar, text="Draw Signature", command=self._open_signature_pad,
                                    state="disabled")
        self.sign_btn.pack(side="left", padx=4)

        self.load_sig_btn = ttk.Button(toolbar, text="Load Signature...", command=self._load_signature_file,
                                        state="disabled")
        self.load_sig_btn.pack(side="left", padx=4)

        self.date_btn = ttk.Button(toolbar, text="Add Today's Date", command=self._add_date,
                                    state="disabled")
        self.date_btn.pack(side="left", padx=4)

        self.add_all_btn = ttk.Button(toolbar, text="Add All", command=self._add_all,
                                       state="disabled")
        self.add_all_btn.pack(side="left", padx=4)

        self.undo_name_btn = ttk.Button(toolbar, text="Clear All Names",
                                         command=lambda: self._clear_all_text("name"), state="disabled")
        self.undo_name_btn.pack(side="left", padx=4)

        self.undo_sig_btn = ttk.Button(toolbar, text="Clear All Signatures",
                                        command=self._clear_all_signatures, state="disabled")
        self.undo_sig_btn.pack(side="left", padx=4)

        self.undo_date_btn = ttk.Button(toolbar, text="Clear All Dates",
                                         command=lambda: self._clear_all_text("date"), state="disabled")
        self.undo_date_btn.pack(side="left", padx=4)

        self.save_btn = ttk.Button(toolbar, text="Save Signed PDF As...", command=self._save_pdf,
                                    state="disabled")
        self.save_btn.pack(side="right", padx=4)

        # Kind -> the "Clear All ..." button for it, and the mutually-shared
        # canvas tag names — used throughout so drag/resize/delete/clear all
        # generalize across "date" and "name" instead of duplicating code.
        self._clear_btn_for = {
            "signature": self.undo_sig_btn,
            "date": self.undo_date_btn,
            "name": self.undo_name_btn,
        }

        self.status = tk.StringVar(value="Drag and drop a PDF file here to begin.")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(side="bottom", fill="x", padx=8, pady=4)

        # Scrollable canvas area for the rendered PDF page
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=8, pady=4)

        self.canvas = tk.Canvas(container, bg="#ddd")
        vbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        hbar = ttk.Scrollbar(container, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        # Mouse-wheel scrolling of the page view: plain wheel scrolls
        # vertically, Shift+wheel scrolls horizontally. <MouseWheel> covers
        # Windows/macOS; <Button-4>/<Button-5> cover Linux (X11), which
        # sends those instead of a MouseWheel event.
        self.canvas.bind("<MouseWheel>", self._on_mousewheel_y)
        self.canvas.bind("<Shift-MouseWheel>", self._on_mousewheel_x)
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))
        self.canvas.bind("<Shift-Button-4>", lambda e: self.canvas.xview_scroll(-1, "units"))
        self.canvas.bind("<Shift-Button-5>", lambda e: self.canvas.xview_scroll(1, "units"))

        # Let any placed signature/date/name be dragged around to reposition
        # it. Bound by tag (shared across every instance of that kind) — the
        # handler looks up which specific item ("current") received the
        # event, so each instance moves independently.
        for tag in ("signature", "date", "name"):
            self.canvas.tag_bind(tag, "<ButtonPress-1>",
                                  lambda e, t=tag: self._start_drag(t, e))
            self.canvas.tag_bind(tag, "<B1-Motion>", self._do_drag)
            self.canvas.tag_bind(tag, "<ButtonRelease-1>", self._end_drag)
            self.canvas.tag_bind(tag, "<Enter>", lambda e: self.canvas.config(cursor="fleur"))
            self.canvas.tag_bind(tag, "<Leave>", lambda e: self.canvas.config(cursor=""))

        # Each placed item gets its own small draggable handle at its
        # bottom-right corner; dragging that handle resizes that instance.
        handle_tag_kind = {"sig_handle": "signature", "date_handle": "date", "name_handle": "name"}
        for tag, kind in handle_tag_kind.items():
            self.canvas.tag_bind(tag, "<ButtonPress-1>",
                                  lambda e, k=kind: self._start_resize(k, e))
            self.canvas.tag_bind(tag, "<B1-Motion>", self._do_resize_drag)
            self.canvas.tag_bind(tag, "<ButtonRelease-1>", self._end_resize)
            self.canvas.tag_bind(tag, "<Enter>",
                                  lambda e: self.canvas.config(cursor="bottom_right_corner"))
            self.canvas.tag_bind(tag, "<Leave>", lambda e: self.canvas.config(cursor=""))

        # Delete/Backspace removes whichever specific overlay instance is
        # under the cursor at the time of the key press — not "the"
        # signature/date/name, since there can be several. bind_all so it
        # works regardless of which widget currently has keyboard focus.
        self.bind_all("<Delete>", self._on_delete_key)
        self.bind_all("<BackSpace>", self._on_delete_key)

        # Drag and drop
        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self._on_drop)

        # Warn before closing if there are unsaved changes.
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        if not self.modified:
            self.destroy()
            return
        response = messagebox.askyesnocancel(
            "Unsaved changes",
            "You have unsaved changes to this PDF. Save before closing?",
        )
        if response is None:
            return  # Cancel — leave the window open
        if response:
            self._save_pdf()
            if not self.modified:  # save succeeded (or nothing needed saving)
                self.destroy()
            # else the save dialog was cancelled/failed — stay open
        else:
            self.destroy()  # discard changes

    # ------------------------------------------------------------ Loading ---
    def _on_drop(self, event):
        paths = self.tk.splitlist(event.data)
        if not paths:
            return
        path = paths[0]
        if not path.lower().endswith(".pdf"):
            messagebox.showerror("Unsupported file", "Please drop a PDF file.")
            return
        self._load_pdf(path)

    def _open_dialog(self):
        path = filedialog.askopenfilename(title="Open PDF", filetypes=[("PDF files", "*.pdf")])
        if path:
            self._load_pdf(path)

    def _load_pdf(self, path):
        try:
            doc = fitz.open(path)
        except Exception as exc:
            messagebox.showerror("Failed to open PDF", str(exc))
            return

        self.pdf_path = path
        self.doc = doc
        self.page_index = 0
        self.signature_items = []
        self.text_items = {kind: [] for kind in TEXT_KINDS}
        self._drag_type = None
        self._drag_canvas_id = None
        self._resize_type = None
        self._resize_handle_id = None
        self._last_touched = {}
        self.modified = False
        self.sign_btn.config(state="normal")
        self.load_sig_btn.config(state="normal")
        self.name_btn.config(state="normal")
        self.load_name_btn.config(state="normal")
        self.date_btn.config(state="normal")
        self.add_all_btn.config(state="normal")
        self.save_btn.config(state="normal")
        self.undo_sig_btn.config(state="disabled")
        self.undo_name_btn.config(state="disabled")
        self.undo_date_btn.config(state="disabled")

        self._render_page()
        self.status.set(f"Loaded {os.path.basename(path)}. Draw or load a signature, type your "
                         f"name, or add today's date — each drops onto the page automatically, "
                         f"and you can add as many as you need.")

    def _render_page(self):
        page = self.doc[self.page_index]
        page_width_pt = page.rect.width
        self.zoom = CANVAS_TARGET_WIDTH / page_width_pt
        matrix = fitz.Matrix(self.zoom, self.zoom)
        pix = page.get_pixmap(matrix=matrix)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        self.page_photo = ImageTk.PhotoImage(img)

        self.canvas.delete("all")
        self.canvas.config(scrollregion=(0, 0, pix.width, pix.height))
        self.canvas.create_image(0, 0, anchor="nw", image=self.page_photo, tags=("page",))

        # Re-draw any existing overlays after a re-render
        self._redraw_overlays()

    def _redraw_overlays(self):
        for item in self.signature_items:
            x, y = item["canvas_xy"]
            item["canvas_id"] = self.canvas.create_image(
                x, y, image=item["thumbnail"], anchor="center", tags=("signature",)
            )
            item["handle_id"] = None
            self._update_handle_for_item(item, "signature")
        for kind in TEXT_KINDS:
            for item in self.text_items[kind]:
                x, y = item["canvas_xy"]
                disp_size = max(1, round(item["font_pt"] * self.zoom))
                item["canvas_id"] = self.canvas.create_text(
                    x, y, text=item["text"], fill="black",
                    font=("Helvetica", disp_size), anchor="nw", tags=(kind,)
                )
                item["handle_id"] = None
                self._update_handle_for_item(item, kind)

    # ------------------------------------------------------------ Signing ---
    def _open_signature_pad(self):
        SignaturePad(self, on_saved=self._on_signature_saved)

    def _load_signature_file(self):
        path = filedialog.askopenfilename(
            title="Load a saved signature",
            initialdir=SCRIPT_DIR,
            filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            img = Image.open(path).convert("RGBA")
        except Exception as exc:
            messagebox.showerror("Failed to load signature", str(exc))
            return
        self._on_signature_saved(path, img.size)

    def _on_signature_saved(self, path, size_px):
        self._last_sig_path = path
        orig_img = Image.open(path).convert("RGBA")
        x, y = self._default_position("signature")
        self._place_signature(path, orig_img, size_px, x, y)

    def _add_name(self):
        name = simpledialog.askstring("Type your name", "Enter the name to add to the PDF:",
                                       parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        self._last_name = name
        x, y = self._default_position("name")
        self._place_text("name", x, y, name)
        if messagebox.askyesno("Save name?",
                                "Save this name to a text file so you can reuse it later?"):
            self._save_name_to_file(name)

    def _save_name_to_file(self, name):
        save_path = filedialog.asksaveasfilename(
            title="Save name as text file",
            defaultextension=".txt",
            initialdir=SCRIPT_DIR,
            initialfile="name.txt",
            filetypes=[("Text file", "*.txt")],
        )
        if not save_path:
            return
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(name)
        except Exception as exc:
            messagebox.showerror("Failed to save name", str(exc))

    def _load_name_file(self):
        path = filedialog.askopenfilename(
            title="Load a saved name",
            initialdir=SCRIPT_DIR,
            filetypes=[("Text file", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                name = f.read().strip()
        except Exception as exc:
            messagebox.showerror("Failed to load name", str(exc))
            return
        if not name:
            messagebox.showwarning("Empty file", "That file doesn't contain any text.")
            return
        self._last_name = name
        x, y = self._default_position("name")
        self._place_text("name", x, y, name)

    def _add_all(self):
        """Drop name, signature and today's date in one click, using the
        name and signature used last (remembered between sessions). Only
        asks for what it doesn't have yet; cancelling a prompt skips just
        that item."""
        name = self._last_name
        if not name:
            name = simpledialog.askstring("Type your name",
                                          "Enter the name to add to the PDF:", parent=self)
            name = name.strip() if name else ""
        if name:
            self._last_name = name
            x, y = self._default_position("name")
            self._place_text("name", x, y, name)

        sig_path = self._last_sig_path
        if not sig_path or not os.path.isfile(sig_path):
            sig_path = filedialog.askopenfilename(
                title="Load a saved signature",
                initialdir=SCRIPT_DIR,
                filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
            )
        if sig_path:
            try:
                img = Image.open(sig_path).convert("RGBA")
            except Exception as exc:
                messagebox.showerror("Failed to load signature", str(exc))
            else:
                self._on_signature_saved(sig_path, img.size)

        self._add_date()

    def _add_date(self):
        date_str = datetime.date.today().isoformat()
        x, y = self._default_position("date")
        self._place_text("date", x, y, date_str)

    # ------------------------------------------------- Remembered layout ---
    @staticmethod
    def _load_layout_memory():
        """Read the remembered layout from disk. Anything missing, corrupt
        or out of range is ignored, so a bad file can never break startup."""
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f).get("layout", {})
        except Exception:
            return {}
        memory = {}
        if not isinstance(raw, dict):
            return memory
        for kind in ("name", "signature", "date"):
            entry = raw.get(kind)
            try:
                x_frac = min(1.0, max(0.0, float(entry["x_frac"])))
                y_frac = min(1.0, max(0.0, float(entry["y_frac"])))
                size = float(entry["size"])
            except (TypeError, KeyError, ValueError):
                continue
            if size > 0:
                memory[kind] = {"x_frac": x_frac, "y_frac": y_frac, "size": size}
        return memory

    @staticmethod
    def _load_last_used():
        """Last name text and signature path from the settings file, or
        (None, None). Never raises."""
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            name = data.get("last_name")
            sig = data.get("last_signature_path")
        except Exception:
            return None, None
        name = name.strip() if isinstance(name, str) and name.strip() else None
        sig = sig if isinstance(sig, str) and sig else None
        return name, sig

    def _remembered_width_px(self):
        """Remembered signature width in canvas pixels, or None."""
        entry = self.layout_memory.get("signature")
        if not entry:
            return None
        return int(round(min(600, max(30, entry["size"] * CANVAS_TARGET_WIDTH))))

    def _remembered_font_pt(self, kind):
        """Remembered font size in points for 'name'/'date', or None."""
        entry = self.layout_memory.get(kind)
        if not entry:
            return None
        return min(96, max(6, entry["size"]))

    def _touch(self, kind, item):
        """Note that this is the item of its kind to remember on save."""
        self._last_touched[kind] = item

    def _remember_layout(self):
        """Store position and size of the last-used name, signature and date
        so the next session drops them in the same place at the same size.
        Position is stored as a fraction of the page, so it carries over
        between page sizes. Kinds with nothing on the page keep whatever
        was remembered before. Best-effort: failure to write is non-fatal."""
        page = self.doc[self.page_index]
        height_px = page.rect.height * self.zoom
        for kind in ("name", "signature", "date"):
            items = self._items_for(kind)
            if not items:
                continue
            item = self._last_touched.get(kind)
            if item not in items:
                item = items[-1]
            cx, cy = item["canvas_xy"]
            size = (item["width_px"] / CANVAS_TARGET_WIDTH if kind == "signature"
                    else item["font_pt"])
            self.layout_memory[kind] = {
                "x_frac": min(1.0, max(0.0, cx / CANVAS_TARGET_WIDTH)),
                "y_frac": min(1.0, max(0.0, cy / height_px)),
                "size": size,
            }
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump({"layout": self.layout_memory,
                           "last_name": self._last_name,
                           "last_signature_path": self._last_sig_path}, f, indent=2)
        except Exception:
            return False
        return True

    def _default_position(self, kind):
        """Where a fresh item lands: the spot it was last left in (see
        _remember_layout), or on first use a row near the bottom of the page
        arranged left-to-right as name, signature, date. Successive items
        of the same kind are staggered slightly so they don't stack exactly
        on top of each other. The user drags each wherever it needs to go."""
        page = self.doc[self.page_index]
        height_px = page.rect.height * self.zoom
        entry = self.layout_memory.get(kind)
        if entry:
            base_x = CANVAS_TARGET_WIDTH * entry["x_frac"]
            base_y = height_px * entry["y_frac"]
        elif kind == "name":
            base_x, base_y = CANVAS_TARGET_WIDTH * 0.08, height_px * 0.85
        elif kind == "signature":
            base_x, base_y = CANVAS_TARGET_WIDTH * 0.38, height_px * 0.85
        else:  # "date"
            base_x, base_y = CANVAS_TARGET_WIDTH * 0.68, height_px * 0.85
        count = len(self.signature_items) if kind == "signature" else len(self.text_items[kind])
        offset = count * PLACEMENT_STAGGER_PX
        return base_x + offset, base_y + offset

    def _place_signature(self, path, orig_img, size_px, x, y, width_px=None):
        width_px = width_px or self._remembered_width_px() or SIGNATURE_DEFAULT_WIDTH_PX
        thumbnail = self._make_signature_thumbnail(orig_img, width_px)
        canvas_id = self.canvas.create_image(x, y, image=thumbnail,
                                              anchor="center", tags=("signature",))
        item = {
            "canvas_id": canvas_id,
            "handle_id": None,
            "canvas_xy": (x, y),
            "width_px": width_px,
            "path": path,
            "orig_img": orig_img,
            "size_px": size_px,
            "thumbnail": thumbnail,
        }
        self.signature_items.append(item)
        self._touch("signature", item)
        self._update_handle_for_item(item, "signature")
        self.undo_sig_btn.config(state="normal")
        self.modified = True
        self.status.set("Signature dropped in — drag it to reposition, drag its corner handle "
                         "to resize, or hover + Delete to remove just that one.")

    @staticmethod
    def _make_signature_thumbnail(orig_img, width_px):
        ratio = orig_img.height / orig_img.width
        width = max(10, int(round(width_px)))
        height = max(1, int(width * ratio))
        resized = orig_img.resize((width, height), Image.LANCZOS)
        return ImageTk.PhotoImage(resized)

    def _place_text(self, kind, x, y, text, font_pt=None):
        """Place a text overlay of the given kind ('date' or 'name')."""
        font_pt = font_pt or self._remembered_font_pt(kind) or TEXT_DEFAULT_FONT_PT
        disp_size = max(1, round(font_pt * self.zoom))
        canvas_id = self.canvas.create_text(x, y, text=text, fill="black",
                                             font=("Helvetica", disp_size), anchor="nw",
                                             tags=(kind,))
        item = {
            "canvas_id": canvas_id,
            "handle_id": None,
            "canvas_xy": (x, y),
            "text": text,
            "font_pt": font_pt,
        }
        self.text_items[kind].append(item)
        self._touch(kind, item)
        self._update_handle_for_item(item, kind)
        self._clear_btn_for[kind].config(state="normal")
        self.modified = True
        label = "Name" if kind == "name" else "Date"
        self.status.set(f"{label} dropped in — drag it to reposition, drag its corner handle to "
                         f"resize, or hover + Delete to remove just that one.")

    # ------------------------------------------------------------- Lookup ---
    def _items_for(self, kind):
        if kind == "signature":
            return self.signature_items
        return self.text_items[kind]

    def _find_item(self, kind, canvas_id):
        for item in self._items_for(kind):
            if item["canvas_id"] == canvas_id:
                return item
        return None

    def _find_item_by_handle(self, kind, handle_id):
        for item in self._items_for(kind):
            if item["handle_id"] == handle_id:
                return item
        return None

    def _item_at(self, x, y):
        """Return (kind, canvas_id) for whichever overlay is at (x, y),
        preferring the topmost if several overlap, or None."""
        overlapping = self.canvas.find_overlapping(x - 1, y - 1, x + 1, y + 1)
        for item_id in reversed(overlapping):  # topmost first
            tags = self.canvas.gettags(item_id)
            if "signature" in tags:
                return "signature", item_id
            if "date" in tags:
                return "date", item_id
            if "name" in tags:
                return "name", item_id
        return None

    # --------------------------------------------------------------- Drag ---
    def _start_drag(self, item_type, event):
        ids = self.canvas.find_withtag("current")
        if not ids:
            return
        self._drag_type = item_type
        self._drag_canvas_id = ids[0]

    def _do_drag(self, event):
        if self._drag_type is None or self._drag_canvas_id is None:
            return
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        item = self._find_item(self._drag_type, self._drag_canvas_id)
        if not item:
            return
        self.canvas.coords(self._drag_canvas_id, x, y)
        item["canvas_xy"] = (x, y)
        self._update_handle_for_item(item, self._drag_type)
        self._touch(self._drag_type, item)
        self.modified = True

    def _end_drag(self, _event):
        self._drag_type = None
        self._drag_canvas_id = None

    # ------------------------------------------------------- Resize handle ---
    def _update_handle_for_item(self, item, kind):
        """(Re)position the small draggable resize-handle square at the
        bottom-right corner of this item's current bounding box."""
        tag = {"signature": "sig_handle", "date": "date_handle", "name": "name_handle"}[kind]
        bbox = self.canvas.bbox(item["canvas_id"])
        if not bbox:
            return
        x1, y1 = bbox[2], bbox[3]
        half = 6
        handle_id = item.get("handle_id")
        if handle_id:
            self.canvas.coords(handle_id, x1 - half, y1 - half, x1 + half, y1 + half)
        else:
            handle_id = self.canvas.create_rectangle(
                x1 - half, y1 - half, x1 + half, y1 + half,
                fill="#2f6fed", outline="white", width=1,
                tags=("resize_handle", tag),
            )
            item["handle_id"] = handle_id
        # Keep the handle drawn above the item it belongs to.
        self.canvas.tag_raise(handle_id)

    def _start_resize(self, kind, event):
        ids = self.canvas.find_withtag("current")
        if not ids:
            return
        handle_id = ids[0]
        item = self._find_item_by_handle(kind, handle_id)
        if not item:
            return
        self._resize_type = kind
        self._resize_handle_id = handle_id
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if kind == "signature":
            cx, cy = item["canvas_xy"]
            self._resize_start_dist = max(1.0, math.hypot(x - cx, y - cy))
            self._resize_start_value = item["width_px"]
        else:
            x0, y0 = item["canvas_xy"]
            self._resize_start_dist = max(1.0, math.hypot(x - x0, y - y0))
            self._resize_start_value = item["font_pt"]

    def _do_resize_drag(self, event):
        if self._resize_type is None or self._resize_handle_id is None:
            return
        item = self._find_item_by_handle(self._resize_type, self._resize_handle_id)
        if not item:
            return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

        if self._resize_type == "signature":
            cx, cy = item["canvas_xy"]
            dist = max(1.0, math.hypot(x - cx, y - cy))
            factor = dist / self._resize_start_dist
            new_width = max(30, min(600, self._resize_start_value * factor))
            item["width_px"] = int(round(new_width))
            item["thumbnail"] = self._make_signature_thumbnail(item["orig_img"], item["width_px"])
            self.canvas.itemconfig(item["canvas_id"], image=item["thumbnail"])
            self._update_handle_for_item(item, "signature")

        else:  # "date" or "name" text overlay
            x0, y0 = item["canvas_xy"]
            dist = max(1.0, math.hypot(x - x0, y - y0))
            factor = dist / self._resize_start_dist
            new_pt = max(6, min(96, self._resize_start_value * factor))
            item["font_pt"] = new_pt
            disp_size = max(1, round(new_pt * self.zoom))
            self.canvas.itemconfig(item["canvas_id"], font=("Helvetica", disp_size))
            self._update_handle_for_item(item, self._resize_type)

        self._touch(self._resize_type, item)
        self.modified = True

    def _end_resize(self, _event):
        self._resize_type = None
        self._resize_handle_id = None

    # ------------------------------------------------------------- Delete ---
    # -------------------------------------------------------------- Scroll ---
    def _on_mousewheel_y(self, event):
        # event.delta is ±120 per notch on Windows, a small integer on
        # macOS — either way, treat any wheel tick as one scroll unit.
        direction = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(direction, "units")

    def _on_mousewheel_x(self, event):
        direction = -1 if event.delta > 0 else 1
        self.canvas.xview_scroll(direction, "units")

    def _on_delete_key(self, event):
        # Use the mouse position carried on the key event rather than
        # tracking focus/selection state, so whichever specific instance is
        # under the cursor gets removed — not "the" signature/date/name,
        # since there can be several.
        cx = event.x_root - self.canvas.winfo_rootx()
        cy = event.y_root - self.canvas.winfo_rooty()
        x, y = self.canvas.canvasx(cx), self.canvas.canvasy(cy)
        found = self._item_at(x, y)
        if not found:
            return
        kind, canvas_id = found
        self._remove_instance(kind, canvas_id)
        label = {"signature": "Signature", "date": "Date", "name": "Name"}[kind]
        self.status.set(f"{label} deleted.")

    def _remove_instance(self, kind, canvas_id):
        item = self._find_item(kind, canvas_id)
        if not item:
            return
        self.canvas.delete(item["canvas_id"])
        if item.get("handle_id"):
            self.canvas.delete(item["handle_id"])
        self._items_for(kind).remove(item)
        if not self._items_for(kind):
            self._clear_btn_for[kind].config(state="disabled")
        self.modified = True

    # Kept as thin, explicitly-named wrappers since other code/tests refer
    # to them directly for clarity.
    def _remove_signature_instance(self, canvas_id):
        self._remove_instance("signature", canvas_id)

    def _clear_all_signatures(self):
        for item in list(self.signature_items):
            self._remove_instance("signature", item["canvas_id"])
        self.status.set("All signatures cleared.")

    def _clear_all_text(self, kind):
        for item in list(self.text_items[kind]):
            self._remove_instance(kind, item["canvas_id"])
        label = "names" if kind == "name" else "dates"
        self.status.set(f"All {label} cleared.")

    # -------------------------------------------------------------- Save ---
    def _save_pdf(self):
        if not self.doc:
            return
        has_anything = self.signature_items or any(self.text_items[k] for k in TEXT_KINDS)
        if not has_anything:
            if not messagebox.askyesno("Nothing placed",
                                        "No signature, name, or date has been placed. Save anyway?"):
                return

        out_path = filedialog.asksaveasfilename(
            title="Save signed PDF as",
            defaultextension=".pdf",
            initialdir=os.path.dirname(os.path.abspath(self.pdf_path)),
            initialfile=os.path.splitext(os.path.basename(self.pdf_path))[0] + "_signed.pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if not out_path:
            return

        page = self.doc[self.page_index]

        for item in self.signature_items:
            cx, cy = item["canvas_xy"]
            # Convert canvas pixel coords -> PDF points
            pdf_cx, pdf_cy = cx / self.zoom, cy / self.zoom
            sig_w_pt = item["width_px"] / self.zoom
            sig_h_pt = sig_w_pt * (item["size_px"][1] / item["size_px"][0])
            rect = fitz.Rect(
                pdf_cx - sig_w_pt / 2, pdf_cy - sig_h_pt / 2,
                pdf_cx + sig_w_pt / 2, pdf_cy + sig_h_pt / 2,
            )
            page.insert_image(rect, filename=item["path"])

        for kind in TEXT_KINDS:
            for item in self.text_items[kind]:
                cx, cy = item["canvas_xy"]
                pdf_cx, pdf_cy = cx / self.zoom, cy / self.zoom
                page.insert_text(
                    (pdf_cx, pdf_cy + item["font_pt"]),  # insert_text anchors baseline
                    item["text"], fontsize=item["font_pt"], fontname="helv",
                )

        try:
            self.doc.save(out_path, garbage=4, deflate=True)
        except Exception as exc:
            messagebox.showerror("Failed to save", str(exc))
            return

        remembered = self._remember_layout()
        self.status.set(f"Saved: {out_path}" if remembered else
                         f"Saved: {out_path} (couldn't write {os.path.basename(SETTINGS_PATH)}, "
                         f"so the layout won't be remembered)")
        self.modified = False
        messagebox.showinfo("Saved", f"Signed PDF saved to:\n{out_path}")


if __name__ == "__main__":
    PDFSignerApp().mainloop()
