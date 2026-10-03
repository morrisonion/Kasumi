# The HOME Menu shortcut template (see source/main.c). Kasumi embeds the
# built resources/shortcut.cia and rewrites its title ID, icon and banner for
# each game, so the main build needs only devkitPro.
#
# Rebuild it (from devkitPro MSYS) after changing the shortcut:
#   make -C shortcut MAKEROM=/path/to/makerom BANNERTOOL=/path/to/bannertool

.SUFFIXES:

ifeq ($(strip $(DEVKITARM)),)
$(error Run this from devkitPro MSYS or set DEVKITARM.)
endif

include $(DEVKITARM)/3ds_rules

MAKEROM ?= makerom
BANNERTOOL ?= bannertool

BUILD := build
OUT := ../resources/shortcut.cia
ARCH := -march=armv6k -mtune=mpcore -mfloat-abi=hard -mtp=soft
CFLAGS := -g -Wall -Wextra -Werror -O2 -mword-relocations -ffunction-sections $(ARCH) -I$(CTRULIB)/include -D__3DS__
LDFLAGS := -specs=3dsx.specs -g $(ARCH)

.PHONY: all clean
all: $(OUT)

$(BUILD):
	@mkdir -p $@

$(BUILD)/main.o: source/main.c | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/shortcut.elf: $(BUILD)/main.o
	$(CC) $(LDFLAGS) $^ -L$(CTRULIB)/lib -lctru -o $@

# The banner's picture and the icon are placeholders: Kasumi draws the
# game's own. The banner sound is the short koto from the menus (audio/sfx_open.opus).
$(OUT): $(BUILD)/shortcut.elf shortcut.rsf
	$(BANNERTOOL) makebanner -i ../resources/banner.png -a banner.wav -o $(BUILD)/banner.bnr
	$(BANNERTOOL) makesmdh -s "Kasumi shortcut" -l "Kasumi game shortcut" -p "Kasumi" -i ../resources/icon.png -f "visible,nosavebackups,new3ds" -o $(BUILD)/icon.icn
	$(MAKEROM) -f cia -o $@ -target t -elf $(BUILD)/shortcut.elf -rsf shortcut.rsf -banner $(BUILD)/banner.bnr -icon $(BUILD)/icon.icn

clean:
	@rm -rf $(BUILD)
