from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Literal, Optional

from pydantic import BaseModel


class ThemeConfig(BaseModel):
    name: str
    support_dark_mode: bool
    default_theme: Optional[Literal["dark", "light"]] = None
    radius: str
    spacing: int
    shadow: bool
    height: int
    widget_width: Dict[str, int]


@dataclass
class ThemeInfo:
    path: Path
    config: ThemeConfig
