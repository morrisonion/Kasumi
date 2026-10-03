/* A Kasumi game shortcut on the HOME Menu.
 *
 * Kasumi installs one copy of this per game, each with its own title ID,
 * icon and banner (source/shortcut.c). Opened, it hands its own title ID to
 * Kasumi and jumps there; Kasumi looks the ID up in shortcuts.json and
 * launches that game. */

#include <3ds.h>
#include <stdio.h>
#include <string.h>

#define KASUMI_TITLE_ID 0x0004000004B53400ULL

/* Read by Kasumi (shortcut.c, ShortcutArg): keep the two in step. */
typedef struct {
    char magic[8];
    u64 shortcut_id;
    u32 version;
} ShortcutArg;

static bool kasumi_installed(void)
{
    /* Can't ask: try the jump anyway. */
    if (R_FAILED(amInit())) return true;
    u64 id = KASUMI_TITLE_ID;
    AM_TitleEntry entry;
    const bool found = R_SUCCEEDED(AM_GetTitleInfo(MEDIATYPE_SD, 1, &id, &entry));
    amExit();
    return found;
}

static void explain_missing(void)
{
    gfxInitDefault();
    consoleInit(GFX_TOP, NULL);
    printf("\n\n  Kasumi isn't installed.\n\n"
           "  This is a Kasumi game shortcut. Install\n"
           "  Kasumi (Kasumi.cia) and it will start\n"
           "  the game from here.\n\n"
           "  Press any button to go back.\n");
    while (aptMainLoop()) {
        hidScanInput();
        if (hidKeysDown()) break;
        gfxFlushBuffers();
        gfxSwapBuffers();
        gspWaitForVBlank();
    }
    gfxExit();
}

int main(void)
{
    if (!kasumi_installed()) {
        explain_missing();
        return 0;
    }
    ShortcutArg arg;
    memset(&arg, 0, sizeof(arg));
    memcpy(arg.magic, "KSHORTC1", 8);
    arg.version = 1;
    APT_GetProgramID(&arg.shortcut_id);
    /* Leaving main runs the chainloader: straight into Kasumi. */
    aptSetChainloader(KASUMI_TITLE_ID, MEDIATYPE_SD);
    aptSetChainloaderArgs(&arg, sizeof(arg), NULL);
    return 0;
}
