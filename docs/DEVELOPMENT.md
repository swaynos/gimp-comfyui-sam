# Developer Guide

This guide covers the architecture, development workflow, coding constraints, and extension points for contributors working on `gimp-comfyui-sam`.

---

## 1. Codebase Architecture

The project is structured with a strict separation between **pure-Python business logic** (runnable anywhere without GIMP) and **GIMP/GTK runtime adapters**:

```text
gimp-comfyui-sam/
├── plug-ins/gimp-comfyui-sam/     # Main plug-in sources
│   ├── gimp-comfyui-sam.py        # Entry point: registers GIMP procedures
│   ├── sam_core.py                # Pure-Python: data models, transforms, request queue
│   ├── sam_png.py                 # Pure-Python: lightweight PNG chunk encoder/decoder
│   ├── sam_comfy.py               # Pure-Python: ComfyUI HTTP client, .env loader
│   ├── sam_gimp.py                # GIMP adapters: pixel buffers, selection application
│   └── sam_editor.py              # GTK UI: canvas, point overlays, settings dialogs
├── tests/                         # Unit tests (runnable with standard Python unittest)
│   ├── test_core.py               # Coordinates, view transforms, request lifecycle
│   ├── test_png.py                # PNG encoding and buffer safety limits
│   └── test_comfy.py              # ComfyUI HTTP contract, serialization, .env loading
├── tools/                         # Headless validation harnesses and smoke tests
│   ├── backend_smoke.py           # Live ComfyUI endpoint fixture test
│   ├── gimp_smoke.py              # Headless GIMP pixel and selection adapter checks
│   ├── editor_smoke.py            # Headless GTK editor window construction test
│   ├── project_apply_probe.py     # In-memory test probe for custom XCF/image files
│   └── procedure_apply_driver.py  # Batch procedure driver
└── Makefile                       # Build and install automation (test, install)
```

### Module Responsibilities

| File | Dependencies | Purpose |
| --- | --- | --- |
| `sam_core.py` | Python stdlib | Core domain models (`Point`, `GenerationIdentity`), `ViewTransform` (pan/zoom viewport calculations), `RequestSlot` (single-flight concurrency management), and pixel validation logic. |
| `sam_png.py` | Python stdlib (`zlib`, `struct`) | Minimal, dependency-free PNG encoder and chunk parser for high-speed mask transmission. |
| `sam_comfy.py` | Python stdlib (`http.client`, `json`, `os`, `pathlib`) | Bounded ComfyUI HTTP client, prompt workflow generation, `.env` file loading, and endpoint normalization. |
| `sam_gimp.py` | `gi.repository` (`Gimp`, `Gegl`, `Babl`) | Bridge between GIMP's GEGL image buffers and raw pixel bytearrays. Manages undo groups, selection channel creation, and cleanup. |
| `sam_editor.py` | `gi.repository` (`Gtk`, `Gdk`, `cairo`, `GdkPixbuf`) | Interactive Cairo-based point canvas, view controls, modal/non-modal dialogs, and async worker threads. |
| `gimp-comfyui-sam.py` | `gi.repository` (`Gimp`, `GLib`) | GIMP 3 `Gimp.PlugIn` implementation registering `python-fu-comfyui-sam-selection` (ImageProcedure). |

---

## 2. Core Development Constraints

When contributing to this repository, follow these design rules:

### Zero External Python Dependencies
- **Do not add packages to requirements or install via pip.**
- The plug-in must run entirely on the Python environment bundled inside the official GIMP Flatpak / package distribution.
- Use only Python standard library modules (`http.client`, `json`, `struct`, `urllib`, `pathlib`, etc.) and GIMP runtime GI bindings (`Gimp`, `Gegl`, `Gtk`, `GdkPixbuf`, `cairo`).

### Pure-Python Testability
- Modules `sam_core.py`, `sam_png.py`, and `sam_comfy.py` must **never import `gi` or GTK**.
- Any feature, formula, or transform that does not directly manipulate GIMP UI widgets or GIMP image buffers belongs in `sam_core.py` or `sam_comfy.py`, where it can be tested instantly via `make test` without GIMP.

### Document and Selection Safety
- **Always wrap selection edits in GIMP undo groups** (`image.undo_group_start()` / `image.undo_group_end()`).
- Always clean up temporary channels in a `finally` block, even if an exception is thrown.
- Never write to or overwrite source image files on disk. Selections are applied only to the in-memory document.

### Configured Safety Limits
- Maximum source / mask dimensions: 100,000,000 pixels.
- Maximum downloaded mask PNG: 256 MiB.
- HTTP inactivity timeout: 15 seconds per request.
- Overall generation job timeout: 600 seconds.

---

## 3. Local Development Workflow

### Rapid Iteration with Symlinks

Instead of running `make install` after every edit, you can symlink the plug-in directory directly into GIMP's plug-in folder:

```sh
# Remove existing installed folder if present
rm -rf ~/.config/GIMP/3.2/plug-ins/gimp-comfyui-sam

# Create a symlink pointing to your repository checkout
ln -s "$(pwd)/plug-ins/gimp-comfyui-sam" ~/.config/GIMP/3.2/plug-ins/gimp-comfyui-sam
```

With a symlink in place, any edits you make in `plug-ins/gimp-comfyui-sam/` take effect immediately the next time you launch GIMP or restart the plug-in procedure.

### Testing Workflow

Always run the fast test suite before committing changes:

```sh
# 1. Deterministic unit tests (< 1s)
make test

# 2. Syntax check
python3 -m py_compile plug-ins/gimp-comfyui-sam/*.py tools/*.py tests/*.py

# 3. Headless GIMP smoke tests (via Flatpak)
flatpak run org.gimp.GIMP -i --batch-interpreter python-fu-eval -b '
import sys; sys.path.insert(0, "tools")
import gimp_smoke; gimp_smoke.main()
import editor_smoke; editor_smoke.main()
' --quit
```

---

## 4. Extending the Plug-in

### Adding or Modifying ComfyUI Workflows
- The workflow template is defined in `sam_comfy.py` (`build_workflow()`).
- Output nodes must feed into a `MaskPreview` node producing a valid PNG mask matching the source dimensions.
- If new parameters are introduced (e.g. model selection, box prompts), serialize them explicitly into the workflow dictionary and add corresponding tests in `tests/test_comfy.py`.

### Adding UI Controls
- All UI elements are defined in `sam_editor.py`.
- Canvas interactions (clicks, drags, overlays) belong in `PointCanvas`.
- Settings inputs belong in the collapsible `Inference Settings` expander.
- Persisted settings are stored in JSON format via `load_settings()` / `save_settings()` in `sam_gimp.py`. Ensure any new setting includes a sensible default.

