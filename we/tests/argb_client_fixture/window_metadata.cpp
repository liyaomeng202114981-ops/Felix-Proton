/* SPDX-License-Identifier: BSD-3-Clause; Copyright 2026 Felix Li */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string>
static FILE *out;
static std::wstring wanted;
static int count;
static bool same_file(const wchar_t *a,const wchar_t *b) {
  HANDLE x=CreateFileW(a,FILE_READ_ATTRIBUTES,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,0,OPEN_EXISTING,0,0);
  HANDLE y=CreateFileW(b,FILE_READ_ATTRIBUTES,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,0,OPEN_EXISTING,0,0);
  BY_HANDLE_FILE_INFORMATION u={},v={};bool ok=x!=INVALID_HANDLE_VALUE&&y!=INVALID_HANDLE_VALUE&&GetFileInformationByHandle(x,&u)&&GetFileInformationByHandle(y,&v)&&u.dwVolumeSerialNumber==v.dwVolumeSerialNumber&&u.nFileIndexHigh==v.nFileIndexHigh&&u.nFileIndexLow==v.nFileIndexLow;
  if(x!=INVALID_HANDLE_VALUE)CloseHandle(x);if(y!=INVALID_HANDLE_VALUE)CloseHandle(y);return ok;
}
static std::string json(const wchar_t *text) {
  int n=WideCharToMultiByte(CP_UTF8,0,text,-1,0,0,0,0);
  std::string s(n,0),r="\"";WideCharToMultiByte(CP_UTF8,0,text,-1,s.data(),n,0,0);
  for(int i=0;i<n-1;i++){unsigned char c=s[i];if(c=='"'||c=='\\')r+='\\';if(c<32){char b[8];sprintf(b,"\\u%04x",c);r+=b;}else r+=(char)c;}return r+"\"";
}
static BOOL CALLBACK inspect(HWND h,LPARAM) {
  DWORD pid;GetWindowThreadProcessId(h,&pid);HANDLE p=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);if(!p)return TRUE;
  wchar_t exe[32768];DWORD size=32768;BOOL ok=QueryFullProcessImageNameW(p,0,exe,&size);CloseHandle(p);
  if(!ok||(!same_file(exe,wanted.c_str())))return TRUE;
  wchar_t cls[256],title[512];GetClassNameW(h,cls,256);GetWindowTextW(h,title,512);RECT r,c;GetWindowRect(h,&r);GetClientRect(h,&c);
  COLORREF key=0;BYTE alpha=0;DWORD flags=0;BOOL layered=GetLayeredWindowAttributes(h,&key,&alpha,&flags);
  if(count++)fputs(",\n",out);
  fprintf(out,"{\"hwnd\":%llu,\"xid\":%llu,\"pid\":%lu,\"class\":%s,\"title\":%s,\"visible\":%s,\"style\":%lu,\"exstyle\":%lu,\"rect\":[%ld,%ld,%ld,%ld],\"client\":[%ld,%ld],\"owner\":%llu,\"parent\":%llu,\"dwm_custom_frame\":%llu,\"wine_frameless\":%llu,\"layered_attributes_ok\":%s,\"layered_flags\":%lu,\"constant_alpha\":%u,\"color_key\":%lu}",
    (unsigned long long)(ULONG_PTR)h,(unsigned long long)(ULONG_PTR)GetPropW(h,L"__wine_x11_whole_window"),pid,json(cls).c_str(),json(title).c_str(),IsWindowVisible(h)?"true":"false",(DWORD)GetWindowLongPtrW(h,GWL_STYLE),(DWORD)GetWindowLongPtrW(h,GWL_EXSTYLE),r.left,r.top,r.right,r.bottom,c.right,c.bottom,(unsigned long long)(ULONG_PTR)GetWindow(h,GW_OWNER),(unsigned long long)(ULONG_PTR)GetParent(h),(unsigned long long)(ULONG_PTR)GetPropW(h,L"__wine_dwm_custom_frame"),(unsigned long long)(ULONG_PTR)GetPropW(h,L"__wine_win32u_frameless"),layered?"true":"false",flags,(unsigned)alpha,key);
  return TRUE;
}
int wmain(int argc,wchar_t **argv) {
  if(argc!=3)return 2;wanted=argv[1];out=_wfopen(argv[2],L"wb");if(!out)return 3;
  fputs("{\"windows\":[\n",out);EnumWindows(inspect,0);fprintf(out,"\n],\"count\":%d,\"scope\":\"documented read-only APIs, exact process-image filter; no injection or pixel changes\"}\n",count);fclose(out);return count?0:4;
}
