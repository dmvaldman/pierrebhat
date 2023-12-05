from typing import Optional

import cv2
import numpy as np

from supervision.draw.color import Color
from supervision.geometry.core import Point, Rect


def draw_line(
    scene: np.ndarray, start: Point, end: Point, color: Color, thickness: int = 2
) -> np.ndarray:
    """
    Draws a line on a given scene.

    Parameters:
        scene (np.ndarray): The scene on which the line will be drawn
        start (Point): The starting point of the line
        end (Point): The end point of the line
        color (Color): The color of the line
        thickness (int): The thickness of the line

    Returns:
        np.ndarray: The scene with the line drawn on it
    """
    cv2.line(
        scene,
        start.as_xy_int_tuple(),
        end.as_xy_int_tuple(),
        color.as_bgr(),
        thickness=thickness,
    )
    return scene


def draw_rectangle(
    scene: np.ndarray, rect: Rect, color: Color, thickness: int = 2
) -> np.ndarray:
    """
    Draws a rectangle on an image.

    Parameters:
        scene (np.ndarray): The scene on which the rectangle will be drawn
        rect (Rect): The rectangle to be drawn
        color (Color): The color of the rectangle
        thickness (int): The thickness of the rectangle border

    Returns:
        np.ndarray: The scene with the rectangle drawn on it
    """
    cv2.rectangle(
        scene,
        rect.top_left.as_xy_int_tuple(),
        rect.bottom_right.as_xy_int_tuple(),
        color.as_bgr(),
        thickness=thickness,
    )
    return scene


def draw_filled_rectangle(scene: np.ndarray, rect: Rect, color: Color) -> np.ndarray:
    """
    Draws a filled rectangle on an image.

    Parameters:
        scene (np.ndarray): The scene on which the rectangle will be drawn
        rect (Rect): The rectangle to be drawn
        color (Color): The color of the rectangle

    Returns:
        np.ndarray: The scene with the rectangle drawn on it
    """
    cv2.rectangle(
        scene,
        rect.top_left.as_xy_int_tuple(),
        rect.bottom_right.as_xy_int_tuple(),
        color.as_bgr(),
        -1,
    )
    return scene


def draw_polygon(
    scene: np.ndarray, polygon: np.ndarray, color: Color, thickness: int = 2
) -> np.ndarray:
    """Draw a polygon on a scene.

    Parameters:
        scene (np.ndarray): The scene to draw the polygon on.
        polygon (np.ndarray): The polygon to be drawn, given as a list of vertices.
        color (Color): The color of the polygon.
        thickness (int, optional): The thickness of the polygon lines, by default 2.

    Returns:
        np.ndarray: The scene with the polygon drawn on it.
    """
    cv2.polylines(
        scene, [polygon], isClosed=True, color=color.as_bgr(), thickness=thickness
    )
    return scene


def draw_image(
    scene: np.ndarray,
    image: Union[str, np.ndarray],
    opacity: float,
    rect: Rect
) -> np.ndarray:
    “““
    Draws an image onto a given scene with specified opacity and dimensions.
    
    Args:
        scene (np.ndarray): The background image onto which the image will be drawn.
        image (Union[str, np.ndarray]): The image to be drawn, can be either a file path or numpy array.
        opacity (float): The opacity level of the image to be drawn, from 0.0 to 1.0.
        rect (Rect): A Rect object specifying the dimensions and position where the image will be drawn.
    
    Returns:
        np.ndarray: The scene with the image drawn onto it.
    
    Example:
        scene = np.zeros((400, 400, 3), dtype=np.uint8)
        image_path = "path/to/image.jpg"
        opacity = 0.5
        rect = Rect(x=50, y=50, width=200, height=200)
        new_scene = draw_image(scene, image_path, opacity, rect)
    ”””
    if isinstance(image, str):
        # Load image from the file path
        watermark = cv2.imread(image, cv2.IMREAD_UNCHANGED)
    elif isinstance(image, np.ndarray):
        # Use the provided image
        watermark = image.copy()
    else:
        raise TypeError("image must be a path string or a numpy array")

    if watermark.shape[2] == 4:
        # Image has alpha channel for transparency
        alpha_mask = watermark[:, :, 3] / 255.0 * opacity
        alpha_background = 1.0 - alpha_mask
    else:
        alpha_mask = np.full_like(watermark[..., :1], fill_value=opacity)
        alpha_background = 1.0 - alpha_mask

    # Resize watermark to fit the rect dimensions
    watermark = cv2.resize(watermark, (rect.width, rect.height))

    # Place watermark image at the specified rect coordinates
    x_start, y_start = rect.top_left.as_xy_int_tuple()
    x_end, y_end = x_start + rect.width, y_start + rect.height

    # Check for image bounds
    x_end = min(x_end, scene.shape[1])
    y_end = min(y_end, scene.shape[0])

    for c in range(0, 3):
        scene[y_start:y_end, x_start:x_end, c] = (
            alpha_mask * watermark[..., c] + alpha_background * scene[y_start:y_end, x_start:x_end, c]
        )
    
    return scene
def draw_text(
    scene: np.ndarray,
    text: str,
    text_anchor: Point,
    text_color: Color = Color.black(),
    text_scale: float = 0.5,
    text_thickness: int = 1,
    text_padding: int = 10,
    text_font: int = cv2.FONT_HERSHEY_SIMPLEX,
    background_color: Optional[Color] = None,
) -> np.ndarray:
    """
    Draw text with background on a scene.

    Parameters:
        scene (np.ndarray): A 2-dimensional numpy ndarray representing an image or scene
        text (str): The text to be drawn.
        text_anchor (Point): The anchor point for the text, represented as a
            Point object with x and y attributes.
        text_color (Color, optional): The color of the text. Defaults to black.
        text_scale (float, optional): The scale of the text. Defaults to 0.5.
        text_thickness (int, optional): The thickness of the text. Defaults to 1.
        text_padding (int, optional): The amount of padding to add around the text
            when drawing a rectangle in the background. Defaults to 10.
        text_font (int, optional): The font to use for the text.
            Defaults to cv2.FONT_HERSHEY_SIMPLEX.
        background_color (Color, optional): The color of the background rectangle,
            if one is to be drawn. Defaults to None.

    Returns:
        np.ndarray: The input scene with the text drawn on it.

    Examples:
        ```python
        >>> scene = np.zeros((100, 100, 3), dtype=np.uint8)
        >>> text_anchor = Point(x=50, y=50)
        >>> scene = draw_text(scene=scene, text="Hello, world!",text_anchor=text_anchor)
        ```
    """
    text_width, text_height = cv2.getTextSize(
        text=text,
        fontFace=text_font,
        fontScale=text_scale,
        thickness=text_thickness,
    )[0]
    text_rect = Rect(
        x=text_anchor.x - text_width // 2,
        y=text_anchor.y - text_height // 2,
        width=text_width,
        height=text_height,
    ).pad(text_padding)

    if background_color is not None:
        scene = draw_filled_rectangle(
            scene=scene, rect=text_rect, color=background_color
        )

    cv2.putText(
        img=scene,
        text=text,
        org=(text_anchor.x - text_width // 2, text_anchor.y + text_height // 2),
        fontFace=text_font,
        fontScale=text_scale,
        color=text_color.as_bgr(),
        thickness=text_thickness,
        lineType=cv2.LINE_AA,
    )
    return scene
