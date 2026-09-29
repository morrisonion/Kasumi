#pragma once

#include <stdarg.h>

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
