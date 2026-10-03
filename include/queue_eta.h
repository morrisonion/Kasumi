#pragma once

#include <stdbool.h>

/* How long a queue will take. The report service fits every player's
 * finished queues per provider as base + perPlace * starting place (GET
 * /eta); Kasumi keeps the last answer on the SD card and, for a provider it
 * has no fit for, learns from this console's own queues. Beta.29 data:
 * NVIDIA's queue took ~133 s whatever the starting place, so the old
 * seconds-per-place guess was off by 72 s typically, the fit by 5 s. */

/* Startup: the saved model and this console's own averages. */
void queue_eta_load(void);
/* Worker thread: fetch the shared model (quietly does nothing offline). */
void queue_eta_fetch(void);
/* Expected total queue seconds for a queue that started at `place` with
 * `provider` (a provider code, "NVIDIA"); false if there is nothing to go on. */
bool queue_eta_expected(const char *provider, int place, float *seconds);
/* A queue finished: learn from it (this console's fallback). */
void queue_eta_learn(const char *provider, int place, float seconds);
