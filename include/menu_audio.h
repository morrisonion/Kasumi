#pragma once

#include <stdbool.h>

#include "app_paths.h"

/* Players' own songs (.mp3 or .opus). When any are here, they replace the
 * built-in tracks. */
#define MENU_MUSIC_DIR APP_DATA_DIR "/music"

typedef enum { MENU_MUSIC_ON, MENU_MUSIC_QUIET, MENU_MUSIC_OFF, MENU_MUSIC_MODE_COUNT } MenuMusicMode;

/* Where the player is: music plays in the menus, softer while a game is
 * being set up, and fades out once the game's own sound takes over. */
typedef enum { MENU_SCENE_MENUS, MENU_SCENE_WAITING, MENU_SCENE_GAME } MenuScene;

typedef enum { MENU_CUE_OKAERI, MENU_CUE_ITTERASSHAI } MenuCue;

/* After audio_system_init(); does nothing without the DSP. */
void menu_audio_start(void);
/* Every loop: what should be playing now. */
void menu_audio_set(MenuMusicMode mode, MenuScene scene);
/* A voice line; the music dips under it. */
void menu_audio_cue(MenuCue cue);
/* Fade out the current song and start another. */
void menu_audio_next(void);
/* Title of the song playing, or "" when none. */
const char *menu_audio_now_playing(void);
void menu_audio_exit(void);
