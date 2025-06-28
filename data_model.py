from typing import Optional, Literal
from pydantic import BaseModel
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


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
