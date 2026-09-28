#pragma once

#include <stdarg.h>

#include "app_paths.h"

#define DIAGNOSTIC_PATH APP_DATA_DIR "/kasumi-diagnostic.txt"
/* The run before this one: after a crash, its log is the useful one. */
#define DIAGNOSTIC_PREVIOUS_PATH APP_DATA_DIR "/kasumi-diagnostic-previous.txt"

void diagnostic_init(void);
void diagnostic_close(void);
void diagnostic_checkpoint(void);
void diagnostic_log(const char *component, const char *format, ...);
void diagnostic_vlog(const char *component, const char *format, va_list args);
