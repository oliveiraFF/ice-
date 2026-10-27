# -*- coding: utf-8 -*-
Unicode true
RequestExecutionLevel user
Name "ice运营台"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\ICEOps"
InstallDirRegKey HKCU "Software\ICEOps" "InstallDir"
SetCompressor /SOLID lzma
VIProductVersion "${APP_VERSION}"
VIAddVersionKey "ProductName" "ice运营台"
VIAddVersionKey "FileDescription" "ice运营台 Windows 安装程序"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "LegalCopyright" "ICE 运营台项目"

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!define MUI_ICON "${PROJECT_ICON}"
!define MUI_UNICON "${PROJECT_ICON}"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TEXT "安装 ice运营台 ${APP_VERSION}。$\r$\n$\r$\n默认只为当前 Windows 用户安装，无需管理员权限。安装包不含密钥、账号资料或测试记录。$\r$\n$\r$\n升级和卸载均保留 data、downloads 及其他用户自行创建的文件。"
!define MUI_FINISHPAGE_RUN "$INSTDIR\ice运营台.exe"
!define MUI_FINISHPAGE_RUN_TEXT "启动 ice运营台"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!define MUI_UNCONFIRMPAGE_TEXT_TOP "将移除程序和快捷方式，保留 data、downloads 及其他用户文件。请先退出软件。"
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

!macro EnsureClosed
  ${If} ${FileExists} "$INSTDIR\ice运营台.exe"
    System::Call 'kernel32::CreateFileW(w "$INSTDIR\ice运营台.exe", i 0x40000000, i 7, p 0, i 3, i 128, p 0) p.r0'
    ${If} $0 == -1
      IfSilent +2
      MessageBox MB_OK|MB_ICONEXCLAMATION "程序正在使用或目录不可写。请先退出这一目录中的 ice运营台，再重试；不会自动关闭程序。"
      SetErrorLevel 2
      Abort
    ${EndIf}
    System::Call 'kernel32::CloseHandle(p r0)'
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\data\desktop.lock"
    System::Call 'kernel32::CreateFileW(w "$INSTDIR\data\desktop.lock", i 0xC0000000, i 0, p 0, i 3, i 128, p 0) p.r0'
    ${If} $0 == -1
      IfSilent +2
      MessageBox MB_OK|MB_ICONEXCLAMATION "数据仍被使用或正在退出收尾。请等待软件完全退出后重试；不会修改用户数据。"
      SetErrorLevel 2
      Abort
    ${EndIf}
    System::Call 'kernel32::CloseHandle(p r0)'
  ${EndIf}
!macroend

Function .onInit
  SetShellVarContext current
  SetRegView 64
  ${IfNot} ${RunningX64}
  ${OrIfNot} ${AtLeastWin10}
    IfSilent +2
    MessageBox MB_OK|MB_ICONSTOP "此版本需要 Windows 10/11 64位系统。"
    SetErrorLevel 2
    Abort
  ${EndIf}
FunctionEnd

Section "程序文件（必选）" Core
  SectionIn RO
  !insertmacro EnsureClosed
  SetOverwrite on
  !include "${PAYLOAD_INCLUDE}\payload-install.nsh"
  SetOutPath "$INSTDIR"
  CreateDirectory "$INSTDIR\data"
  WriteUninstaller "$INSTDIR\UninstallICE.exe"
  CreateDirectory "$SMPROGRAMS\ice运营台"
  CreateShortcut "$SMPROGRAMS\ice运营台\ice运营台.lnk" "$INSTDIR\ice运营台.exe"
  CreateShortcut "$SMPROGRAMS\ice运营台\卸载 ice运营台.lnk" "$INSTDIR\UninstallICE.exe"
  WriteRegStr HKCU "Software\ICEOps" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ICEOps" "DisplayName" "ice运营台"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ICEOps" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ICEOps" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ICEOps" "DisplayIcon" "$INSTDIR\ice运营台.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ICEOps" "UninstallString" '$\"$INSTDIR\UninstallICE.exe$\"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ICEOps" "QuietUninstallString" '$\"$INSTDIR\UninstallICE.exe$\" /S'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ICEOps" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ICEOps" "NoRepair" 1
SectionEnd

Section "桌面快捷方式" DesktopLink
  CreateShortcut "$DESKTOP\ice运营台.lnk" "$INSTDIR\ice运营台.exe"
SectionEnd

Function un.onInit
  SetShellVarContext current
  SetRegView 64
  !insertmacro EnsureClosed
FunctionEnd

Section "Uninstall"
  !include "${PAYLOAD_INCLUDE}\payload-uninstall.nsh"
  Delete "$DESKTOP\ice运营台.lnk"
  Delete "$SMPROGRAMS\ice运营台\ice运营台.lnk"
  Delete "$SMPROGRAMS\ice运营台\卸载 ice运营台.lnk"
  RMDir "$SMPROGRAMS\ice运营台"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ICEOps"
  DeleteRegKey HKCU "Software\ICEOps"
  Delete "$INSTDIR\UninstallICE.exe"
  RMDir "$INSTDIR"
SectionEnd
