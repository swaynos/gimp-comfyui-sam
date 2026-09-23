# Verification and Validation Guide

This guide provides reproducible validation steps for contributors to verify `gimp-comfyui-sam` using automated test suites, headless smoke tests, and live validation with custom image assets.

---

## 1. Prerequisites and Setup

1. **Runtime Environment**:
   - Flatpak GIMP 3.2+ on Linux (`org.gimp.GIMP`) or a compatible native GIMP 3 installation.
   - Python 3.10+ with standard library.
2. **Backend**:
   - A running ComfyUI instance with `sam3.1_multiplex_fp16.safetensors` in `models/checkpoints/` and required nodes (`LoadImage`, `CheckpointLoaderSimple`, `SAM3_Detect`, `MaskPreview`).
3. **Configuration**:
   Copy `.env.example` to `.env` and set your endpoint URL:
   ```sh
   cp .env.example .env
   # Edit .env:
   # COMFYUI_ENDPOINT=http://127.0.0.1:8188
   ```

---

## 2. Automated Test Suite

Run the deterministic unit test suite:

```sh
make test
```

This validates:
- Coordinate transforms and viewport zoom/pan math
- Request slot lifecycle and queuing logic
- PNG encoding and decode buffer safety limits
- Mask polarity, uniformity, and RGB/RGBA conversion
- ComfyUI HTTP client serialization, headers, and error handling
- `.env` and environment variable configuration handling

To check code syntax across all modules:

```sh
python3 -m py_compile plug-ins/gimp-comfyui-sam/*.py tools/*.py tests/*.py
```

---

## 3. Headless GIMP Smoke Tests

Install the plug-in to the user plug-in directory:

```sh
make install
```

### 3.1 Procedure Registration Check

Verify that the selection procedure registers cleanly with GIMP:

```sh
flatpak run org.gimp.GIMP -i --batch-interpreter python-fu-eval -b '
import gi; gi.require_version("Gimp", "3.0")
from gi.repository import Gimp
proc = Gimp.get_pdb().lookup_procedure("python-fu-comfyui-sam-selection")
print(f"python-fu-comfyui-sam-selection: {proc.get_menu_label() if proc else \"MISSING\"}")
' --quit
```

### 3.2 GIMP Adapter Smoke Test

Tests active-layer offsets, Sample Merged extent, clipping, four selection modes, revision tracking, and mask decoding inside GIMP:

```sh
flatpak run org.gimp.GIMP -i --batch-interpreter python-fu-eval -b '
import sys; sys.path.insert(0, "tools")
import gimp_smoke; gimp_smoke.main()
' --quit
```

Expected output ends with:
```text
PASS active-offset merged selection-modes clipping revision mask-decode pixels
```

### 3.3 Editor Window Construction Test

Verifies GTK window layout, event loop execution, Apply button sensitivity transitions, and clean disposal:

```sh
flatpak run org.gimp.GIMP -i --batch-interpreter python-fu-eval -b '
import sys; sys.path.insert(0, "tools")
import editor_smoke; editor_smoke.main()
' --quit
```

Expected output ends with:
```text
PASS editor-window Current Apply callback selection event-loop close
```

---

## 4. Live Backend Verification

Run the synthetic backend verification tool against your ComfyUI server:

```sh
# Uses endpoint configured in .env or COMFYUI_ENDPOINT:
python3 tools/backend_smoke.py

# Or explicitly pass an endpoint:
python3 tools/backend_smoke.py http://127.0.0.1:8188
```

This sends a synthetic fixture image with positive and negative points, verifies prompt queuing, tests source image upload reuse, and asserts correct foreground mask polarity.

---

## 5. Interactive Validation with Custom Assets

1. Open any photo or illustration in GIMP containing distinct subjects.
2. Ensure a raster layer is selected, then open **Select > ComfyUI SAM Selection...**.
3. **Configure & Test Backend**:
   - In the **Inference Settings** panel, enter your ComfyUI Server URL.
   - Click **Test Connection** (and **Save URL**). Confirm status reports server is reachable and compatible.
4. **Place Points**:
   - Left-click on the desired subject to place a green positive point (`+`).
   - Shift+left-click (or right-click) on the background to place a red negative point (`-`).
5. **Inspect Preview**:
   - Click **Generate**.
   - Verify that the tinted mask overlay accurately covers the target object.
   - Press **Tab** (or toggle **Peek**) to toggle the mask overlay on and off against the source pixels.
   - Adjust the **Opacity** slider to verify preview transparency.
5. **Apply Selection**:
   - Choose a selection mode (default: **Replace**).
   - Click **Apply**.
   - Verify the status bar displays the count of selected pixels (e.g., `Applied to GIMP: 42,115 selected pixels`).
   - Confirm that the marching ants selection outline appears on the canvas in GIMP (if hidden, toggle `Ctrl+T` or **View → Show Selection**).
6. **Selection Combination Modes**:
   - With an active selection on the canvas, open the editor again.
   - Segment a second object and test **Add**, **Subtract**, or **Intersect** modes.
   - Confirm the combined selection reflects the chosen operation.
7. **Single-Step Undo**:
   - Close the editor.
   - Press `Ctrl+Z` in GIMP. Verify that the entire selection operation undoes cleanly in a single history step.

### 5.3 Automated Probing on Custom Images / XCF Files

To test headless adapter execution against a specific image or `.xcf` file without GUI interaction:

```sh
flatpak run org.gimp.GIMP -i --batch-interpreter python-fu-eval -b '
import sys; sys.path.insert(0, "tools")
import project_apply_probe
project_apply_probe.probe("/path/to/your/image.xcf")
' --quit
```

This probe:
- Loads the image into memory without modifying the file on disk.
- Reports dimensions, layer structure, and active selection coverage.
- Captures the source snapshot and applies a synthetic mask.
- Verifies that the selection is created and read back successfully.

---

## 6. Pre-Release Checklist

- [ ] All unit tests pass: `make test`
- [ ] Headless GIMP adapter and editor smoke tests pass
- [ ] Synthetic backend smoke test passes against live ComfyUI instance
- [ ] Interactive selection tested with positive/negative points on custom image
- [ ] Selection modes (**Replace**, **Add**, **Subtract**, **Intersect**) verified
- [ ] Single-step undo verified in GIMP undo history
- [ ] No hardcoded URLs, hostnames, or machine-specific paths present in code

