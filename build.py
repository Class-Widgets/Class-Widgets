import os
import shutil
import PyInstaller.__main__

# 程序入口和资源文件夹配置
entry_file = 'main.py'
app_name = 'ClassWidgets'
resource_dirs = ['audio', 'config', 'font', 'plugins', 'Scripts', 'ui', 'view']

# 清理旧构建
if os.path.exists('dist'):
    shutil.rmtree('dist')
if os.path.exists('build'):
    shutil.rmtree('build')
if os.path.exists(f'{app_name}.spec'):
    os.remove(f'{app_name}.spec')

# 准备数据文件参数
datas_args = []
for directory in resource_dirs:
    if os.path.exists(directory):
        datas_args.append(f'--add-data={directory}{os.pathsep}{directory}')

# 添加所有.py文件
py_files = [f for f in os.listdir('.') if f.endswith('.py')]
for py_file in py_files:
    datas_args.append(f'--add-data={py_file}{os.pathsep}.')

# 构建PyInstaller命令
cmd = [
    entry_file,
    f'--name={app_name}',     # 生成的exe名称
    '--onedir',               # 目录模式（非单文件）
    '--console',              # 命令行程序
    '--distpath=./dist',      # 输出目录
    '--workpath=./build',     # 临时目录
    '--specpath=./',          # spec文件位置
    '--noconfirm',            # 覆盖现有文件
    '--paths=./',             # 添加当前目录到搜索路径
    '--clean',                # 清理缓存
]

# 添加资源文件夹和.py文件
cmd += datas_args

# 执行打包命令
PyInstaller.__main__.run(cmd)

print("\n" + "="*50)
print(f"打包完成！程序位于: dist/{app_name}")
print("目录结构:")
print(f"dist/{app_name}/")
print(f"├── {app_name}.exe")
print(f"├── main.py")
for py_file in py_files:
    if py_file != entry_file:
        print(f"├── {py_file}")
for directory in resource_dirs:
    if os.path.exists(directory):
        print(f"├── {directory}/")
print("└── ... (依赖文件)")
print("="*50)