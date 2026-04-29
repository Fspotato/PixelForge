"""像素色彩處理工具。"""

from __future__ import annotations

import math

import cv2
import numpy as np


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    """將 HEX 色碼轉為 RGB。"""
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"不支援的 HEX 色碼: {value}")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def hex_to_rgb_array(colors: list[str]) -> np.ndarray:
    """將 HEX 色碼清單轉為 RGB 陣列。"""
    return np.array([hex_to_rgb(color) for color in colors], dtype=np.uint8)


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """將 RGB uint8 陣列轉為 Lab float32。"""
    shaped = np.asarray(rgb, dtype=np.uint8)
    original_shape = shaped.shape
    flat = shaped.reshape(-1, 1, 3)
    lab = cv2.cvtColor(flat, cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32)
    return lab.reshape(*original_shape[:-1], 3)


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """將 Lab 陣列轉為 RGB uint8。"""
    shaped = np.asarray(lab, dtype=np.float32)
    original_shape = shaped.shape
    flat = np.clip(shaped.reshape(-1, 1, 3), 0, 255).astype(np.uint8)
    rgb = cv2.cvtColor(flat, cv2.COLOR_LAB2RGB).reshape(-1, 3)
    return rgb.reshape(*original_shape[:-1], 3)


def nearest_palette_indices(pixels_lab: np.ndarray, palette_lab: np.ndarray) -> np.ndarray:
    """回傳每個像素最接近的色盤索引。"""
    diff = pixels_lab[:, np.newaxis, :] - palette_lab[np.newaxis, :, :]
    distances = np.sum(diff * diff, axis=2)
    return distances.argmin(axis=1)


def variance_quantize(points_lab: np.ndarray, n_colors: int) -> np.ndarray:
    """以方差切分法產生代表色盤。"""
    if len(points_lab) == 0:
        return np.empty((0, 3), dtype=np.float32)

    boxes = [points_lab]
    while len(boxes) < n_colors:
        best_idx = -1
        best_score = -1.0
        for idx, box in enumerate(boxes):
            if len(box) <= 1:
                continue
            score = float(np.sum(np.var(box, axis=0)) * len(box))
            if score > best_score:
                best_idx = idx
                best_score = score
        if best_idx < 0:
            break

        box = boxes.pop(best_idx)
        axis = int(np.argmax(np.var(box, axis=0)))
        order = np.argsort(box[:, axis])
        midpoint = len(order) // 2
        left = box[order[:midpoint]]
        right = box[order[midpoint:]]
        if len(left) == 0 or len(right) == 0:
            boxes.append(box)
            break
        boxes.extend([left, right])

    return np.array([box.mean(axis=0) for box in boxes if len(box)], dtype=np.float32)[:n_colors]


def edge_mask(rgb: np.ndarray, threshold: float = 30.0) -> np.ndarray:
    """以 RGB L1 距離建立邊緣遮罩。"""
    source = rgb.astype(np.float32)
    dx = np.zeros(source.shape[:2], dtype=np.float32)
    dy = np.zeros(source.shape[:2], dtype=np.float32)
    dx[:, :-1] = np.abs(source[:, 1:] - source[:, :-1]).sum(axis=2)
    dy[:-1, :] = np.abs(source[1:] - source[:-1]).sum(axis=2)
    return (dx + dy) > threshold


def atkinson_dither(
    rgb: np.ndarray,
    palette_rgb: np.ndarray,
    *,
    edges: np.ndarray | None = None,
    strength: float = 0.55,
    dither_threshold: float = 8.0,
) -> np.ndarray:
    """套用邊緣感知 Atkinson dithering。"""
    height, width = rgb.shape[:2]
    working = rgb.astype(np.float32).copy()
    palette = palette_rgb.astype(np.float32)
    output = np.zeros((height, width, 3), dtype=np.uint8)
    edge_values = edges if edges is not None else np.zeros((height, width), dtype=bool)

    for y in range(height):
        for x in range(width):
            old = working[y, x]
            distances = np.sum((palette - old) ** 2, axis=1)
            idx = int(np.argmin(distances))
            new = palette[idx]
            output[y, x] = np.clip(new + 0.5, 0, 255).astype(np.uint8)
            if edge_values[y, x] or math.sqrt(float(distances[idx])) <= dither_threshold:
                continue

            error = (old - new) * (strength / 8.0)
            if x + 1 < width:
                working[y, x + 1] += error
            if x + 2 < width:
                working[y, x + 2] += error
            if y + 1 < height:
                if x - 1 >= 0:
                    working[y + 1, x - 1] += error
                working[y + 1, x] += error
                if x + 1 < width:
                    working[y + 1, x + 1] += error
            if y + 2 < height:
                working[y + 2, x] += error

    return output


def map_to_palette(
    rgb: np.ndarray,
    palette_hex: list[str],
    *,
    dither: bool = True,
    dither_strength: float = 0.55,
    edge_threshold: float = 30.0,
) -> np.ndarray:
    """將 RGB 圖像映射到指定 HEX 色盤。"""
    palette_rgb = hex_to_rgb_array(palette_hex)
    palette_lab = rgb_to_lab(palette_rgb)
    if dither:
        return atkinson_dither(
            rgb,
            palette_rgb,
            edges=edge_mask(rgb, edge_threshold),
            strength=dither_strength,
        )

    flat_lab = rgb_to_lab(rgb).reshape(-1, 3)
    indices = nearest_palette_indices(flat_lab, palette_lab)
    return palette_rgb[indices].reshape(rgb.shape)
