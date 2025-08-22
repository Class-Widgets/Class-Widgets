<div align="right">
简体中文 | <a href="/docs/contributing/CONTRIBUTING.en_US.md">English</a> | <a href="/docs/contributing/CONTRIBUTING.ja.md">日本語</a>
</div>

# 向 `Class Widgets` 贡献

## 反馈

### 反馈 Bug

如果您在使用 Class Widgets 时遇到问题，可在 Issues 中提交 Bug 反馈。提交前请先完成以下检查：

- 确认问题在 [最新 Release 版本](https://github.com/Class-Widgets/Class-Widgets/releases/latest) 和 [主分支最新提交](https://github.com/Class-Widgets/Class-Widgets/commits) 中未被修复；
- 确认没有相同或相似的 Issue 已存在（可通过关键词搜索验证）。

Bug 反馈需包含的信息：

- 操作系统及版本（如 Windows 10 21H2、macOS Ventura 13.4、Ubuntu 22.04）；
- 软件版本（可在「关于本产品」中查看）；
- 问题复现步骤（清晰描述操作流程）；
- 实际结果与预期结果；
- 相关截图或日志、错误报告。

若反馈重复，将被标记为 "重复" 并关闭，您可通过 Issue 关联找到原始讨论。

### 提交新功能请求

若您有新功能想法，可在 Discussions 中提交 功能请求。请确保：

- 功能未在最新版本或提交中实现；
- 无相同或相似的 Discussion 存在；
- 功能符合软件核心目标（聚焦课表管理及教学辅助），且具有广泛适用性（非小众需求），无法通过插件替代。

功能请求建议包含：

- 功能背景（解决什么问题）；
- 具体实现思路（可选）；
- 适用场景及用户群体。

不符合上述要求的请求可能被关闭或转为「插件请求」。

### 提交插件请求

若功能可通过插件实现，可在 Issues 中提交 插件请求。请确保：

- 功能未在现有版本或插件中实现；
- 无相同或相似的 Issue 存在；
- 功能与课表及教学辅助相关，具有实用价值。

插件请求需包含：

- 功能描述（需实现的核心能力）；
- 使用场景（何时会用到该插件）；
- 预期交互方式（可选）。

若团队认为功能具有广泛需求，可能将其转为「功能请求」，原 Issue 会被关闭并关联至新请求。

## 贡献代码

### 贡献准则

您贡献的代码需满足：

- **稳定性**：兼容 Windows 7+、Linux（主流发行版）、macOS 10.13+，避免引入平台特异性代码（若无法避免，需通过条件判断兼容）；
- **通用适用性**：面向多数用户需求，专用性功能建议以插件形式实现；

### 提交规范

请尽量遵循 [约定式提交](https://www.conventionalcommits.org/zh-hans) 规范。

### 发起拉取请求（PR）

1. **环境准备**

   - 本项目使用 [`uv`](https://docs.astral.sh/uv/getting-started/installation/) 作为项目包管理器，请使用任意方式安装最新的 uv 并在项目文件夹执行 `uv sync` 来配置环境
   - 推荐随后执行 `uv run pre-commit install` 添加提交前钩子进行代码风格统一

2. **分支准备**：

   - 基于主仓库 main 分支创建个人分支，命名建议：feat/功能名 或 fix/bug描述；

   - 确保分支与主仓库 main 分支同步（减少合并冲突）：

     ```bash
      git fetch origin
      git rebase origin/main
     ```

3. **提交前检查**：

   - 本地测试通过（至少在一个操作系统上验证功能）；
   - 代码无语法错误，运行 pylint 检查基本规范；
   - 新增依赖已添加至 `pyproject.toml`，并尽量兼容多平台。

4. **PR 描述**：

   - 标题：简要说明修改（建议与提交信息一致）；
   - 内容：
     - 修改目的及实现思路；
     - 已测试的操作系统（如 "测试通过：Windows 11、Ubuntu 22.04"）；
     - 关联的 Issue/Discussion 编号（如 Fixes #123）。

### 拉取请求审核与合并

- 团队成员会审核代码，可能提出修改建议，需您配合完善；
- 审核通过且测试无误后，PR 将被合并至主分支；
- 若超过 7 个工作日未收到反馈，可在社群中友好提醒。

## 贡献翻译

Class Widgets 支持多语言国际化（i18n），您可通过以下方式贡献翻译：

1. 访问项目 [Weblate 翻译平台](https://hosted.weblate.org/engage/class-widgets-1/)；
2. 选择目标语言，翻译未完成的词条；
3. 翻译需符合软件语境，保持术语一致性（参考附录「功能对照表」）。

## 还有问题？

可加入 [README](/README.md) 中提到的 QQ 群或 Discord 服务器，与开发者及其他贡献者讨论。

## 附录：功能对照表

| 中 | 英 | 日 |
| :-------------: | :----------------------: | :-------------------------: |
| 天气 | weather | 天気 |
| 提醒 | tip | リマインダー |
| TTS | tts | TTS |
| 插件广场 | pp/plugin_plaza | プラグイン広場 |
| 设置 | settings | 設定 |
| 设置 - 课表 | schedule | 設定 - 時間割 |
| 设置 - CSES | cses | 設定 - CSES |
| 设置 - 个性化 | customize | 設定 - カスタマイズ |
| 设置 - 高级选项 | advanced | 設定 - 詳細オプション |
| 额外选项 | additional options | 追加オプション |
| 轮播 | carousel | スライドショー |
| 多小组件 | multi-widgets | 複数ウィジェット |
| 倒计日 | countdown | カウントダウン |
| 倒计日编辑 | countdown editing | カウントダウン編集 |
| 课程表编辑 | schedule editing | 時間割編集 |
| 插件管理 | plugin management | プラグイン管理 |
| 帮助 | help | ヘルプ |
| 关于本产品 | about this product | 本製品について |
| 配置文件 | configuration file | 設定ファイル |
| 国际化 | i18n | 国際化 |
| 时间线 | timeline | タイムライン |
| 节点 | node | ノード |
| 上下课提醒 | class start/end reminder | 授業開始 / 終了リマインダー |
| 浮窗 | floating window | 浮動ウィンドウ |
| 课表预览 | schedule preview | 時間割プレビュー |
| 时间线编辑 | timeline editing | タイムライン編集 |
