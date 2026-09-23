# gimp-comfyui-sam

Point-guided SAM selection for GIMP, powered by ComfyUI, with a fast preview
editor for positive and negative prompts.

Mark what to include and exclude in a dedicated image preview, submit both
point sets together, and bring the resulting mask back into GIMP as a selection.

## Project status

The repository contains an installable GIMP 3 Python plug-in and deterministic
tests for its coordinate transforms, request lifecycle, PNG encoding, mask
validation, and ComfyUI HTTP contract. Live GIMP acceptance and large-image
performance evidence are still required before a release.

## Install and test

The initial verified layout is Flatpak GIMP 3.2 on Linux:

```sh
make test
make install
```

Restart GIMP after installation, then open **Select > ComfyUI SAM Selection**.

## Backend configuration

The ComfyUI backend endpoint can be configured through three methods:

### 1. Local environment file (`.env`)
For tests and local development code, create a `.env` file from the example:

```sh
cp .env.example .env
```

Edit `.env` to specify your ComfyUI server address:

```env
COMFYUI_ENDPOINT=http://127.0.0.1:8188
```

This `.env` file is automatically detected and loaded by the test suite (`make test`),
CLI tools (`tools/backend_smoke.py`), and the plug-in.

### 2. GIMP editor panel
The backend URL can be configured directly inside GIMP in the **Select > ComfyUI SAM Selection...** window:
- In the **Inference Settings** panel, enter your **Server URL**.
- Click **Test Connection** to verify server connectivity and SAM model availability.
- Click **Save URL** (or run a successful connection test) to persist the endpoint across sessions in
  `~/.config/GIMP/3.2/plug-in-settings/gimp-comfyui-sam.json`.

### 3. Environment variable
Set the environment variable directly in your shell or launch script:

```sh
export COMFYUI_ENDPOINT="http://127.0.0.1:8188"
```


## Scope

- Install into an existing GIMP 3 installation. No custom GIMP build.
- Use a required ComfyUI backend for SAM inference.
- Prepare positive and negative points together in the plugin's own editor.
- Keep large-image interaction fast through a cached, scaled preview and
  independent point overlays.
- Apply a validated result as an undoable GIMP selection.

The plugin does not replace Fuzzy Select or register a native toolbox tool.
The editor is described as a panel in the product concept; native docking
support needs verification. A plugin-owned window is the initial implementation
baseline.

## Intended workflow

1. Open the SAM editor from a GIMP menu action.
2. Choose the active layer or the visible image as the source.
3. Place positive and negative points in the preview.
4. Generate a mask through ComfyUI and inspect the result.
5. Apply the result as a selection, or adjust points and generate again.

## Documentation

| Document | Purpose |
| --- | --- |
| [Requirements](docs/REQUIREMENTS.md) | Product scope, interaction, and acceptance criteria |
| [Architecture](docs/ARCHITECTURE.md) | Preview, coordinates, caching, and request lifecycle |
| [Editor UI/UX](docs/EDITOR_UX.md) | Window modality, canvas interaction, controls, and status feedback |
| [ComfyUI contract](docs/COMFYUI.md) | Workflow, payloads, API calls, and compatibility |
| [Decisions and proof gates](docs/DECISIONS.md) | Fixed v1 choices, unverified runtime questions, and blockers |
| [Acceptance specification](docs/ACCEPTANCE.md) | Traceable live, backend, lifecycle, and performance checks |
| [Developer guide](docs/DEVELOPMENT.md) | Architecture, codebase structure, coding constraints, and development workflow |
| [Source support record](docs/SOURCE_SUPPORT.md) | Exact enabled and rejected source representations |
| [Verification guide](docs/VERIFICATION.md) | Reproducible automated suites, headless smoke tests, and manual validation |

## Initial environment

The initial target is GIMP 3.2.6 installed through Flatpak on Linux Mint.
The backend endpoint is configurable (defaulting to `http://127.0.0.1:8188` or
`COMFYUI_ENDPOINT`), serving SAM through ComfyUI. Other environments require
their own verification.

The plug-in has no third-party Python dependency. It uses the Python, GI, GTK,
GEGL, and GdkPixbuf modules bundled with the GIMP Flatpak plus the Python
standard library for HTTP.
