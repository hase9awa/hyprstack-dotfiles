CC ?= cc
SCANNER ?= wayland-scanner
BUILD ?= build
PROTOCOLS := $(shell pkg-config --variable=pkgdatadir wayland-protocols)
CFLAGS ?= -O2 -g
CFLAGS += -std=c11 -Wall -Wextra -Wpedantic
CPPFLAGS += $(shell pkg-config --cflags wayland-client) -I$(BUILD)
LDLIBS += $(shell pkg-config --libs wayland-client)

GENERATED := $(BUILD)/layer-shell.h $(BUILD)/layer-shell.c \
             $(BUILD)/single-pixel.h $(BUILD)/single-pixel.c \
             $(BUILD)/presentation.h $(BUILD)/presentation.c $(BUILD)/xdg-shell.c

.PHONY: all
all: $(BUILD)/hyprstack-vrr-pixel

$(BUILD):
	mkdir -p $@

$(BUILD)/layer-shell.h: protocols/wlr-layer-shell-v1.xml | $(BUILD)
	$(SCANNER) client-header $< $@
$(BUILD)/layer-shell.c: protocols/wlr-layer-shell-v1.xml | $(BUILD)
	$(SCANNER) private-code $< $@
$(BUILD)/single-pixel.h: $(PROTOCOLS)/staging/single-pixel-buffer/single-pixel-buffer-v1.xml | $(BUILD)
	$(SCANNER) client-header $< $@
$(BUILD)/single-pixel.c: $(PROTOCOLS)/staging/single-pixel-buffer/single-pixel-buffer-v1.xml | $(BUILD)
	$(SCANNER) private-code $< $@
$(BUILD)/presentation.h: $(PROTOCOLS)/stable/presentation-time/presentation-time.xml | $(BUILD)
	$(SCANNER) client-header $< $@
$(BUILD)/presentation.c: $(PROTOCOLS)/stable/presentation-time/presentation-time.xml | $(BUILD)
	$(SCANNER) private-code $< $@
$(BUILD)/xdg-shell.c: $(PROTOCOLS)/stable/xdg-shell/xdg-shell.xml | $(BUILD)
	$(SCANNER) private-code $< $@

$(BUILD)/hyprstack-vrr-pixel: pixel.c $(GENERATED)
	$(CC) $(CPPFLAGS) $(CFLAGS) pixel.c $(BUILD)/layer-shell.c $(BUILD)/single-pixel.c $(BUILD)/presentation.c $(BUILD)/xdg-shell.c $(LDFLAGS) $(LDLIBS) -o $@
