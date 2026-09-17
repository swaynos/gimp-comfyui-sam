# gimp-comfyui-sam

Point-guided SAM selection for GIMP, powered by ComfyUI, with a fast preview
editor for positive and negative prompts.

Mark what to include and exclude in a dedicated image preview, submit both
point sets together, and bring the resulting mask back into GIMP as a selection.

## Project status

This repository currently contains project documentation. It does not yet
contain an installable plugin, a tested editor, or a release.

An earlier standalone test outside this repository retrieved a same-size SAM
mask from ComfyUI. That establishes an initial backend proof, not a working
GIMP integration or a large-image performance result.

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
| [ComfyUI contract](docs/COMFYUI.md) | Workflow, payloads, API calls, and compatibility |
| [Decisions and proof gates](docs/DECISIONS.md) | Fixed v1 choices, unverified runtime questions, and blockers |
| [Acceptance specification](docs/ACCEPTANCE.md) | Traceable live, backend, lifecycle, and performance checks |
| [Development and verification](docs/DEVELOPMENT.md) | Milestones, evidence rules, and release record |

## Initial environment

The initial target is GIMP 3.2.6 installed through Flatpak on Linux Mint.
The development backend is `http://callisto:28188`, serving SAM through ComfyUI
on an RTX 5060 Ti. The endpoint must be configurable; other environments require
their own verification.

Installation and usage commands will be added when the plugin exists and those
commands have been tested.
