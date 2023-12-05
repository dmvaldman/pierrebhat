from abc import ABC, abstractmethod

import numpy as np

from supervision.detection.core import Detections


class BaseAnnotator(ABC):
    @abstractmethod
    def annotate(self, scene: np.ndarray, detections: Detections) -> np.ndarray:
        pass


from typing import Union
from supervision.draw.color import Color, ColorPalette

class BoxMaskAnnotator(BaseAnnotator):

    def __init__(
        self,
        color: Union[Color, ColorPalette] = ColorPalette.default(),
        color_map: str = "class",
    ):
        self.color = color
        self.color_map = color_map
        self.color_strategy = {
            "index": self._color_map_by_index,
            "class": self._color_map_by_class,
            "track": self._color_map_by_track,
        }.get(color_map, self._color_map_by_class)  # Default to color_map by class

    def annotate(
        self,
        scene: np.ndarray,
        detections: Detections,
    ) -> np.ndarray:
        # Annotation logic will be implemented here
        pass

    def _color_map_by_index(self, index: int) -> Color:
        return self.color[index % len(self.color)]

    def _color_map_by_class(self, class_id: int) -> Color:
        return self.color[class_id % len(self.color)]

    def _color_map_by_track(self, track_id: int) -> Color:
        return self.color[track_id % len(self.color)]