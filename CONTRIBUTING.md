# 向 Class Widgets 贡献代码

## 反馈
### 反馈 Bug

如果您在使用 Class Widgets 时遇到问题，可以在 Issues 中提交 **Bug 反馈**。

您的 Bug 反馈需要：
- 在最新版 ![GitHub Release](https://img.shields.io/github/v/release/RinLit-233-shiroko/Class-Widgets?include_prereleases)和[最新提交](https://github.com/RinLit-233-shiroko/Class-Widgets/commits)中未修复；
- 没有与您的 Bug 反馈相同或相似的 Issue。

如果您的 Bug 反馈与其他重复，我们将以“重复”原因关闭（Close as Duplicate）您的 Issue。您可以在 Issue 状态中找到对应的 Issue。

### 提交新功能请求

如果您在使用 Class Widgets 时有关于新功能的想法，您可以在 Discussions 中提交 **新功能请求**。

请注意，您的功能请求需要：
- 在 Class Widgets 版本 和最新提交中没有实现；
- 没有与您的功能请求相同或相似的 Discussion；
- 提交的功能是用户广泛需要的，插件不能替代的，且没有超出 **软件本来** 的开发目标，而非 **添加与课表及教学辅助无关的内容** 。

如果您的请求不符合上述要求，您的请求可能会被关闭，或转为 插件请求。

### 提交插件请求

如果您在使用 Class Widgets 时有关于新功能的想法，且该想法可以用插件实现，您可以在 Issues 中提交插件请求。

注意，您的插件请求需要：
- 在 Class Widgets 版本 和最新提交中没有实现；
- 没有与您的插件请求相同或相似的 Issue；
- 提交的功能是用户需要的，不是 **添加与课表及教学辅助无关的内容** 。
- 尽量详细说明插件的背景与动机，用途以及效果，以便插件开发人员能理解您想要实现的功能。

如果开发者认为您提交的功能是用户广泛需要的，您的请求可能会被转为 功能请求。您的 Issue 会被关闭并锁定，您可以通过页面上方的链接找到您的请求。

## 贡献代码

### 贡献准则

您为 Class Widgets 贡献的代码需要：
- **稳定**  
您贡献的代码需要能尽可能在多个平台稳定工作。
- **具有泛用性**  
与功能请求一样，您贡献的代码需要面向大部分用户。如果您的代码专用性较强，可以考虑开发插件或与开发者讨论。

### 提交

提交时，请尽量遵守[约定式提交](https://www.conventionalcommits.org/zh-hans/v1.0.0/)规范。

在约定式提交规范上，我们还建议您：
- **添加动词**  
如果您的提交是 fix（修复）类型，请您在提交信息中添加“修复”等动词和“的问题”等词汇。  
如果您的提交是 feat（功能）类型，您可以在提交信息中添加“增加”等动词和“功能”等词汇。这不是硬性要求。
- **注明范围（scope）**  
如果您的提交是 feat（功能）类型，且添加的是一整个功能，您不需要注明范围；如果添加的功能是一个大功能下的小功能（如 天气（weather） 功能下的 高德地图天气 功能），请您添加范围。  
如果您的提交是 fix（修复）类型，且修复的部分不属于下表的任何一个，您可以不添加范围；反之，请您添加范围。
在文档底部有一份对照表。


### 发起拉取请求

在提交拉取请求前，请先对您的代码进行测试。随后您可以向本仓库提交拉取请求。请您在拉取请求中简要说明您的更改。

> [!IMPORTANT]
> 因为 Class Widgets 同时兼容 Windows 7 及更新版本，Linux 和 macOS，请确保您引入的库同时兼容以上三类操作系统的对应版本，或对不兼容的系统或版本进行了规避。  
> 如果您不能在三个系统分别进行测试，您仍然可以提交拉取请求，但请在拉取请求描述中注明已测试的操作系统，以便我们进行测试。

### 合并拉取请求

在经过团队成员的代码审查和测试后，您的拉取请求会被合并。

## 还有问题？

您可以加入 [QQ 群](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=yHXKCAjOxlpTpJ4mNdXm0mxOneYUinRs&authKey=sd3%2F06iGdOZUjkXXPBeIzGnFDIeYwmdwuM8dhk25fi%2B1CUL32MkeN2EEfjdo2pzE&noverify=0&group_code=169200380)或 [Discord 服务器](https://discord.gg/EFF4PpqpqZ)与开发者和其他用户讨论。
