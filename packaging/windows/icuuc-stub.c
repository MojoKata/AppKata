/* A stand-in for Windows' icuuc.dll, used only while building (scripts/build-windows.sh).
   Qt 6.10+ links its text codecs to the ICU in Windows itself (icuuc.dll); Wine has no ICU, so
   Qt6Core.dll won't load under Wine and PyInstaller's Qt hook silently collects no plugins or QML.
   The build puts this in Wine's system32 so Qt loads there. Nothing calls it, and the installer
   never carries it: the installed app uses Windows' own icuuc.dll. When a newer Qt imports more,
   the build stops (Qt won't load under Wine) and names the missing import: add it here. */
#define STUB(name) __declspec(dllexport) void *name(void) { return 0; }

STUB(ucnv_open)
STUB(ucnv_close)
STUB(ucnv_reset)
STUB(ucnv_getMaxCharSize)
STUB(ucnv_getName)
STUB(ucnv_getToUCallBack)
STUB(ucnv_getFromUCallBack)
STUB(ucnv_setToUCallBack)
STUB(ucnv_setFromUCallBack)
STUB(ucnv_cbToUWriteUChars)
STUB(ucnv_toUnicode)
STUB(ucnv_cbFromUWriteUChars)
STUB(ucnv_toUCountPending)
STUB(ucnv_fromUCountPending)
STUB(ucnv_getStandardName)
STUB(ucnv_getAvailableName)
STUB(ucnv_countAvailable)
STUB(ucnv_fromUnicode)
