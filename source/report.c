#include "report.h"

#include <3ds.h>
#include <dirent.h>
#include <jansson.h>
#include <mbedtls/base64.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <zlib.h>

#include "app_paths.h"
#include "diagnostic.h"
#include "http_client.h"

/* Each log is capped (its end is kept): 6000 lines is well under this. */
#define LOG_CAP (768 * 1024)
#define DUMP_DIR "sdmc:/luma/dumps/arm11"
#define DUMP_MAX_AGE (3 * 24 * 3600)
#define DUMP_CAP (64 * 1024)

static char g_code[16];
static char g_error[96];

const char *report_code(void) { return g_code; }
const char *report_error(void) { return g_error; }

bool report_available(void) { return strstr(REPORT_URL, "CHANGE-ME") == NULL; }

/* The whole file, or its last `cap` bytes. NULL if missing. */
static char *read_file(const char *path, size_t cap, size_t *length)
{
    *length = 0;
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    const long size = ftell(f);
    if (size <= 0) {
        fclose(f);
        return NULL;
    }
    size_t want = (size_t)size;
    if (want > cap) {
        fseek(f, size - (long)cap, SEEK_SET);
        want = cap;
    } else {
        fseek(f, 0, SEEK_SET);
    }
    char *data = malloc(want + 1);
    if (data) {
        *length = fread(data, 1, want, f);
        data[*length] = '\0';
    }
    fclose(f);
    return data;
}

static bool private_address(int a, int b)
{
    return a == 0 || a == 10 || a == 127 || (a == 192 && b == 168) ||
           (a == 172 && b >= 16 && b <= 31) || (a == 169 && b == 254) || (a == 100 && b >= 64 && b <= 127);
}

static bool is_digit(char c) { return c >= '0' && c <= '9'; }

/* Public IPv4 addresses keep only their first two numbers ("151.62.x.x"):
 * enough to tell networks apart, not to identify anyone. Never longer than
 * the input. */
static char *scrub(const char *in, size_t length)
{
    char *out = malloc(length + 1);
    if (!out) return NULL;
    size_t o = 0, i = 0;
    while (i < length) {
        if (is_digit(in[i]) && (i == 0 || (!is_digit(in[i - 1]) && in[i - 1] != '.'))) {
            int parts[4];
            size_t j = i;
            int k = 0;
            for (; k < 4; ++k) {
                int value = 0, digits = 0;
                while (j < length && is_digit(in[j]) && digits < 4) value = value * 10 + (in[j++] - '0'), ++digits;
                if (!digits || digits > 3 || value > 255) break;
                parts[k] = value;
                if (k < 3) {
                    if (j >= length || in[j] != '.') break;
                    ++j;
                }
            }
            const bool ends = j >= length || (!is_digit(in[j]) && !(in[j] == '.' && j + 1 < length && is_digit(in[j + 1])));
            if (k == 4 && ends && !private_address(parts[0], parts[1])) {
                o += (size_t)sprintf(out + o, "%d.%d.x.x", parts[0], parts[1]);
                i = j;
                continue;
            }
        }
        out[o++] = in[i++];
    }
    out[o] = '\0';
    return out;
}

static json_t *scrubbed_file(const char *path)
{
    size_t length = 0;
    char *raw = read_file(path, LOG_CAP, &length);
    if (!raw) return json_string("");
    char *clean = scrub(raw, length);
    free(raw);
    json_t *value = json_stringn(clean ? clean : "", clean ? strlen(clean) : 0);
    free(clean);
    return value ? value : json_string("");
}

static char *base64(const unsigned char *data, size_t length)
{
    size_t needed = 0;
    mbedtls_base64_encode(NULL, 0, &needed, data, length);
    char *out = malloc(needed + 1);
    if (!out) return NULL;
    size_t written = 0;
    if (mbedtls_base64_encode((unsigned char *)out, needed + 1, &written, data, length) != 0) {
        free(out);
        return NULL;
    }
    out[written] = '\0';
    return out;
}

/* The newest Luma ARM11 crash dump from the last few days, if any. */
static json_t *recent_dump(void)
{
    DIR *dir = opendir(DUMP_DIR);
    if (!dir) return NULL;
    char best[64] = "";
    time_t best_time = 0;
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        /* Luma names them crash_dump_00000033.dmp; skip anything else. */
        if (strncmp(entry->d_name, "crash_dump_", 11) || strlen(entry->d_name) >= sizeof(best)) continue;
        char path[160];
        snprintf(path, sizeof(path), "%s/%.63s", DUMP_DIR, entry->d_name);
        struct stat st;
        if (stat(path, &st) || st.st_size <= 0 || st.st_size > DUMP_CAP) continue;
        if (!best[0] || st.st_mtime > best_time || (st.st_mtime == best_time && strcmp(entry->d_name, best) > 0)) {
            snprintf(best, sizeof(best), "%.63s", entry->d_name);
            best_time = st.st_mtime;
        }
    }
    closedir(dir);
    if (!best[0]) return NULL;
    const time_t now = time(NULL);
    if (best_time && now - best_time > DUMP_MAX_AGE) return NULL;
    char path[160];
    snprintf(path, sizeof(path), "%s/%s", DUMP_DIR, best);
    size_t length = 0;
    char *data = read_file(path, DUMP_CAP, &length);
    if (!data) return NULL;
    char *encoded = base64((const unsigned char *)data, length);
    free(data);
    if (!encoded) return NULL;
    json_t *dump = json_pack("{s:s,s:s}", "name", best, "data", encoded);
    free(encoded);
    return dump;
}

/* gzip, so the service can unpack it with standard tools. */
static unsigned char *gzip(const char *data, size_t length, size_t *out_length)
{
    z_stream z;
    memset(&z, 0, sizeof(z));
    if (deflateInit2(&z, 6, Z_DEFLATED, 15 + 16, 8, Z_DEFAULT_STRATEGY) != Z_OK) return NULL;
    const uLong bound = deflateBound(&z, (uLong)length);
    unsigned char *out = malloc(bound);
    if (!out) {
        deflateEnd(&z);
        return NULL;
    }
    z.next_in = (Bytef *)data;
    z.avail_in = (uInt)length;
    z.next_out = out;
    z.avail_out = (uInt)bound;
    const int result = deflate(&z, Z_FINISH);
    *out_length = z.total_out;
    deflateEnd(&z);
    if (result != Z_STREAM_END) {
        free(out);
        return NULL;
    }
    return out;
}

static bool fail(const char *message)
{
    snprintf(g_error, sizeof(g_error), "%s", message);
    diagnostic_log("REPORT", "not sent: %s", message);
    return false;
}

bool report_previous_run_unclean(void)
{
    size_t length = 0;
    char *head = read_file(DIAGNOSTIC_PREVIOUS_PATH, 1u << 30, &length);
    if (!head) return false;
    /* Only a run of this very version: older ones never wrote the marker. */
    const bool same_version = strstr(head, APP_NAME " " APP_VERSION " (build " APP_BUILD ")") == head;
    const char *tail = length > 4096 ? head + length - 4096 : head;
    const bool clean = strstr(tail, REPORT_CLEAN_EXIT) != NULL;
    /* A few lines only: it barely started (e.g. exited from a fatal screen). */
    unsigned lines = 0;
    for (size_t i = 0; i < length && lines < 8; ++i) lines += head[i] == '\n';
    free(head);
    return same_version && !clean && lines >= 8;
}

bool report_send(const char *trigger)
{
    g_code[0] = g_error[0] = '\0';
    if (!trigger || !trigger[0]) trigger = "manual";
    if (!report_available()) return fail("Reports are not set up in this build");
    diagnostic_log("REPORT", "sending (%s)", trigger);
    diagnostic_checkpoint();

    char sent_at[32];
    const time_t now = time(NULL);
    strftime(sent_at, sizeof(sent_at), "%Y-%m-%dT%H:%M:%S", gmtime(&now));
    json_t *root = json_pack("{s:s,s:s,s:s,s:s,s:s}", "app", APP_NAME, "version", APP_VERSION,
                             "build", APP_BUILD, "sent_at", sent_at, "trigger", trigger);
    if (!root) return fail("Out of memory");
    json_object_set_new(root, "log", scrubbed_file(DIAGNOSTIC_PATH));
    json_object_set_new(root, "previous_log", scrubbed_file(DIAGNOSTIC_PREVIOUS_PATH));
    json_t *settings = scrubbed_file(APP_DATA_DIR "/settings.json");
    json_error_t parse_error;
    json_t *parsed = json_loads(json_string_value(settings), 0, &parse_error);
    const char *install = json_is_object(parsed) ? json_string_value(json_object_get(parsed, "install_id")) : NULL;
    json_object_set_new(root, "install", json_string(install ? install : ""));
    json_decref(parsed);
    json_object_set_new(root, "settings", settings);
    json_t *dump = recent_dump();
    if (dump) json_object_set_new(root, "dump", dump);
    char *report = json_dumps(root, JSON_COMPACT);
    json_decref(root);
    if (!report) return fail("Out of memory");

    size_t packed_length = 0;
    unsigned char *packed = gzip(report, strlen(report), &packed_length);
    const size_t report_length = strlen(report);
    free(report);
    if (!packed) return fail("Could not compress the report");
    char *payload = base64(packed, packed_length);
    free(packed);
    if (!payload) return fail("Out of memory");
    json_t *upload = json_pack("{s:s,s:s}", "format", "kasumi-report-1", "payload", payload);
    free(payload);
    char *body = upload ? json_dumps(upload, JSON_COMPACT) : NULL;
    json_decref(upload);
    if (!body) return fail("Out of memory");

    static const char *const headers[] = { "Content-Type: application/json", "Accept: application/json" };
    HttpResponse response;
    http_next_request(30, NULL, NULL);
    const bool sent = http_request("POST", REPORT_URL, "Kasumi-3DS", headers, 2, body, 16 * 1024, &response);
    free(body);
    if (!sent) {
        char message[96];
        snprintf(message, sizeof(message), "No connection: %.70s", response.error);
        return fail(message);
    }
    const long status = response.status;
    json_error_t error;
    json_t *reply = json_loadb(response.body ? response.body : "", response.size, 0, &error);
    http_response_free(&response);
    const char *code = json_is_object(reply) ? json_string_value(json_object_get(reply, "code")) : NULL;
    if (status == 200 && code && strlen(code) == 6) {
        snprintf(g_code, sizeof(g_code), "%.3s-%.3s", code, code + 3);
        json_decref(reply);
        diagnostic_log("REPORT", "sent code=%s bytes=%lu packed=%lu", g_code,
                       (unsigned long)report_length, (unsigned long)packed_length);
        return true;
    }
    json_decref(reply);
    if (status == 429) return fail("Too many reports from this network: try again in an hour");
    char message[64];
    snprintf(message, sizeof(message), "The report service answered HTTP %ld", status);
    return fail(message);
}
