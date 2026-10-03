#pragma once

#include <stdarg.h>
#include <stddef.h>

#include "app_paths.h"

#define DIAGNOSTIC_PATH APP_DATA_DIR "/kasumi-diagnostic.txt"
/* The run before this one: after a crash, its log is the useful one. */
#define DIAGNOSTIC_PREVIOUS_PATH APP_DATA_DIR "/kasumi-diagnostic-previous.txt"
/* This run's earlier lines, once the log rolled over (see diagnostic.c). */
#define DIAGNOSTIC_OLDER_PATH APP_DATA_DIR "/kasumi-diagnostic-older.txt"

void diagnostic_init(void);
void diagnostic_close(void);
void diagnostic_checkpoint(void);
void diagnostic_log(const char *component, const char *format, ...);
void diagnostic_vlog(const char *component, const char *format, va_list args);

/* Something that should not happen (an unmapped NVIDIA answer, a stuck
 * screen, a decoder error...). Logged as "[FLAG] code: ...", counted per run,
 * and each new code asks for an automatic report, so new bugs reach us even
 * when the player sees nothing wrong. Any thread. `code` is a short fixed
 * string ("video-freeze"); repeats of a code are logged sparingly. */
void diagnostic_flag(const char *code, const char *format, ...);
/* The next code flagged for the first time this run and not yet taken, or
 * NULL. Main thread: it turns them into automatic reports. */
const char *diagnostic_take_new_flag(void);
/* "video-freeze x2, unknown-reason x1", or "" when nothing was flagged. */
void diagnostic_flags_summary(char *out, size_t size);
