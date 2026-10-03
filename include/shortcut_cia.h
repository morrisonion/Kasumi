#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* HOME Menu shortcuts are copies of one template app (shortcut/, built into
 * resources/shortcut.cia and linked into Kasumi). Each copy gets its own
 * title ID, icon and names (SMDH) and banner picture; everything else,
 * including the code that jumps into Kasumi, stays the same.
 *
 * Checked against a Python model of the same steps (every hash in the
 * ticket, TMD, NCCH and ExeFS verified) before it ran on a console. */

#define SHORTCUT_SMDH_SIZE 0x36C0
/* The banner's picture: 256x128, RGBA4444 in the GPU's 8x8 tiled order,
 * top row first (bannertool's model; see shortcut_cia.c). */
#define SHORTCUT_BANNER_WIDTH 256
#define SHORTCUT_BANNER_HEIGHT 128

/* The template's SMDH, to start a shortcut's from. False if the embedded
 * template is missing or damaged. */
bool shortcut_cia_template_smdh(uint8_t smdh[SHORTCUT_SMDH_SIZE]);

/* A complete CIA for `title_id` (malloc'd; *size set), or NULL with the
 * reason in `error`. */
uint8_t *shortcut_cia_build(uint64_t title_id, const uint8_t smdh[SHORTCUT_SMDH_SIZE],
                            const uint16_t *banner_texture, size_t *size, char *error, size_t error_size);
