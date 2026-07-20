# PDF Signer

A small desktop GUI for signing PDFs by hand: drag a PDF in, drop on as many
signatures and dates as you need, drag them into place, and save.

## Features

- **Drag and drop** a PDF onto the window (or use "Open PDF...").
- **Draw a signature** with the mouse in a popup pad, saved as a PNG — or
  **load a previously-saved signature PNG** to reuse it.
- Signatures and today's date **drop onto the page automatically** — no
  click-to-place step, no confirmation dialogs.
- **Add as many signatures and dates as you like.** Each one is independent.
- **Drag** any signature or date to reposition it.
- **Resize** any signature or date by dragging the small blue handle at its
  bottom-right corner.
- **Remove one at a time**: hover over a signature or date and press
  `Delete` or `Backspace`.
- **Clear All Signatures** / **Clear All Dates** buttons to wipe everything
  of that kind at once.
- **Save Signed PDF As...** composites everything onto the actual PDF (not
  a flattened image) and saves a new file — your original is left untouched.
  The save dialog defaults to the same folder the PDF was dropped from.
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
2. Click **Draw Signature** to scribble one with the mouse, or
   **Load Signature...** to reuse a PNG you saved earlier.
3. The signature drops onto the page automatically. Drag it into place and
   use its corner handle to resize it.
4. Click **Add Today's Date** to drop today's date onto the page the same
   way.
5. Repeat steps 2–4 for as many signatures/dates as the document needs
   (e.g. initialing multiple pages, or a signature plus a witness line).
6. To remove one, hover over it and press `Delete`/`Backspace`. To remove
   every signature or every date at once, use the **Clear All** buttons.
7. Click **Save Signed PDF As...** to save the result. It defaults to the
   same folder as the original PDF, with `_signed` appended to the name.

## Notes

- Only the first page of the PDF is currently signable.
- Signature PNGs you save from the drawing pad can be reused later via
  **Load Signature...** — handy if you sign the same way repeatedly.
- All positioning and sizing math converts between on-screen pixels and PDF
  points, so what you see on screen matches what ends up in the saved file.
