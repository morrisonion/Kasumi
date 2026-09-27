#include "regions.h"

#include <3ds.h>
#include <errno.h>
#include <fcntl.h>
#include <jansson.h>
#include <netdb.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include "app_paths.h"
#include "diagnostic.h"
#include "http_client.h"

#define REGIONS_PATH APP_DATA_DIR "/regions.json"
/* Servers don't move; a network's measurement stays good for a week. */
#define REGIONS_MAX_AGE (7 * 24 * 3600)

static LightLock g_lock = 1;
static Region g_regions[REGION_MAX];
static unsigned g_count;
static char g_measured_ssid[40];
static int64_t g_measured_at;
static char g_choice[40];

static void current_ssid(char *out, size_t size)
{
    char ssid[64];
    memset(ssid, 0, sizeof(ssid));
    if (R_FAILED(ACU_GetSSID(ssid))) ssid[0] = '\0';
    ssid[32] = '\0';
    snprintf(out, size, "%s", ssid);
}

static void save(void)
{
    json_t *list = json_array();
    LightLock_Lock(&g_lock);
    for (unsigned i = 0; i < g_count; ++i)
        json_array_append_new(list, json_pack("{s:s,s:s,s:i}", "name", g_regions[i].name,
                                              "url", g_regions[i].url, "ms", g_regions[i].ms));
    json_t *root = json_pack("{s:o,s:s,s:I}", "regions", list, "ssid", g_measured_ssid,
                             "measured_at", (json_int_t)g_measured_at);
    LightLock_Unlock(&g_lock);
    if (root) json_dump_file(root, REGIONS_PATH, JSON_INDENT(1));
    json_decref(root);
}

void regions_load(void)
{
    LightLock_Init(&g_lock);
    json_error_t error;
    json_t *root = json_load_file(REGIONS_PATH, 0, &error);
    json_t *list = json_is_object(root) ? json_object_get(root, "regions") : NULL;
    size_t index;
    json_t *item;
    g_count = 0;
    json_array_foreach(list, index, item) {
        if (g_count >= REGION_MAX) break;
        const char *name = json_string_value(json_object_get(item, "name"));
        const char *url = json_string_value(json_object_get(item, "url"));
        json_t *ms = json_object_get(item, "ms");
        if (!name || !url || strncmp(url, "https://", 8)) continue;
        Region *r = &g_regions[g_count++];
        snprintf(r->name, sizeof(r->name), "%s", name);
        snprintf(r->url, sizeof(r->url), "%s", url);
        r->ms = json_is_integer(ms) ? (int)json_integer_value(ms) : -1;
    }
    const char *ssid = json_is_object(root) ? json_string_value(json_object_get(root, "ssid")) : NULL;
    snprintf(g_measured_ssid, sizeof(g_measured_ssid), "%s", ssid ? ssid : "");
    json_t *at = json_is_object(root) ? json_object_get(root, "measured_at") : NULL;
    g_measured_at = json_is_integer(at) ? (int64_t)json_integer_value(at) : 0;
    json_decref(root);
}

/* The list is in serverInfo's metaData: each region's name maps to its own
 * session service URL (besides "local-region" and "gfn-regions"). */
bool regions_update(void)
{
    static const char *const headers[] = { "Accept: application/json" };
    HttpResponse response;
    if (!http_request("GET", REGION_NVIDIA_URL "/v2/serverInfo", "Kasumi-3DS", headers, 1, NULL,
                      256 * 1024, &response)) {
        diagnostic_log("REGION", "list failed: %s", response.error);
        return false;
    }
    json_error_t error;
    json_t *root = response.status == 200 ? json_loadb(response.body ? response.body : "", response.size, 0, &error) : NULL;
    http_response_free(&response);
    json_t *meta = json_is_object(root) ? json_object_get(root, "metaData") : NULL;
    Region fresh[REGION_MAX];
    unsigned count = 0;
    size_t index;
    json_t *item;
    json_array_foreach(meta, index, item) {
        const char *key = json_string_value(json_object_get(item, "key"));
        const char *value = json_string_value(json_object_get(item, "value"));
        if (!key || !value || strncmp(value, "https://", 8) || !strstr(value, ".nvidiagrid.net") ||
            count >= REGION_MAX)
            continue;
        snprintf(fresh[count].name, sizeof(fresh[count].name), "%s", key);
        snprintf(fresh[count].url, sizeof(fresh[count].url), "%s", value);
        fresh[count].ms = -1;
        ++count;
    }
    json_decref(root);
    if (!count) {
        diagnostic_log("REGION", "list empty");
        return false;
    }
    LightLock_Lock(&g_lock);
    /* Keep earlier measurements for regions that are still listed. */
    for (unsigned i = 0; i < count; ++i)
        for (unsigned j = 0; j < g_count; ++j)
            if (!strcmp(fresh[i].url, g_regions[j].url)) fresh[i].ms = g_regions[j].ms;
    memcpy(g_regions, fresh, sizeof(Region) * count);
    g_count = count;
    LightLock_Unlock(&g_lock);
    diagnostic_log("REGION", "list %u regions", count);
    save();
    return true;
}

/* TCP connect time to the region's HTTPS port: one round trip, without the
 * TLS handshake the 3DS would add. -1 if unreachable within the timeout. */
static int connect_ms(const char *url, int timeout_ms)
{
    char host[96];
    const char *start = url + 8;
    size_t n = strcspn(start, "/:");
    if (n == 0 || n >= sizeof(host)) return -1;
    memcpy(host, start, n);
    host[n] = '\0';
    struct addrinfo hints, *result = NULL;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(host, "443", &hints, &result) != 0 || !result) return -1;
    const int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        freeaddrinfo(result);
        return -1;
    }
    const int flags = fcntl(fd, F_GETFL, 0);
    if (flags >= 0) fcntl(fd, F_SETFL, flags | O_NONBLOCK);
    const u64 began = osGetTime();
    int ms = -1;
    if (connect(fd, result->ai_addr, result->ai_addrlen) == 0) {
        ms = (int)(osGetTime() - began);
    } else if (errno == EINPROGRESS) {
        struct pollfd p = { .fd = fd, .events = POLLOUT };
        if (poll(&p, 1, timeout_ms) == 1 && (p.revents & POLLOUT) && !(p.revents & (POLLERR | POLLHUP)))
            ms = (int)(osGetTime() - began);
    }
    freeaddrinfo(result);
    close(fd);
    return ms;
}

void regions_measure(void)
{
    Region list[REGION_MAX];
    LightLock_Lock(&g_lock);
    const unsigned count = g_count;
    memcpy(list, g_regions, sizeof(Region) * count);
    LightLock_Unlock(&g_lock);
    if (!count) return;
    /* One connect each, then two more for the closest few: far regions
     * only need to be known as far. */
    for (unsigned i = 0; i < count; ++i) list[i].ms = connect_ms(list[i].url, 900);
    for (unsigned round = 0; round < 2; ++round) {
        for (unsigned i = 0; i < count; ++i) {
            if (list[i].ms < 0 || list[i].ms > 200) continue;
            const int again = connect_ms(list[i].url, 900);
            if (again >= 0 && again < list[i].ms) list[i].ms = again;
        }
    }
    int best = -1;
    for (unsigned i = 0; i < count; ++i)
        if (list[i].ms >= 0 && (best < 0 || list[i].ms < list[best].ms)) best = (int)i;
    LightLock_Lock(&g_lock);
    for (unsigned i = 0; i < count && i < g_count; ++i)
        if (!strcmp(g_regions[i].url, list[i].url)) g_regions[i].ms = list[i].ms;
    current_ssid(g_measured_ssid, sizeof(g_measured_ssid));
    g_measured_at = (int64_t)time(NULL);
    LightLock_Unlock(&g_lock);
    if (best >= 0)
        diagnostic_log("REGION", "measured %u regions: fastest %s %d ms", count, list[best].name, list[best].ms);
    else
        diagnostic_log("REGION", "measured %u regions: none reachable", count);
    save();
}

unsigned regions_count(void)
{
    LightLock_Lock(&g_lock);
    const unsigned count = g_count;
    LightLock_Unlock(&g_lock);
    return count;
}

bool regions_get(unsigned index, Region *out)
{
    LightLock_Lock(&g_lock);
    const bool ok = index < g_count;
    if (ok) *out = g_regions[index];
    LightLock_Unlock(&g_lock);
    return ok;
}

int regions_fastest(void)
{
    int best = -1;
    LightLock_Lock(&g_lock);
    for (unsigned i = 0; i < g_count; ++i)
        if (g_regions[i].ms >= 0 && (best < 0 || g_regions[i].ms < g_regions[best].ms)) best = (int)i;
    LightLock_Unlock(&g_lock);
    return best;
}

bool regions_measured_here(void)
{
    char ssid[40];
    current_ssid(ssid, sizeof(ssid));
    LightLock_Lock(&g_lock);
    const int64_t age = (int64_t)time(NULL) - g_measured_at;
    const bool here = g_measured_at && age >= 0 && age < REGIONS_MAX_AGE && !strcmp(ssid, g_measured_ssid);
    LightLock_Unlock(&g_lock);
    return here;
}

void regions_set_choice(const char *choice)
{
    LightLock_Lock(&g_lock);
    snprintf(g_choice, sizeof(g_choice), "%s", choice ? choice : "");
    LightLock_Unlock(&g_lock);
}

void regions_resolve(char *url, size_t size)
{
    char choice[40];
    LightLock_Lock(&g_lock);
    snprintf(choice, sizeof(choice), "%s", g_choice);
    LightLock_Unlock(&g_lock);
    snprintf(url, size, "%s", REGION_NVIDIA_URL);
    if (!strcmp(choice, REGION_CHOICE_NVIDIA)) {
        diagnostic_log("REGION", "server=NVIDIA default");
        return;
    }
    if (choice[0]) {
        LightLock_Lock(&g_lock);
        bool found = false;
        for (unsigned i = 0; i < g_count && !found; ++i) {
            if (strcmp(g_regions[i].name, choice)) continue;
            snprintf(url, size, "%s", g_regions[i].url);
            found = true;
        }
        LightLock_Unlock(&g_lock);
        diagnostic_log("REGION", "server=%s%s", choice, found ? "" : " (not listed; NVIDIA default)");
        return;
    }
    /* Auto: the region with the lowest ping from this network. Measuring
     * matters most on mobile data, whose address can make NVIDIA pick a
     * far-away region. */
    if (!regions_count()) regions_update();
    if (!regions_measured_here()) regions_measure();
    const int best = regions_fastest();
    Region region;
    if (best >= 0 && regions_get((unsigned)best, &region)) {
        snprintf(url, size, "%s", region.url);
        diagnostic_log("REGION", "server=auto %s %d ms", region.name, region.ms);
    } else {
        diagnostic_log("REGION", "server=auto: no measurement; NVIDIA default");
    }
}
