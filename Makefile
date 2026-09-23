PYTHON ?= python3
GIMP_VERSION ?= 3.2
PLUGIN_NAME := gimp-comfyui-sam
SOURCE_DIR := plug-ins/$(PLUGIN_NAME)
PLUGIN_DIR ?= $(HOME)/.config/GIMP/$(GIMP_VERSION)/plug-ins/$(PLUGIN_NAME)

.PHONY: test install

test:
	$(PYTHON) -m unittest discover -s tests -v

install:
	install -d -m 0755 "$(PLUGIN_DIR)"
	install -m 0755 "$(SOURCE_DIR)/$(PLUGIN_NAME).py" "$(PLUGIN_DIR)/$(PLUGIN_NAME).py"
	install -m 0644 "$(SOURCE_DIR)/sam_core.py" "$(PLUGIN_DIR)/sam_core.py"
	install -m 0644 "$(SOURCE_DIR)/sam_png.py" "$(PLUGIN_DIR)/sam_png.py"
	install -m 0644 "$(SOURCE_DIR)/sam_comfy.py" "$(PLUGIN_DIR)/sam_comfy.py"
	install -m 0644 "$(SOURCE_DIR)/sam_gimp.py" "$(PLUGIN_DIR)/sam_gimp.py"
	install -m 0644 "$(SOURCE_DIR)/sam_editor.py" "$(PLUGIN_DIR)/sam_editor.py"
