# 可自定义 lupdate 路径，默认使用 'lupdate'（需在 PATH 中）
$lupdatePath = "lupdate"

# 遍历 ./ui 下所有主题文件夹
$themeFolders = Get-ChildItem -Path ./ui -Directory
foreach ($themeFolder in $themeFolders) {
    # 获取该主题文件夹下所有 .ui 文件
    $uiFiles = Get-ChildItem -Path $themeFolder.FullName -Filter *.ui -File -Recurse
    if ($uiFiles.Count -gt 0) {
        # 生成 ts 文件夹路径 ./ui/<主题文件夹>/i18n
        $i18nDir = Join-Path $themeFolder.FullName 'i18n'
        if (-not (Test-Path $i18nDir)) {
            New-Item -Path $i18nDir -ItemType Directory | Out-Null
        }
        # 生成 ts 文件名，格式如 ./ui/<主题文件夹>/i18n/<主题文件夹名>.ts
        $tsFile = Join-Path $i18nDir ("zh_CN.ts")
        # 只用该主题下的 ui 文件
        & $lupdatePath $uiFiles.FullName -ts $tsFile
    }
}
