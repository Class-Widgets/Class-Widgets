# 可自定义 lrelease 路径，默认使用 'lrelease'
$lreleasePath = "lrelease"

# 遍历 ./ui 下所有主题文件夹
$themeFolders = Get-ChildItem -Path ./ui -Directory
foreach ($themeFolder in $themeFolders) {
    $i18nDir = Join-Path $themeFolder.FullName 'i18n'
    if (Test-Path $i18nDir) {
        $tsFiles = Get-ChildItem -Path $i18nDir -Filter *.ts -File
        foreach ($ts in $tsFiles) {
            $qm = [System.IO.Path]::ChangeExtension($ts.FullName, '.qm')
            & $lreleasePath $ts.FullName -qm $qm
        }
    }
}
