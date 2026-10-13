# PDF Signer

A small desktop GUI for signing PDFs by hand: drag a PDF in, drop on as many
signatures, typed names, and dates as you need, drag them into place, and
save.

## Features

- **Mouse-wheel scrolling**: scroll the wheel to move the page view up and
  down, hold Shift while scrolling to move it left and right.
- **Drag and drop** a PDF onto the window (or use "Open PDF...").
- **Type your name** to drop in a typed name (handy alongside — or instead
  of — a drawn signature, e.g. a "print name" line). You can optionally
  save the typed name to a text file and **load a previously-saved name**
  later instead of retyping it.
- **Draw a signature** with the mouse in a popup pad, saved as a PNG — or
  **load a previously-saved signature PNG** to reuse it.
- Signatures, typed names, and today's date **drop onto the page
  automatically** — no click-to-place step, no confirmation dialogs.
- **Add as many signatures, names, and dates as you like.** Each one is
  independent.
- **Drag** any signature, name, or date to reposition it.
- **Resize** any signature, name, or date by dragging the small blue handle
  at its bottom-right corner.
- **Remembers your layout**: when you save a signed PDF, the position and
  size of your name, signature, and date are remembered, and next time they
  drop in at that same spot and size (see Notes).
- **Remove one at a time**: hover over a signature, name, or date and press
  `Delete` or `Backspace`.
- **Clear All Names** / **Clear All Signatures** / **Clear All Dates**
  buttons to wipe everything of that kind at once.
- **Save Signed PDF As...** composites everything onto the actual PDF (not
  a flattened image) and saves a new file — your original is left untouched.
  The save dialog defaults to the same folder the PDF was dropped from.
- Signature PNGs and saved-name text files default to the folder the
  **script itself** lives in when you save or load them — a separate,
  consistent spot from wherever your PDFs happen to be.
- **Unsaved-changes prompt**: closing the window with unsaved edits asks
  whether to save, discard, or cancel.
- Dates are written in ISO 8601 format (`YYYY-MM-DD`).

## Requirements

- Python 3
- Dependencies: `pymupdf`, `pillow`, `tkinterdnd2`

These are installed automatically the first time you run the script if
they're missing (via `pip install --break-system-packages`). To install
them yourself instead:

```bash
pip install pymupdf pillow tkinterdnd2
```

## Usage

```bash
python pdf_signer.py
# or, on Windows, just double-click pdf_signer.pyw
```

1. Drag a PDF file onto the window (or click **Open PDF...**).
2. Click **Type Name...** to type a name (e.g. for a "print name" line) and
   drop it onto the page automatically. You'll be asked whether to save the
   typed name to a text file for reuse — say yes once and use
   **Load Name...** next time instead of retyping.
3. Click **Draw Signature** to scribble one with the mouse, or
   **Load Signature...** to reuse a PNG you saved earlier. Both dialogs
   default to the folder the script is running from. The signature drops
   onto the page automatically — drag it into place and use its corner
   handle to resize it.
4. Click **Add Today's Date** to drop today's date onto the page the same
   way.
5. Repeat steps 2–4 for as many signatures/names/dates as the document
   needs (e.g. initialing multiple pages, or a signature plus a witness
   line).
6. To remove one, hover over it and press `Delete`/`Backspace`. To remove
   every name, every signature, or every date at once, use the matching
   **Clear All** button (in that order on the toolbar).
7. Click **Save Signed PDF As...** to save the result. It defaults to the
   same folder as the original PDF, with `_signed` appended to the name.
   Saving also remembers where you left your name, signature, and date, and
   how big they were, so next time they appear there already.

## Notes

- Toolbar button order, left to right: **Open PDF...**, **Type Name...**,
  **Load Name...**, **Draw Signature**, **Load Signature...**,
  **Add Today's Date**, **Clear All Names**, **Clear All Signatures**,
  **Clear All Dates**, with **Save Signed PDF As...** docked on the right.
- **Remembered layout.** On the very first use, items drop onto a row near
  the bottom of the page, left to right as **name, signature, date**, with
  small default sizes. After that, each time you click **Save Signed PDF
  As...** the position and size of your name, signature, and date are stored
  in `pdf_signer_settings.json` next to the script, and the next items you
  drop in start there instead.
  - If you've placed several of one kind, the one you placed, moved, or
    resized most recently is the one remembered.
  - Position is stored relative to the page (as a fraction of its width and
    height), so it still lands sensibly on a different page size.
  - A kind you didn't use in a given save (say, no name this time) keeps
    its previously remembered layout.
  - Nothing is remembered until you save; closing without saving leaves the
    stored layout as it was.
  - To go back to the built-in default layout, delete
    `pdf_signer_settings.json`. If that file is missing, unreadable, or
    can't be written, the app simply uses the defaults and signing still
    works.
- Only the first page of the PDF is currently signable.
- Signature PNGs (from the drawing pad or **Load Signature...**) and saved
  name text files (from **Type Name...** or **Load Name...**) all default
  their save/open dialogs to the folder the script itself is running
  from — separate from the PDF's own folder, which only the final
  **Save Signed PDF As...** dialog uses.
- All positioning and sizing math converts between on-screen pixels and PDF
  points, so what you see on screen matches what ends up in the saved file.
