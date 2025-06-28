# 可自定义 lrelease 路径，默认使用 'lrelease'
$lreleasePath = "lrelease"

# 查找 ./i18n 目录下所有 .ts 文件
$tsFiles = Get-ChildItem -Path ./i18n -Filter *.ts -File -Recurse

foreach ($ts in $tsFiles) {
    $qm = [System.IO.Path]::ChangeExtension($ts.FullName, '.qm')
    & $lreleasePath $ts.FullName -qm $qm
}
