#pragma once

#include <stdbool.h>

#include "app_paths.h"
#include "gfn_input.h"
#include "stream_profile.h"

#define SETTINGS_PATH APP_DATA_DIR "/settings.json"

typedef enum {
    DEADZONE_SMALL,
    DEADZONE_MEDIUM,
    DEADZONE_LARGE,
    DEADZONE_COUNT
} DeadzoneLevel;

enum { LID_PAUSE, LID_SLEEP, LID_KEEP_PLAYING, LID_MODE_COUNT };
/* Automatic diagnostic reports: not asked yet, yes, or no. */
enum { SHARE_ASK, SHARE_YES, SHARE_NO };
/* Bumped when what is shared changes, so everyone is asked again:
 * 2 = problem reports + session performance stats (beta.16). */
#define SHARE_CONSENT_VERSION 2

typedef struct {
    GfnButtonLayout button_layout;
    DeadzoneLevel deadzone;
    bool swap_shoulders;
    /* Start Genshin Impact sessions in pointer mode for its PC login screen. */
    bool auto_pointer;
    bool show_stats;
    /* Experimental: gamepad state on an unordered, partially reliable
     * channel. Lower latency on lossy Wi-Fi, but unverified with NVIDIA's
     * WebRTC streamer, so it is off by default. */
    bool fast_input;
    /* Picture, applied at the next launch. */
    bool wide_video;
    StreamBitrateMode bitrate_mode;
    /* NVIDIA encoder options, applied at the next launch. */
    bool sharpen;
    GfnGyroMode gyro_mode;
    unsigned gyro_speed;
    /* Appearance and audio. */
    unsigned theme;
    /* Stream volume in steps of 20 %: 0 = mute ... 5 = 100 %. */
    unsigned volume;
    bool mute_in_menus;
    /* Closing the lid mid-game (LID_*): pause with the connection kept,
     * sleep and reconnect on opening, or keep playing with the screens off. */
    unsigned lid_mode;
    /* Weak Wi-Fi or a phone hotspot: lower bitrate, bigger buffers. */
    bool net_weak;
    /* GeForce NOW server: "" auto (lowest ping), "nvidia", or a region name. */
    char server[40];
    /* GeForce NOW provider for the next sign-in: "" = NVIDIA's pick for this
     * country, or a provider code (provider.h). */
    char provider[12];
    /* Send a report automatically when something goes wrong (SHARE_*). */
    unsigned share_reports;
    /* Anonymous performance summary after each session. */
    bool share_stats;
    /* The SHARE_CONSENT_VERSION last answered (0 = never asked). */
    unsigned share_consent;
    /* Random, made on this console: tells reports from one console apart.
     * Not linked to the NVIDIA account. */
    char install_id[20];
    /* The first-run guide was finished or skipped. */
    bool guide_done;
    /* Look for updates once or twice a day; include pre-releases (beta). */
    bool auto_update;
    bool update_beta;
} AppSettings;

void settings_defaults(AppSettings *settings);
bool settings_load(AppSettings *settings);
bool settings_save(const AppSettings *settings);
/* Push controller-related settings into the input encoder. */
void settings_apply_input(const AppSettings *settings);
/* Push the picture settings into the stream profile. */
void settings_apply_picture(const AppSettings *settings);
unsigned settings_deadzone_percent(DeadzoneLevel level);
