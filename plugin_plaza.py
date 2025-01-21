import json
import sys
from datetime import datetime
from random import shuffle

from PyQt5 import uic
from PyQt5.QtCore import QSize, Qt, QTimer, QUrl, QStringListModel
from PyQt5.QtGui import QIcon, QPixmap, QDesktopServices
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QGridLayout, QSpacerItem, QSizePolicy, QWidget, \
    QScroller, QCompleter
from loguru import logger
from qfluentwidgets import MSFluentWindow, FluentIcon as fIcon, NavigationItemPosition, TitleLabel, \
    ImageLabel, StrongBodyLabel, HyperlinkLabel, CaptionLabel, PrimaryPushButton, HorizontalFlipView, \
    InfoBar, InfoBarPosition, SplashScreen, MessageBoxBase, TransparentToolButton, BodyLabel, \
    PrimarySplitPushButton, RoundMenu, Action, PipsPager, TextBrowser, CardWidget, \
    IndeterminateProgressRing, ComboBox, ProgressBar, SmoothScrollArea, SearchLineEdit, HyperlinkButton, SubtitleLabel, \
    MessageBox

import conf
import list as l
import network_thread as nt
from conf import base_directory
from utils import restart

# 适配高DPI缩放
QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

CONF_PATH = f"{base_directory}/plugins/plugins_from_pp.json"
PLAZA_REPO_URL = "https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/"
PLAZA_REPO_DIR = "https://api.github.com/repos/Class-Widgets/plugin-plaza/contents/Plugins"
TEST_DOWNLOAD_LINK = "https://dldir1.qq.com/qqfile/qq/PCQQ9.7.17/QQ9.7.17.29225.exe"

restart_tips_flag = False  # 重启提示
plugins_data = []  # 仓库插件信息
local_plugins_version = {}  # 本地插件版本
download_progress = []  # 下载线程

installed_plugins = {}  # 已安装插件（通过PluginPlaza获取）
tags = ['示例', '信息展示', '学习', '测试', '工具', '自动化']  # 测试用TAG
search_items = []
SELF_PLUGIN_VERSION = conf.read_conf('Plugin', 'version')  # 自身版本号
SEARCH_FIELDS = ["name", "description", "tag", "author"]  # 搜索字段


class TagLink(HyperlinkButton):  # 标签链接
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.tag = text
        self.setText(text)
        self.setIcon(fIcon.SEARCH)

        self.setFixedHeight(30)
        self.clicked.connect(self.search_tag)

    def search_tag(self):
        self.parent.search_plugin.setText(self.tag)
        self.parent.search_plugin.searchSignal.emit(self.tag)  # 发射搜索信号


class downloadProgressBar(InfoBar):  # 下载进度条(创建下载进程)
    def __init__(self, url=TEST_DOWNLOAD_LINK, branch='main', name="Test", parent=None):
        global download_progress
        self.p_name = url.split('/')[4]  # repo
        # user = url.split('/')[3]
        self.name = name
        self.url = f'{url}/archive/refs/heads/{branch}.zip'

        super().__init__(icon=fIcon.DOWNLOAD,
                         title='',
                         content=f"正在下载 {name} (～￣▽￣)～)",
                         orient=Qt.Horizontal,
                         isClosable=False,
                         position=InfoBarPosition.TOP,
                         duration=-1,
                         parent=parent
                         )
        self.setCustomBackgroundColor('white', '#202020')
        self.bar = ProgressBar()
        self.bar.setFixedWidth(300)
        self.cancelBtn = HyperlinkLabel()
        self.cancelBtn.setText("取消")
        self.cancelBtn.clicked.connect(self.cancelDownload)
        self.addWidget(self.bar)
        self.addWidget(self.cancelBtn)

        # 开始下载

        download_progress.append(self.p_name)
        self.download(self.url)

    def download(self, url):  # 接受下载连接并开始任务
        self.download_thread = nt.DownloadAndExtract(url, self.p_name)
        # self.download_thread = nt.DownloadAndExtract(TEST_DOWNLOAD_LINK, self.p_name)
        self.download_thread.progress_signal.connect(lambda progress: self.bar.setValue(int(progress)))  # 下载进度
        self.download_thread.status_signal.connect(self.detect_status)  # 判断状态
        self.download_thread.start()

    def cancelDownload(self):
        global download_progress
        download_progress.remove(self.p_name)
        self.download_thread.stop()
        self.download_thread.deleteLater()
        self.close()

    def detect_status(self, status):
        if status == "DOWNLOADING":
            self.content = f"正在下载 {self.name} (～￣▽￣)～)"
        elif status == "EXTRACTING":
            self.content = f"正在解压 {self.name} ( •̀ ω •́ )✧)"
        elif status == "DONE":
            self.download_finished()
        elif status.startswith("ERROR"):
            self.download_error(status[6:])
        else:
            pass

    def download_finished(self):
        global download_progress
        download_progress.remove(self.p_name)
        add2save_plugin(self.p_name)  # 保存到配置
        self.download_thread.finished.emit()
        self.download_thread.deleteLater()

        InfoBar.success(
            title='下载成功！',
            content=f"下载 {self.name} 成功！",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self.parent()
        )
        if not restart_tips_flag:  # 重启提示
            self.parent().restart_tips()
        self.close()

    def download_error(self, error_info):
        global download_progress
        download_progress.remove(self.p_name)
        InfoBar.error(
            title='下载失败(っ °Д °;)っ',
            content=f"{error_info}",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self.parent()
        )
        self.close()


def install_plugin(parent, p_name, data=dict):
    plugin_ver = str(data.get('plugin_ver'))
    if plugin_ver != SELF_PLUGIN_VERSION:  # 插件版本不匹配
        if plugin_ver > SELF_PLUGIN_VERSION:
            content = (f'此插件版本（{plugin_ver}）高于当前设备中 Class Widgets 兼容的插件版本（{SELF_PLUGIN_VERSION}）；\n'
                       f'请更新 Class Widgets 后再尝试安装此插件。')
        else:
            content = (f'此插件版本（{plugin_ver}）低于当前设备中 Class Widgets 兼容的插件版本（{SELF_PLUGIN_VERSION}）；\n'
                       f'可能是插件缺乏维护，请联系插件作者更新插件，或在社区（GitHub、QQ群）中提出问题。')

        cc = MessageBox(
            "本插件不兼容当前版本的 Class Widgets",
            f"{content}\n\n不建议安装此插件，否则将出现不可预料（包括崩溃、闪退等故障）的问题。",
            parent
        )  # 兼容性检查窗口
        cc.yesButton.setText("取消安装")
        cc.cancelButton.setText("强制安装（不建议）")
        if cc.exec():  # 取消安装
            return False

    if p_name not in download_progress:  # 如果正在下载
        url = data.get("url")
        branch = data.get("branch")
        title = data.get("title")

        di = downloadProgressBar(
            url=f"{url}",
            branch=branch,
            name=title,
            parent=parent
        )
        di.show()
        return True
    return False


class PluginDetailPage(MessageBoxBase):  # 插件详情页面
    def __init__(self, icon, title, content, tag, version, author, url, data=None, parent=None):
        super().__init__(parent)
        self.data = data
        self.branch = data.get("branch")
        self.title = title
        self.parent = parent
        self.url = url
        self.p_name = url.split('/')[-1]  # repo
        author_url = '/'.join(url.rsplit('/', 2)[:-1])
        self.init_ui()
        self.download_readme()
        scroll_area_widget = self.findChild(QVBoxLayout, 'verticalLayout_9')

        self.iconWidget = self.findChild(ImageLabel, 'pluginIcon')
        self.iconWidget.setImage(icon)
        self.iconWidget.setFixedSize(100, 100)
        self.iconWidget.setBorderRadius(8, 8, 8, 8)

        self.titleLabel = self.findChild(TitleLabel, 'titleLabel')  # 标题
        self.titleLabel.setText(title)

        self.contentLabel = self.findChild(CaptionLabel, 'descLabel')  # 描述
        self.contentLabel.setText(content)

        self.tagLabel = self.findChild(HyperlinkLabel, 'tagButton')  # tag
        self.tagLabel.setText(tag)

        self.versionLabel = self.findChild(BodyLabel, 'versionLabel')  # 版本
        self.versionLabel.setText(version)

        self.authorLabel = self.findChild(HyperlinkLabel, 'authorButton')  # 作者
        self.authorLabel.setText(author)
        self.authorLabel.setUrl(author_url)

        self.openGitHub = self.findChild(TransparentToolButton, 'openGitHub')  # 打开连接
        self.openGitHub.setIcon(fIcon.LINK)
        self.openGitHub.setIconSize(QSize(18, 18))
        self.openGitHub.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))

        self.installButton = self.findChild(PrimarySplitPushButton, 'installButton')
        self.installButton.setText("  安装  ")
        self.installButton.setIcon(fIcon.DOWNLOAD)
        self.installButton.clicked.connect(self.install)

        if self.p_name in download_progress:  # 如果正在下载
            self.installButton.setText("  安装中  ")
            self.installButton.setEnabled(False)
        if self.p_name in installed_plugins:  # 如果已安装
            self.installButton.setText("  已安装  ")
            self.installButton.setEnabled(False)

        if self.p_name in local_plugins_version:  # 如果本地版本低于仓库版本
            print(local_plugins_version[self.p_name], version)
            if local_plugins_version[self.p_name] < version:
                self.installButton.setText("更新")
                self.installButton.setIcon(fIcon.SYNC)
                self.installButton.setEnabled(True)

        menu = RoundMenu(parent=self.installButton)
        menu.addActions([
            Action(fIcon.DOWNLOAD, "为 Class Widgets 安装", triggered=self.install),
            Action(fIcon.LINK, "下载到本地",
                   triggered=lambda: QDesktopServices.openUrl(QUrl(f"{url}/releases/latest")))
        ])
        self.installButton.setFlyout(menu)

        self.readmePage = TextBrowser(self)
        self.readmePage.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.readmePage.setReadOnly(True)
        scroll_area_widget.addWidget(self.readmePage)

    def install(self):
        if install_plugin(self.parent, self.p_name, self.data):
            self.installButton.setText("  安装中  ")
            self.installButton.setEnabled(False)

    def download_readme(self):
        def display_readme(markdown_text):
            self.readmePage.setMarkdown(markdown_text)

        if self.data is None:
            self.download_thread = nt.getReadme(f"{replace_to_file_server(self.url)}/README.md")
        else:
            self.download_thread = nt.getReadme(f"{replace_to_file_server(self.url, self.data['branch'])}/README.md")
        self.download_thread.html_signal.connect(display_readme)
        self.download_thread.start()

    def init_ui(self):
        # 加载ui文件
        self.temp_widget = QWidget()
        uic.loadUi(f'{base_directory}/view/pp/plugin_detail.ui', self.temp_widget)
        self.viewLayout.addWidget(self.temp_widget)
        self.viewLayout.setContentsMargins(0, 0, 0, 0)
        # 隐藏原有按钮
        self.yesButton.hide()
        self.cancelButton.hide()
        self.buttonGroup.hide()

        # 自定关闭按钮
        self.closeButton = self.findChild(TransparentToolButton, 'closeButton')
        self.closeButton.setIcon(fIcon.CLOSE)
        self.closeButton.clicked.connect(self.close)

        self.widget.setMinimumWidth(875)
        self.widget.setMinimumHeight(625)


class PluginCard_Horizontal(CardWidget):  # 插件卡片（横向）
    def __init__(
            self, icon='img/plaza/plugin_pre.png', title='Plugin Name', content='Description...', tag='Unknown',
            version='1.0.0', author="CW Support",
            url="https://github.com/RinLit-233-shiroko/cw-example-plugin", data=None, parent=None):
        super().__init__(parent)
        self.icon = icon
        self.title = title
        self.plugin_ver = data.get('plugin_ver')
        self.parent = parent
        self.tag = tag
        self.branch = data.get("branch")
        self.url = url
        self.p_name = url.split('/')[-1]  # repo
        self.data = data
        author_url = '/'.join(self.url.rsplit('/', 2)[:-1])

        self.iconWidget = ImageLabel(icon)  # 插件图标
        self.titleLabel = StrongBodyLabel(title, self)  # 插件名
        self.versionLabel = CaptionLabel(version, self)  # 插件版本
        self.authorLabel = HyperlinkLabel()  # 插件作者
        self.contentLabel = CaptionLabel(content, self)  # 插件描述
        self.installButton = PrimaryPushButton()

        # layout
        self.hBoxLayout = QHBoxLayout(self)
        self.hBoxLayout_Title = QHBoxLayout()
        self.hBoxLayout_Author = QHBoxLayout()
        self.vBoxLayout = QVBoxLayout(self)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(110)
        self.setMinimumWidth(250)
        self.authorLabel.setText(author)
        self.authorLabel.setUrl(author_url)
        self.authorLabel.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.iconWidget.setFixedSize(84, 84)
        self.iconWidget.setBorderRadius(5, 5, 5, 5)  # 圆角
        self.contentLabel.setTextColor("#606060", "#d2d2d2")
        self.contentLabel.setWordWrap(True)
        self.versionLabel.setTextColor("#999999", "#999999")
        self.titleLabel.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        self.installButton.setText("安装")
        self.installButton.setMaximumSize(100, 36)
        self.installButton.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.installButton.setIcon(fIcon.DOWNLOAD)
        self.installButton.clicked.connect(self.install)

        if self.p_name in installed_plugins:  # 如果已安装
            self.installButton.setText("已安装")
            self.installButton.setEnabled(False)

        if self.p_name in local_plugins_version:  # 如果本地版本低于仓库版本
            print(local_plugins_version[self.p_name], version)
            if local_plugins_version[self.p_name] < version:
                self.installButton.setText("更新")
                self.installButton.setIcon(fIcon.SYNC)
                self.installButton.setEnabled(True)

        self.hBoxLayout.setContentsMargins(20, 11, 11, 11)
        self.hBoxLayout.setSpacing(15)
        self.hBoxLayout.addWidget(self.iconWidget)

        self.blank = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.vBoxLayout.setContentsMargins(0, 5, 0, 5)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addLayout(self.hBoxLayout_Title)
        self.vBoxLayout.addLayout(self.hBoxLayout_Author)
        self.vBoxLayout.addItem(self.blank)
        self.vBoxLayout.addWidget(self.contentLabel, 0, Qt.AlignmentFlag.AlignTop)
        self.vBoxLayout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.hBoxLayout.addLayout(self.vBoxLayout)
        self.hBoxLayout.addWidget(self.installButton)

        self.hBoxLayout_Title.setSpacing(12)
        self.hBoxLayout_Title.addWidget(self.titleLabel, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hBoxLayout_Title.addWidget(self.versionLabel, 0, Qt.AlignmentFlag.AlignVCenter)

        self.hBoxLayout_Author.addWidget(self.authorLabel, 0, Qt.AlignmentFlag.AlignLeft)

    def install(self):
        install_plugin(self.parent, self.p_name, self.data)

    def set_img(self, img):
        try:
            self.icon = img
            self.iconWidget.setImage(img)
            self.iconWidget.setFixedSize(84, 84)
        except Exception as e:
            logger.error(f"设置插件图片失败: {e}")

    def show_detail(self):
        w = PluginDetailPage(
            icon=self.icon, title=self.title, content=self.contentLabel.text(),
            tag=self.tag, version=self.versionLabel.text(), author=self.authorLabel.text(),
            url=self.url, data=self.data, parent=self.parent
        )
        w.exec()


class PluginPlaza(MSFluentWindow):
    def __init__(self):
        super().__init__()
        global installed_plugins
        try:
            with open(CONF_PATH, 'r', encoding='utf-8') as file:
                installed_plugins = json.load(file).get('plugins')
        except Exception as e:
            logger.error(f"读取已安装的插件失败: {e}")
        try:
            self.homeInterface = uic.loadUi(f'{base_directory}/view/pp/home.ui')  # 首页
            self.homeInterface.setObjectName("homeInterface")
            self.latestsInterface = uic.loadUi(f'{base_directory}/view/pp/latests.ui')  # 最新更新
            self.latestsInterface.setObjectName("latestInterface")
            self.settingsInterface = uic.loadUi(f'{base_directory}/view/pp/settings.ui')  # 设置
            self.settingsInterface.setObjectName("settingsInterface")
            self.searchInterface = uic.loadUi(f'{base_directory}/view/pp/search.ui')  # 搜索
            self.searchInterface.setObjectName("searchInterface")

            load_local_plugins_version()  # 加载本地插件版本
            self.init_nav()
            self.init_window()
            self.get_pp_data()
            self.get_tags_data()
            self.get_banner_img()
        except Exception as e:
            logger.error(f'初始化插件广场时发生错误：{e}')

    def load_all_interface(self):
        self.setup_homeInterface()
        self.setup_settingsInterface()
        self.setup_searchInterface()

    def setup_searchInterface(self):  # 初始化搜索
        search_scroll = self.searchInterface.findChild(SmoothScrollArea, 'search_scroll')

        def search(keyword):  # 搜索
            result = {}
            for key, value in plugins_data.items():
                if any(keyword.lower() in str(value.get(field, "")).lower() for field in SEARCH_FIELDS):
                    result[key] = value
            return result

        def clear_results():
            for i in reversed(range(self.search_plugin_grid.count())):
                widget = self.search_plugin_grid.itemAt(i).widget()
                if widget:
                    widget.setParent(None)  # 移除控件
                    widget.deleteLater()

        def search_plugins():  # 搜索插件
            if not plugins_data:
                return
            clear_results()

            if self.search_plugin.text():
                def set_plugin_image(plugin_card, data):
                    pixmap = QPixmap()
                    pixmap.loadFromData(data)
                    plugin_card.set_img(pixmap)

                keyword = self.search_plugin.text()
                print(search(keyword))  # 结果
                plugin_num = 0  # 计数
                for key, data in search(keyword).items():
                    plugin_card = PluginCard_Horizontal(title=data['name'], content=data['description'],
                                                        tag=data['tag'], version=data['version'], url=data['url'],
                                                        author=data['author'], data=data, parent=self)
                    plugin_card.clicked.connect(plugin_card.show_detail)  # 点击事件

                    # 启动线程加载图片
                    image_thread = nt.getImg(f"{replace_to_file_server(data['url'], data['branch'])}/icon.png")
                    image_thread.repo_signal.connect(
                        lambda img_data, card=plugin_card: set_plugin_image(card, img_data))
                    image_thread.start()

                    self.search_plugin_grid.addWidget(plugin_card, plugin_num // 2, plugin_num % 2)  # 排列
                    plugin_num += 1

        self.search_plugin_grid = self.searchInterface.findChild(QGridLayout, 'search_plugin_grid')  # 插件表格
        self.tags_layout = self.searchInterface.findChild(QGridLayout, 'tags_layout')  # tag 布局
        self.search_plugin = self.searchInterface.findChild(SearchLineEdit, 'search_plugin')
        self.search_plugin.searchSignal.connect(search_plugins)
        self.search_plugin.returnPressed.connect(search_plugins)
        self.search_plugin.clearSignal.connect(clear_results)
        self.search_completer = QCompleter(search_items, self.search_plugin)
        # 设置显示的选项数
        self.search_completer.setMaxVisibleItems(10)
        self.search_completer.setFilterMode(Qt.MatchContains)  # 内容匹配
        self.search_completer.setCaseSensitivity(Qt.CaseInsensitive)  # 不区分大小写
        self.search_completer.activated.connect(search_plugins)
        self.search_plugin.setCompleter(self.search_completer)

        QScroller.grabGesture(search_scroll.viewport(), QScroller.LeftMouseButtonGesture)

    def setup_settingsInterface(self):  # 初始化设置
        # 选择代理
        select_mirror = self.settingsInterface.findChild(ComboBox, 'select_proxy')
        select_mirror.addItems(nt.mirror_list)
        select_mirror.setCurrentIndex(nt.mirror_list.index(conf.read_conf('Plugin', 'mirror')))
        select_mirror.currentIndexChanged.connect(
            lambda: conf.write_conf('Plugin', 'mirror', select_mirror.currentText()))

    def setup_homeInterface(self):  # 初始化首页
        # 标题和副标题
        home_scroll = self.homeInterface.findChild(SmoothScrollArea, 'home_scroll')
        time_today_label = self.homeInterface.findChild(TitleLabel, 'time_today_label')
        time_today_label.setText(f"{datetime.now().month}月{datetime.now().day}日 {l.week[datetime.now().weekday()]}")

        # Banner
        self.banner_view = self.homeInterface.findChild(HorizontalFlipView, 'banner_view')
        self.banner_view.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.banner_view.setItemSize(QSize(900, 450))  # 设置图片大小（banner图片尺寸比）
        self.banner_view.setBorderRadius(8)
        self.banner_view.setSpacing(5)
        self.banner_view.clicked.connect(self.open_banner_link)

        self.auto_play_timer = QTimer(self)  # 自动轮播
        self.auto_play_timer.timeout.connect(lambda: self.switch_banners())
        self.auto_play_timer.setInterval(2500)

        # 翻页
        self.banner_pager = self.homeInterface.findChild(PipsPager, 'banner_pager')
        self.banner_pager.setVisibleNumber(5)
        self.banner_pager.currentIndexChanged.connect(
            lambda: (self.banner_view.scrollToIndex(self.banner_pager.currentIndex()),
                     self.auto_play_timer.stop(),
                     self.auto_play_timer.start(2500))
        )
        QScroller.grabGesture(home_scroll.viewport(), QScroller.LeftMouseButtonGesture)

    def open_banner_link(self):
        if not hasattr(self, 'img_list'):
            QDesktopServices.openUrl(QUrl(
                'https://www.yuque.com/rinlit/class-widgets_help/ez4vv7tv8wikxc0s#Se2Bb'
            ))
            return False  # 没有图片

        if self.img_list[self.banner_view.currentIndex()] in self.banners_data:
            if not self.banners_data[self.img_list[self.banner_view.currentIndex()]]['link']:
                return False  # 无链接
            QDesktopServices.openUrl(QUrl(
                self.banners_data[self.img_list[self.banner_view.currentIndex()]]['link']
            ))

    def set_tags_data(self, data):
        global tags, search_items
        if data:
            tags = data.get('tags')
            shuffle(tags)  # 随机
        for tag in tags:
            search_items.append(tag)
            self.search_completer.setModel(QStringListModel(search_items))  # 设置搜索提示
        tag_num = 0  # 计数
        for tag in tags[:6]:
            tag_link = TagLink(tag, self)
            self.tags_layout.addWidget(tag_link, tag_num // 3, tag_num % 3)  # 排列
            tag_num += 1

    def load_recommend_plugin(self, p_data):
        global plugins_data, search_items
        plugins_data = p_data  # 保存插件数据
        print(plugins_data)

        for plugin in p_data.values():  # 遍历插件数据
            search_items.append(plugin['name'])
            if plugin['author'] not in search_items:
                search_items.append(plugin['author'])
        self.search_completer.setModel(QStringListModel(search_items))  # 设置搜索提示

        def set_plugin_image(plugin_card, data):
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            plugin_card.set_img(pixmap)

        self.rec_plugin_grid = self.homeInterface.findChild(QGridLayout, 'rec_plugin_grid')  # 插件表格
        plugin_num = 0  # 计数

        for plugin, data in p_data.items():  # 遍历插件数据
            plugin_card = PluginCard_Horizontal(title=data['name'], content=data['description'],
                                                tag=data['tag'], version=data['version'], url=data['url'],
                                                author=data['author'], data=data, parent=self)
            plugin_card.clicked.connect(plugin_card.show_detail)  # 点击事件

            # 启动线程加载图片
            image_thread = nt.getImg(f"{replace_to_file_server(data['url'], data['branch'])}/icon.png")
            image_thread.repo_signal.connect(lambda img_data, card=plugin_card: set_plugin_image(card, img_data))
            image_thread.start()

            self.rec_plugin_grid.addWidget(plugin_card, plugin_num // 2, plugin_num % 2)  # 排列
            plugin_num += 1

        self.homeInterface.findChild(IndeterminateProgressRing, 'load_plugin_progress').hide()

    def get_banner_img(self):
        def display_banner(data, index=0):
            if index == 0:
                self.auto_play_timer.start()
            if data:
                pixmap = QPixmap()
                pixmap.loadFromData(data)
                self.banner_view.setItemImage(index, pixmap)
            self.splashScreen.hide()

        def get_banner(data=dict):
            try:
                if 'error' not in data:
                    self.banners_data = data
                    self.img_list = self.img_links = list(data.keys())
                    self.img_links = [f'https://raw.githubusercontent.com/Class-Widgets/plugin-plaza/main/Banner/'
                                      f'{img}.png' for img in self.img_links]
                    self.banner_pager.setPageNumber(len(data))
                    banner_placeholders = ["img/plaza/banner_pre.png" for _ in range(len(data))]
                    self.banner_view.addImages(banner_placeholders)
                else:
                    logger.error(f'PluginPlaza 无法联网，错误：{data["error"]}')
                    self.findChild(BodyLabel, 'tips').setText(f'错误原因：{data["error"]}')
                    self.banner_view.addImage("img/plaza/banner_network-failed.png")
                    self.splashScreen.hide()
                    self.homeInterface.findChild(SubtitleLabel, 'SubtitleLabel_3').hide()  # 隐藏副标题
                    return

                # 定义一个内部函数来启动下一个线程
                def start_next_banner(index):
                    if index < len(data):
                        self.banner_thread = nt.getImg(self.img_links[index])
                        self.banner_thread.repo_signal.connect(lambda data: display_banner(data, index))
                        self.banner_thread.repo_signal.connect(lambda: start_next_banner(index + 1))  # 连接完成信号
                        self.banner_thread.start()

                start_next_banner(0)  # 启动第一个线程

            except Exception as e:
                logger.error(f"获取Banner失败：{e}")

        self.banner_list_thread = nt.getRepoFileList()
        self.banner_list_thread.repo_signal.connect(get_banner)
        self.banner_list_thread.start()

    def restart_tips(self):
        global restart_tips_flag
        restart_tips_flag = True
        w = InfoBar.info(
            title='需要重启',
            content='若要应用插件配置，需重启 Class Widgets',
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=-1,
            parent=self
        )
        restart_btn = HyperlinkLabel('现在重启')
        restart_btn.clicked.connect(restart)
        w.addWidget(restart_btn)
        w.show()

    def get_pp_data(self):
        global plugins_data
        self.get_plugin_list_thread = nt.getPluginInfo()
        self.get_plugin_list_thread.repo_signal.connect(self.load_recommend_plugin)
        self.get_plugin_list_thread.start()

    def get_tags_data(self):
        self.get_tags_list_thread = nt.getTags()
        self.get_tags_list_thread.repo_signal.connect(self.set_tags_data)
        self.get_tags_list_thread.start()

    def switch_banners(self):  # 切换Banner
        if self.banner_view.currentIndex() == len(self.img_list) - 1:
            self.banner_view.scrollToIndex(0)
            self.banner_pager.setCurrentIndex(0)
        else:
            self.banner_view.scrollNext()
            self.banner_pager.setCurrentIndex(self.banner_view.currentIndex())

    def init_nav(self):
        self.addSubInterface(self.homeInterface, fIcon.HOME, '首页', fIcon.HOME_FILL)
        self.addSubInterface(self.latestsInterface, fIcon.LIBRARY, '最新上架', fIcon.LIBRARY_FILL)
        self.addSubInterface(
            self.searchInterface, fIcon.SEARCH, '搜索', position=NavigationItemPosition.BOTTOM
        )
        self.addSubInterface(
            self.settingsInterface, fIcon.SETTING, '设置', fIcon.SETTING, position=NavigationItemPosition.BOTTOM
        )

    def init_window(self):
        self.load_all_interface()
        self.init_font()

        self.setMinimumWidth(850)
        self.setMinimumHeight(500)
        self.setMicaEffectEnabled(True)
        self.setWindowTitle('插件广场')
        self.setWindowIcon(QIcon(f'{base_directory}/img/pp_favicon.png'))

        screen_geometry = QApplication.primaryScreen().geometry()
        screen_width = screen_geometry.width()
        screen_height = screen_geometry.height()

        width = int(screen_width * 0.6)
        height = int(screen_height * 0.7)

        self.move(int(screen_width / 2 - width / 2), 150)
        self.resize(width, height)

        # 启动屏幕
        self.splashScreen = SplashScreen(self.windowIcon(), self)
        self.splashScreen.setIconSize(QSize(102, 102))
        self.show()

    def init_font(self):  # 设置字体
        self.setStyleSheet("""QLabel {
                    font-family: 'Microsoft YaHei';
                }""")


def add2save_plugin(p_name):  # 保存已安装插件
    global installed_plugins
    installed_plugins.append(p_name)
    try:
        with open(CONF_PATH, 'r+', encoding='utf-8') as f:
            if p_name not in json.load(f)['plugins']:
                f.seek(0)  # 指针指向开头
                json.dump({"plugins": installed_plugins}, f, ensure_ascii=False, indent=4)
                f.truncate()  # 截断文件
    except Exception as e:
        logger.error(f"保存已安装插件失败：{e}")


def replace_to_file_server(url, branch='main'):
    return (f'{url.replace("https://github.com/", "https://raw.githubusercontent.com/")}'
            f'/{branch}')


def load_local_plugins_version():
    global local_plugins_version
    for plugin in installed_plugins:
        try:
            with open(f"plugins/{plugin}/plugin.json", 'r', encoding='utf-8') as f:
                data = json.load(f)
                local_plugins_version[plugin] = data['version']
        except Exception as e:
            logger.error(f"加载本地插件版本失败：{e}")
    print(local_plugins_version)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    pp = PluginPlaza()
    pp.show()
    sys.exit(app.exec())
