<div align="right">
<a href="/.github/CONTRIBUTING.md">简体中文</a> | English | <a href="/docs/contributing/CONTRIBUTING.ja.md">日本語</a>
</div>

# Contributing to `Class Widgets`

## Feedback

### Reporting Bugs

If you encounter issues while using Class Widgets, submit bug reports via Issues. Before submitting:

- Confirm the issue is **not fixed** in the [latest Release version](https://github.com/Class-Widgets/Class-Widgets/releases/latest) or [latest main branch commits](https://github.com/Class-Widgets/Class-Widgets/commits);
- Verify no identical or similar Issues exist (search using relevant keywords).

Bug reports **must include**:

- Operating system and version (e.g., Windows 10 21H2, macOS Ventura 13.4, Ubuntu 22.04);
- Software version (found in "About This Product");
- Step-by-step reproduction instructions (clear operational flow);
- Actual vs. expected results;
- Related screenshots, logs, or error reports.

Duplicate reports will be marked "duplicate" and closed, with links to original discussions.

### Submitting Feature Requests

For new feature ideas, submit Feature Requests in Discussions. Ensure:

- The feature is not implemented in the latest version or commits;
- No similar Discussions exist;
- The feature aligns with core goals (class schedule management & teaching assistance), has broad applicability (non-niche), and cannot be implemented via plugins.

Feature requests should include:

- Background (problem being solved);
- Implementation ideas (optional);
- Use cases and target user groups.

Requests failing these criteria may be closed or converted to "Plugin Requests".

### Submitting Plugin Requests

For plugin-suitable features, submit Plugin Requests via Issues. Ensure:

- The feature is **not implemented** in existing versions or plugins;
- No similar Issues exist;
- The feature relates to class schedules/teaching assistance and has practical value.

Plugin requests must include:

- Feature description (core capabilities);
- Usage scenarios (when to use the plugin);
- Expected interaction methods (optional).

If the team determines broad demand, plugin requests may be converted to Feature Requests, with the original Issue closed and linked.

## Contributing Code

### Contribution Guidelines

Your code must meet:

- **Stability**: Compatible with Windows 7+, major Linux distributions, and macOS 10.13+. Avoid platform-specific code; use conditional checks if necessary.
- **General Applicability**: Address majority user needs. Specialized features should be implemented as plugins.

### Commit Standards

Please follow the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification.

### Creating Pull Requests (PRs)

1. **Branch Preparation**:

   - Create a personal branch from the main repository's `main` branch. Naming convention: `feat/feature-name` or `fix/bug-description`;
   - Keep your branch synced with `main` to reduce merge conflicts:
     ```bash
     git fetch origin
     git rebase origin/main
     ```

2. **Pre-Commit Checks**:

   - Pass local tests (verify functionality on at least one OS);
   - Ensure no syntax errors and pass basic pylint checks;
   - Add new dependencies to `requirements.txt` with cross-platform compatibility.

3. **PR Description**:

   - Title: Briefly describe changes (match commit message when possible);
   - Content:
     - Purpose and implementation approach;
     - Tested operating systems (e.g., "Tested on: Windows 11, Ubuntu 22.04");
     - Related Issue/Discussion number (e.g., "Fixes #123").

### PR Review & Merging

- Team members will review code and may request modifications;
- PRs will be merged after approval and successful testing;
- If no feedback is received after 7 business days, politely remind the team via community channels.

## Contributing Translations

Class Widgets supports multilingual internationalization (i18n). Contribute translations via:

1. Visit the project's [Weblate translation platform](https://hosted.weblate.org/engage/class-widgets-1/);
2. Select your target language and translate uncompleted entries;
3. Ensure translations match software context and maintain terminology consistency (refer to the "Feature Terminology Table" appendix).

## Still Have Questions?

Join the QQ group or Discord server mentioned in the [README](/docs/readme/README.en_US.md) to discuss with developers and contributors.

## Appendix: Feature Terminology Table

| Chinese | English | Japanese |
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
