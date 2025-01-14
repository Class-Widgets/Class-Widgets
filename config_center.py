from pathlib import Path
from typing import Literal, Optional

EXE_PATH = Path(__file__).parent
CONFIG_FILE_PATH = EXE_PATH / "config.ini"
DEFAULT_CONFIG_PATH = EXE_PATH / "config" / "default_config.json"


def ternary_choice(input: Optional[int], default: Literal[0, 1, 2]) -> Literal[0, 1, 2]:
    return input if input == 0 or input == 1 or input == 2 else default


class GeneralConfig:
    __schedule: str = "新课表 - 1.json"
    """课程表"""
    __pin_on_top: Literal[0, 1, 2] = 1
    """
    窗口置顶：
    - 0：不置顶
    - 1：置顶
    - 2：置低
    """
    __margin: int = 10
    """窗口边距"""
    __time_offset: int = 0
    """时间偏移"""
    __opacity: int = 95
    """透明度"""
    __auto_startup: bool = False
    """开机自启"""
    __hide: Literal[0, 1, 2] = 0
    """
    自动隐藏
    - 0：不自动隐藏
    - 1：上课自动隐藏
    - 2：最大化/全屏自动隐藏
    """
    __hide_method: Literal[0, 1, 2] = 0
    """
    隐藏方式
    - 0：完全隐藏
    - 1：半隐藏
    - 2：隐藏为浮窗
    """
    __color_mode: Literal[0, 1, 2] = 2
    """
    色彩模式
    - 0：浅色
    - 1：深色
    - 2：自动
    """
    __enable_alt_schedule: bool = False
    """启用备用课程表"""
    __blur_countdown: bool = False
    """模糊倒计时"""
    __theme: str = "default"
    """主题"""
    __scale: float = 1
    """缩放"""

    def __init__(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        self.__schedule = config.get("General", "schedule", fallback="新课表 - 1.json")
        self.__pin_on_top = ternary_choice(
            config.getint("General", "pin_on_top", fallback=1), 1
        )
        self.__margin = config.getint("General", "margin", fallback=10)
        self.__time_offset = config.getint("General", "time_offset", fallback=0)
        self.__opacity = config.getint("General", "opacity", fallback=95)
        self.__auto_startup = config.getboolean(
            "General", "auto_startup", fallback=False
        )
        self.__hide = ternary_choice(config.getint("General", "hide", fallback=0), 0)
        self.__hide_method = ternary_choice(
            config.getint("General", "hide_method", fallback=0), 0
        )
        self.__color_mode = ternary_choice(
            config.getint("General", "color_mode", fallback=2), 2
        )
        self.__enable_alt_schedule = config.getboolean(
            "General", "enable_alt_schedule", fallback=False
        )
        self.__blur_countdown = config.getboolean(
            "General", "blur_countdown", fallback=False
        )
        self.__theme = config.get("General", "theme", fallback="default")
        self.__scale = config.getfloat("General", "scale", fallback=1)

    def save_config(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        if "General" not in config.sections():
            config.add_section("General")

        config.set("General", "schedule", self.__schedule)
        config.set("General", "pin_on_top", str(self.__pin_on_top))
        config.set("General", "margin", str(self.__margin))
        config.set("General", "time_offset", str(self.__time_offset))
        config.set("General", "opacity", str(self.__opacity))
        config.set("General", "auto_startup", str(int(self.__auto_startup)))
        config.set("General", "hide", str(self.__hide))
        config.set("General", "hide_method", str(self.__hide_method))
        config.set("General", "color_mode", str(self.__color_mode))
        config.set(
            "General", "enable_alt_schedule", str(int(self.__enable_alt_schedule))
        )
        config.set("General", "blur_countdown", str(int(self.__blur_countdown)))
        config.set("General", "theme", self.__theme)
        config.set("General", "scale", str(self.__scale))

        with open(CONFIG_FILE_PATH, "w") as configfile:
            config.write(configfile)

    @property
    def schedule(self) -> str:
        return self.__schedule

    @schedule.setter
    def schedule(self, value: str) -> None:
        self.__schedule = value
        self.save_config()

    @property
    def pin_on_top(self) -> Literal[0, 1, 2]:
        return self.__pin_on_top

    @pin_on_top.setter
    def pin_on_top(self, value: Literal[0, 1, 2]) -> None:
        self.__pin_on_top = value
        self.save_config()

    @property
    def margin(self) -> int:
        return self.__margin

    @margin.setter
    def margin(self, value: int) -> None:
        self.__margin = value
        self.save_config()

    @property
    def time_offset(self) -> int:
        return self.__time_offset

    @time_offset.setter
    def time_offset(self, value: int) -> None:
        self.__time_offset = value
        self.save_config()

    @property
    def opacity(self) -> int:
        return self.__opacity

    @opacity.setter
    def opacity(self, value: int) -> None:
        self.__opacity = value
        self.save_config()

    @property
    def auto_startup(self) -> bool:
        return self.__auto_startup

    @auto_startup.setter
    def auto_startup(self, value: bool) -> None:
        self.__auto_startup = value
        self.save_config()

    @property
    def hide(self) -> Literal[0, 1, 2]:
        return self.__hide

    @hide.setter
    def hide(self, value: Literal[0, 1, 2]) -> None:
        self.__hide = value
        self.save_config()

    @property
    def hide_method(self) -> Literal[0, 1, 2]:
        return self.__hide_method

    @hide_method.setter
    def hide_method(self, value: Literal[0, 1, 2]) -> None:
        self.__hide_method = value
        self.save_config()

    @property
    def color_mode(self) -> Literal[0, 1, 2]:
        return self.__color_mode

    @color_mode.setter
    def color_mode(self, value: Literal[0, 1, 2]) -> None:
        self.__color_mode = value
        self.save_config()

    @property
    def enable_alt_schedule(self) -> bool:
        return self.__enable_alt_schedule

    @enable_alt_schedule.setter
    def enable_alt_schedule(self, value: bool) -> None:
        self.__enable_alt_schedule = value
        self.save_config()

    @property
    def blur_countdown(self) -> bool:
        return self.__blur_countdown

    @blur_countdown.setter
    def blur_countdown(self, value: bool) -> None:
        self.__blur_countdown = value
        self.save_config()

    @property
    def theme(self) -> str:
        return self.__theme

    @theme.setter
    def theme(self, value: str) -> None:
        self.__theme = value
        self.save_config()

    @property
    def scale(self) -> float:
        return self.__scale

    @scale.setter
    def scale(self, value: float) -> None:
        self.__scale = value
        self.save_config()


class ToastConfig:
    __enable_wave: bool = True
    """开启涟漪效果"""
    __pin_on_top: bool = True
    """通知窗口置顶"""
    __ringtone: int = 1
    """
    铃声
    TODO: DOCUMENTATION
    """
    __prepare_minutes: int = 2
    """准备时间（分钟）"""
    __attend_class: bool = True
    """上课提醒"""
    __finish_class: bool = True
    """下课提醒"""
    __prepare_class: bool = True
    """课间预备提醒"""

    def __init__(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        if "Toast" in config.sections():
            self.__enable_wave = config.getboolean(
                "Toast", "enable_wave", fallback=True
            )
            self.__pin_on_top = config.getboolean("Toast", "pin_on_top", fallback=True)
            self.__ringtone = config.getint("Toast", "ringtone", fallback=1)
            self.__prepare_minutes = config.getint(
                "Toast", "prepare_minutes", fallback=2
            )
            self.__attend_class = config.getboolean(
                "Toast", "attend_class", fallback=True
            )
            self.__finish_class = config.getboolean(
                "Toast", "finish_class", fallback=True
            )
            self.__prepare_class = config.getboolean(
                "Toast", "prepare_class", fallback=True
            )

    def save_config(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        if "Toast" not in config.sections():
            config.add_section("Toast")

        config.set("Toast", "enable_wave", str(int(self.__enable_wave)))
        config.set("Toast", "pin_on_top", str(int(self.__pin_on_top)))
        config.set("Toast", "ringtone", str(self.__ringtone))
        config.set("Toast", "prepare_minutes", str(self.__prepare_minutes))
        config.set("Toast", "attend_class", str(int(self.__attend_class)))
        config.set("Toast", "finish_class", str(int(self.__finish_class)))
        config.set("Toast", "prepare_class", str(int(self.__prepare_class)))

        with open(CONFIG_FILE_PATH, "w") as configfile:
            config.write(configfile)

    @property
    def enable_wave(self) -> bool:
        return self.__enable_wave

    @enable_wave.setter
    def enable_wave(self, value: bool) -> None:
        self.__enable_wave = value
        self.save_config()

    @property
    def pin_on_top(self) -> bool:
        return self.__pin_on_top

    @pin_on_top.setter
    def pin_on_top(self, value: bool) -> None:
        self.__pin_on_top = value
        self.save_config()

    @property
    def ringtone(self) -> int:
        return self.__ringtone

    @ringtone.setter
    def ringtone(self, value: int) -> None:
        self.__ringtone = value
        self.save_config()

    @property
    def prepare_minutes(self) -> int:
        return self.__prepare_minutes

    @prepare_minutes.setter
    def prepare_minutes(self, value: int) -> None:
        self.__prepare_minutes = value
        self.save_config()

    @property
    def attend_class(self) -> bool:
        return self.__attend_class

    @attend_class.setter
    def attend_class(self, value: bool) -> None:
        self.__attend_class = value
        self.save_config()

    @property
    def finish_class(self) -> bool:
        return self.__finish_class

    @finish_class.setter
    def finish_class(self, value: bool) -> None:
        self.__finish_class = value
        self.save_config()

    @property
    def prepare_class(self) -> bool:
        return self.__prepare_class

    @prepare_class.setter
    def prepare_class(self, value: bool) -> None:
        self.__prepare_class = value
        self.save_config()


class WeatherConfig:
    __city: int = 101010100
    __api: str = "xiaomi_weather"
    __api_key: str = ""

    def __init__(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        if "Weather" in config.sections():
            self.city = config.getint("Weather", "city", fallback=101010100)
            self.api = config.get("Weather", "api", fallback="xiaomi_weather")
            self.api_key = config.get("Weather", "api_key", fallback="")

    def save_config(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        if "Weather" not in config.sections():
            config.add_section("Weather")

        config.set("Weather", "city", str(self.__city))
        config.set("Weather", "api", self.__api)
        config.set("Weather", "api_key", self.__api_key)

        with open(CONFIG_FILE_PATH, "w") as configfile:
            config.write(configfile)

    @property
    def city(self) -> int:
        return self.__city

    @city.setter
    def city(self, value: int) -> None:
        self.__city = value
        self.save_config()

    @property
    def api(self) -> str:
        return self.__api

    @api.setter
    def api(self, value: str) -> None:
        self.__api = value
        self.save_config()

    @property
    def api_key(self) -> str:
        return self.__api_key

    @api_key.setter
    def api_key(self, value: str) -> None:
        self.__api_key = value
        self.save_config()


class ColorConfig:
    __attend_class: str = "DD986F"
    __finish_class: str = "46B878"
    __prepare_class: str = "7065D8"

    def __init__(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        if "Color" in config.sections():
            self.__attend_class = config.get("Color", "attend_class", fallback="DD986F")
            self.__finish_class = config.get("Color", "finish_class", fallback="46B878")
            self.__prepare_class = config.get(
                "Color", "prepare_class", fallback="7065D8"
            )

    def save_config(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        if "Color" not in config.sections():
            config.add_section("Color")

        config.set("Color", "attend_class", self.__attend_class)
        config.set("Color", "finish_class", self.__finish_class)
        config.set("Color", "prepare_class", self.__prepare_class)

        with open(CONFIG_FILE_PATH, "w") as configfile:
            config.write(configfile)

    @property
    def attend_class(self) -> str:
        return self.__attend_class

    @attend_class.setter
    def attend_class(self, value: str) -> None:
        self.__attend_class = value
        self.save_config()

    @property
    def finish_class(self) -> str:
        return self.__finish_class

    @finish_class.setter
    def finish_class(self, value: str) -> None:
        self.__finish_class = value
        self.save_config()

    @property
    def prepare_class(self) -> str:
        return self.__prepare_class

    @prepare_class.setter
    def prepare_class(self, value: str) -> None:
        self.__prepare_class = value
        self.save_config()


class PluginConfig:
    __version: int = 1
    __mirror: str = "gh_proxy"
    __auto_delay: int = 5

    def __init__(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        if "Plugin" in config.sections():
            self.__version = config.getint("Plugin", "version", fallback=1)
            self.__mirror = config.get("Plugin", "mirror", fallback="gh_proxy")
            self.__auto_delay = config.getint("Plugin", "auto_delay", fallback=5)

    def save_config(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        if "Plugin" not in config.sections():
            config.add_section("Plugin")

        config.set("Plugin", "version", str(self.__version))
        config.set("Plugin", "mirror", self.__mirror)
        config.set("Plugin", "auto_delay", str(self.__auto_delay))

        with open(CONFIG_FILE_PATH, "w") as configfile:
            config.write(configfile)

    @property
    def version(self) -> int:
        return self.__version

    @version.setter
    def version(self, value: int) -> None:
        self.__version = value
        self.save_config()

    @property
    def mirror(self) -> str:
        return self.__mirror

    @mirror.setter
    def mirror(self, value: str) -> None:
        self.__mirror = value
        self.save_config()

    @property
    def auto_delay(self) -> int:
        return self.__auto_delay

    @auto_delay.setter
    def auto_delay(self, value: int) -> None:
        self.__auto_delay = value
        self.save_config()


# data = {"start_date": "", "cd_text_custom": "自定义", "countdown_date": ""}


class DateConfig:
    __start_date: str
    __cd_text_custom: str
    __countdown_date: Optional[str]

    def __init__(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        if "Date" not in config.sections():
            config.add_section("Date")

        self.__start_date = config.get("Date", "start_date", fallback="")
        self.__cd_text_custom = config.get("Date", "cd_text_custom", fallback="自定义")
        self.__countdown_date = config.get("Date", "countdown_date", fallback=None)

    def save_config(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        if "Date" not in config.sections():
            config.add_section("Date")

        config.set("Date", "start_date", self.__start_date)
        config.set("Date", "cd_text_custom", self.__cd_text_custom)
        config.set(
            "Date",
            "countdown_date",
            self.__countdown_date if self.__countdown_date else "",
        )

        with open(CONFIG_FILE_PATH, "w") as configfile:
            config.write(configfile)

    @property
    def start_date(self) -> str:
        return self.__start_date

    @start_date.setter
    def start_date(self, value: str) -> None:
        self.__start_date = value
        self.save_config()

    @property
    def cd_text_custom(self) -> str:
        return self.__cd_text_custom

    @cd_text_custom.setter
    def cd_text_custom(self, value: str) -> None:
        self.__cd_text_custom = value
        self.save_config()

    @property
    def countdown_date(self) -> Optional[str]:
        return self.__countdown_date

    @countdown_date.setter
    def countdown_date(self, value: Optional[str]) -> None:
        self.__countdown_date = value
        self.save_config()


class AudioConfig:
    __volume: int
    __attend_class: str
    __finish_class: str
    __prepare_class: str

    def __init__(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        self.__volume = config.getint("Audio", "volume", fallback=75)
        self.__attend_class = config.get(
            "Audio", "attend_class", fallback="attend_class.wav"
        )
        self.__finish_class = config.get(
            "Audio", "finish_class", fallback="finish_class.wav"
        )
        self.__prepare_class = config.get(
            "Audio", "prepare_class", fallback="prepare_class.wav"
        )

    def save_config(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        if "Audio" not in config.sections():
            config.add_section("Audio")

        config.set("Audio", "volume", str(self.__volume))
        config.set("Audio", "attend_class", self.__attend_class)
        config.set("Audio", "finish_class", self.__finish_class)
        config.set("Audio", "prepare_class", self.__prepare_class)

        with open(CONFIG_FILE_PATH, "w") as configfile:
            config.write(configfile)

    @property
    def volume(self) -> int:
        return self.__volume

    @volume.setter
    def volume(self, value: int) -> None:
        self.__volume = value
        self.save_config()

    @property
    def attend_class(self) -> str:
        return self.__attend_class

    @attend_class.setter
    def attend_class(self, value: str) -> None:
        self.__attend_class = value
        self.save_config()

    @property
    def finish_class(self) -> str:
        return self.__finish_class

    @finish_class.setter
    def finish_class(self, value: str) -> None:
        self.__finish_class = value
        self.save_config()

    @property
    def prepare_class(self) -> str:
        return self.__prepare_class

    @prepare_class.setter
    def prepare_class(self, value: str) -> None:
        self.__prepare_class = value
        self.save_config()


class TempConfig:
    __set_week: str
    __temp_schedule: str

    def __init__(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        self.__set_week = config.get("Temp", "set_week", fallback="")
        self.__temp_schedule = config.get("Temp", "temp_schedule", fallback="")

    def save_config(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        if "Temp" not in config.sections():
            config.add_section("Temp")

        config.set("Temp", "set_week", self.__set_week)
        config.set("Temp", "temp_schedule", self.__temp_schedule)

        with open(CONFIG_FILE_PATH, "w") as configfile:
            config.write(configfile)

    @property
    def set_week(self) -> str:
        return self.__set_week

    @set_week.setter
    def set_week(self, value: str) -> None:
        self.__set_week = value
        self.save_config()

    @property
    def temp_schedule(self) -> str:
        return self.__temp_schedule

    @temp_schedule.setter
    def temp_schedule(self, value: str) -> None:
        self.__temp_schedule = value
        self.save_config()


class OtherConfig:
    __do_not_log: bool
    __safe_mode: bool
    __initialstartup: bool
    __multiple_programs: bool
    __version_channel: bool
    __auto_check_update: bool
    __version: str

    def __init__(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        self.__do_not_log = config.getboolean("Other", "do_not_log", fallback=False)
        self.__safe_mode = config.getboolean("Other", "safe_mode", fallback=False)
        self.__initialstartup = config.getboolean(
            "Other", "initialstartup", fallback=True
        )
        self.__multiple_programs = config.getboolean(
            "Other", "multiple_programs", fallback=False
        )
        self.__version_channel = config.getboolean(
            "Other", "version_channel", fallback=False
        )
        self.__auto_check_update = config.getboolean(
            "Other", "auto_check_update", fallback=True
        )
        self.__version = config.get("Other", "version", fallback="1.1.7-b5")

    def save_config(self):
        import configparser

        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)

        if "Other" not in config.sections():
            config.add_section("Other")

        config.set("Other", "do_not_log", str(int(self.__do_not_log)))
        config.set("Other", "safe_mode", str(int(self.__safe_mode)))
        config.set("Other", "initialstartup", str(int(self.__initialstartup)))
        config.set("Other", "multiple_programs", str(int(self.__multiple_programs)))
        config.set("Other", "version_channel", str(int(self.__version_channel)))
        config.set("Other", "auto_check_update", str(int(self.__auto_check_update)))
        config.set("Other", "version", self.__version)

        with open(CONFIG_FILE_PATH, "w") as configfile:
            config.write(configfile)

    @property
    def do_not_log(self) -> bool:
        return self.__do_not_log

    @do_not_log.setter
    def do_not_log(self, value: bool) -> None:
        self.__do_not_log = value
        self.save_config()

    @property
    def safe_mode(self) -> bool:
        return self.__safe_mode

    @safe_mode.setter
    def safe_mode(self, value: bool) -> None:
        self.__safe_mode = value
        self.save_config()

    @property
    def initialstartup(self) -> bool:
        return self.__initialstartup

    @initialstartup.setter
    def initialstartup(self, value: bool) -> None:
        self.__initialstartup = value
        self.save_config()

    @property
    def multiple_programs(self) -> bool:
        return self.__multiple_programs

    @multiple_programs.setter
    def multiple_programs(self, value: bool) -> None:
        self.__multiple_programs = value
        self.save_config()

    @property
    def version_channel(self) -> bool:
        return self.__version_channel

    @version_channel.setter
    def version_channel(self, value: bool) -> None:
        self.__version_channel = value
        self.save_config()

    @property
    def auto_check_update(self) -> bool:
        return self.__auto_check_update

    @auto_check_update.setter
    def auto_check_update(self, value: bool) -> None:
        self.__auto_check_update = value
        self.save_config()

    @property
    def version(self) -> str:
        return self.__version

    @version.setter
    def version(self, value: str) -> None:
        self.__version = value
        self.save_config()


general_config = GeneralConfig()
toast_config = ToastConfig()
weather_config = WeatherConfig()
color_config = ColorConfig()
plugin_config = PluginConfig()
date_config = DateConfig()
audio_config = AudioConfig()
temp_config = TempConfig()
other_config = OtherConfig()
