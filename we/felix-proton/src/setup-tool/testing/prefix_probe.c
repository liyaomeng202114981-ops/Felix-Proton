/* SPDX-License-Identifier: BSD-3-Clause
 * Self-contained Windows file/API startup probe. No account or game access. */
#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0600
#include <winsock2.h>
#include <windows.h>
#include <iphlpapi.h>
#include <stdio.h>
#include <stdlib.h>

int wmain(int argc, wchar_t **argv)
{
    FILE *out;
    OSVERSIONINFOW version = {sizeof(version)};
    ULONG size = 0;
    DWORD result;
    unsigned int adapters = 0;
    IP_ADAPTER_ADDRESSES *list, *row;
    if (argc != 2 || !(out = _wfopen(argv[1], L"wb"))) return 11;
    GetVersionExW(&version);
    result = GetAdaptersAddresses(AF_INET, 0, NULL, NULL, &size);
    list = malloc(size);
    if (!list) { fclose(out); return 12; }
    if (result == ERROR_BUFFER_OVERFLOW)
        result = GetAdaptersAddresses(AF_INET, 0, NULL, list, &size);
    if (!result) for (row = list; row; row = row->Next) adapters++;
    fprintf(out, "{\"process_id\":%lu,\"windows_major\":%lu,\"windows_build\":%lu,"
                 "\"pointer_bits\":%u,\"adapter_result\":%lu,\"adapter_count\":%u,"
                 "\"file_write\":true,\"account_or_game_access\":false}\n",
            GetCurrentProcessId(), version.dwMajorVersion, version.dwBuildNumber,
            (unsigned int)(8 * sizeof(void *)), result, adapters);
    free(list);
    if (fclose(out)) return 13;
    return result ? 14 : 0;
}
