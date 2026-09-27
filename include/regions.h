#pragma once

#include <stdbool.h>
#include <stddef.h>

/* GeForce NOW server regions: the list NVIDIA publishes in serverInfo, a
 * TCP ping to each, and which one a new session goes to. */

#define REGION_MAX 32

/* The session service NVIDIA picks for you (by your internet address). */
#define REGION_NVIDIA_URL "https://prod.cloudmatchbeta.nvidiagrid.net"

/* Server setting values besides a region's name. */
#define REGION_CHOICE_AUTO ""
#define REGION_CHOICE_NVIDIA "nvidia"

typedef struct {
    char name[40];
    char url[96];
    int ms; /* measured round trip, -1 unknown or unreachable */
} Region;

/* The cached list and measurements from the SD card. */
void regions_load(void);

/* Worker thread only: fetch the list, and ping every region. */
bool regions_update(void);
void regions_measure(void);

unsigned regions_count(void);
bool regions_get(unsigned index, Region *out);
/* The lowest measured ping (-1 none), and whether that measurement was made
 * on the Wi-Fi network the console is on now. */
int regions_fastest(void);
bool regions_measured_here(void);

/* REGION_CHOICE_AUTO, REGION_CHOICE_NVIDIA or a region name. */
void regions_set_choice(const char *choice);

/* Worker thread only: the CloudMatch base URL for a new session. Auto pings
 * the regions first if they were not measured on this network. */
void regions_resolve(char *url, size_t size);
