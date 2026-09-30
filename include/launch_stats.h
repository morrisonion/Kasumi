#pragma once

#include <stdbool.h>

#include "app_paths.h"
#include "gfn_client.h"

/* One anonymous record per launch attempt (Share performance stats): how it
 * ended ("ok", "limit", "abandoned", "cancel"...), time in queue, time to
 * the first frame. Beta.18's stats only covered sessions that streamed, so
 * the consoles that never got a game in were invisible on the dashboard.
 * Records wait on the SD card and go out with the session summary. */

#define LAUNCH_PENDING_PATH APP_DATA_DIR "/launches-pending.json"

void launch_begin(bool resumed, bool weak, bool auto_weak);
/* Every frame while launching: queue place and time, rig ready, ads. */
void launch_track(const GfnClient *client);
bool launch_active(void);
/* Finish the attempt. `install_id` NULL: counted locally, nothing written
 * (the player did not opt in). */
void launch_end(const char *outcome, const char *install_id);
