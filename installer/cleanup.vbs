Option Explicit

' 清理用户数据的主函数
Sub CleanupUserData()
    On Error Resume Next
    Dim fso, shell, appDataPath, tempPath, userProfile
    Set fso = CreateObject("Scripting.FileSystemObject")
    Set shell = CreateObject("WScript.Shell")
    ' 获取系统路径
    appDataPath = shell.ExpandEnvironmentStrings("%APPDATA%")
    tempPath = shell.ExpandEnvironmentStrings("%TMP%")
    userProfile = shell.ExpandEnvironmentStrings("%USERPROFILE%")
    Call DeleteFolderSafely(fso, appDataPath & "\Class Widgets")
    ' 清理安装目录中的所有内容
    Call CleanupInstallationFolder()
    Set fso = Nothing
    Set shell = Nothing
End Sub

' 清理安装文件夹内容
Sub CleanupInstallationFolder()
    On Error Resume Next

    Dim fso, shell, installPath
    Set fso = CreateObject("Scripting.FileSystemObject")
    Set shell = CreateObject("WScript.Shell")
    ' 获取安装路径
    installPath = shell.RegRead("HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\ClassWidgets\InstallLocation")
    If installPath = "" Then
        installPath = shell.ExpandEnvironmentStrings("%ProgramFiles%\Class Widgets")
    End If
    If Not fso.FolderExists(installPath) Then
        installPath = shell.ExpandEnvironmentStrings("%ProgramFiles(x86)%\Class Widgets")
    End If
    ' 清理安装目录中的所有文件和子文件夹
    If fso.FolderExists(installPath) Then
        Dim folder, file, subFolder
        Set folder = fso.GetFolder(installPath)
        For Each file In folder.Files
            file.Delete True
        Next
        For Each subFolder In folder.SubFolders
            Call DeleteFolderSafely(fso, subFolder.Path)
        Next
        Call DeleteFolderSafely(fso, installPath & "\log")
        Call DeleteFolderSafely(fso, installPath & "\config")
        Call DeleteFolderSafely(fso, installPath & "\cache")
        Call DeleteFolderSafely(fso, installPath & "\plugins")
    End If

    Set fso = Nothing
    Set shell = Nothing
End Sub

' 移除开机启动项
Sub RemoveStartupShortcut()
    On Error Resume Next
    Dim fso, shell, startupPath, shortcutPath
    Set fso = CreateObject("Scripting.FileSystemObject")
    Set shell = CreateObject("WScript.Shell")
    startupPath = shell.ExpandEnvironmentStrings("%APPDATA%") & "\Microsoft\Windows\Start Menu\Programs\Startup"
    shortcutPath = startupPath & "\Class Widgets.lnk"
    If fso.FileExists(shortcutPath) Then
        fso.DeleteFile shortcutPath, True
    End If
    startupPath = shell.ExpandEnvironmentStrings("%ALLUSERSPROFILE%") & "\Microsoft\Windows\Start Menu\Programs\Startup"
    shortcutPath = startupPath & "\Class Widgets.lnk"
    If fso.FileExists(shortcutPath) Then
        fso.DeleteFile shortcutPath, True
    End If
    Set fso = Nothing
    Set shell = Nothing
End Sub

Sub DeleteFolderSafely(fso, folderPath)
    On Error Resume Next
    If fso.FolderExists(folderPath) Then
        Dim folder, file, subFolder
        Set folder = fso.GetFolder(folderPath)
        For Each file In folder.Files
            file.Delete True
        Next
        For Each subFolder In folder.SubFolders
            Call DeleteFolderSafely(fso, subFolder.Path)
        Next
        fso.DeleteFolder folderPath, True
    End If
End Sub
