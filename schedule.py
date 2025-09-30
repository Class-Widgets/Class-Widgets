from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Union, Tuple

class ScheduleManager(ABC):
    def __init__(self, api_name:str, file_path:Path):
        self.api_name = api_name
        self.file_path = file_path

    @abstractmethod
    def get_current_lesson(self) -> str:
        pass # noqa

    @abstractmethod
    def get_next_lessons(self) -> List[str]:
        pass # noqa

    @abstractmethod
    def get_status_with_time(self) -> Tuple[str, float]:
        pass # noqa