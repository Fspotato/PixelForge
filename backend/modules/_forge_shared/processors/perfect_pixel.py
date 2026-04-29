"""像素網格修正處理器。"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from .base import BaseProcessor


class PerfectPixelProcessor(BaseProcessor):
    """重取樣到穩定像素網格並清理離群像素。"""

    name = "perfect_pixel"
    label = "像素修正"

    def process(self, image: Image.Image, **kwargs) -> Image.Image:
        source = image.convert("RGBA")
        arr = np.array(source, dtype=np.uint8)
        arr = self._normalize_alpha(arr)

        sample_method = str(kwargs.get("sample_method", "adaptive"))
        target_size = self._resolve_target_size(kwargs)
        if target_size and max(source.size) > target_size:
            arr = self._resample_to_grid(
                arr,
                target_size=target_size,
                sample_method=sample_method,
            )

        if bool(kwargs.get("remove_outliers", True)):
            arr = self._remove_outliers(
                arr,
                min_neighbors=int(kwargs.get("outlier_neighbors", 2)),
                color_threshold=float(kwargs.get("outlier_color_thr", 50.0)),
                min_cluster=int(kwargs.get("outlier_min_cluster", 8)),
            )

        return Image.fromarray(arr, "RGBA")

    @staticmethod
    def _resolve_target_size(kwargs: dict) -> int | None:
        value = kwargs.get("target_size", kwargs.get("grid_size", "none"))
        if value in (None, "", "none", "original", "keep", 0, "0"):
            return None
        target_size = int(value)
        if target_size not in {16, 32, 64, 128}:
            raise ValueError("target_size 僅支援 none、16、32、64、128")
        return target_size

    @staticmethod
    def _normalize_alpha(arr: np.ndarray) -> np.ndarray:
        result = arr.copy()
        alpha = result[:, :, 3]
        result[:, :, 3] = np.where(alpha >= 128, 255, 0).astype(np.uint8)
        result[result[:, :, 3] == 0] = [0, 0, 0, 0]
        return result

    def _resample_to_grid(
        self,
        arr: np.ndarray,
        *,
        target_size: int,
        sample_method: str,
    ) -> np.ndarray:
        alpha = arr[:, :, 3]
        bbox = self._alpha_bbox(alpha)
        if bbox is None:
            return arr

        left, top, right, bottom = bbox
        cropped = arr[top:bottom, left:right]
        height, width = cropped.shape[:2]
        if width == 0 or height == 0:
            return arr

        scale = target_size / max(width, height)
        target_w = max(1, round(width * scale))
        target_h = max(1, round(height * scale))
        sampled = self._block_sample(cropped, target_w, target_h, sample_method)

        canvas = np.zeros((target_size, target_size, 4), dtype=np.uint8)
        offset_x = (target_size - target_w) // 2
        offset_y = (target_size - target_h) // 2
        canvas[offset_y : offset_y + target_h, offset_x : offset_x + target_w] = sampled
        return canvas

    @staticmethod
    def _alpha_bbox(alpha: np.ndarray) -> tuple[int, int, int, int] | None:
        points = np.argwhere(alpha > 0)
        if len(points) == 0:
            return None
        top, left = points.min(axis=0)
        bottom, right = points.max(axis=0) + 1
        return int(left), int(top), int(right), int(bottom)

    def _block_sample(
        self,
        arr: np.ndarray,
        target_w: int,
        target_h: int,
        sample_method: str,
    ) -> np.ndarray:
        if sample_method == "center":
            return np.array(
                Image.fromarray(arr, "RGBA").resize((target_w, target_h), Image.Resampling.NEAREST),
                dtype=np.uint8,
            )

        height, width = arr.shape[:2]
        result = np.zeros((target_h, target_w, 4), dtype=np.uint8)
        for y in range(target_h):
            y0 = int(y * height / target_h)
            y1 = max(y0 + 1, int((y + 1) * height / target_h))
            for x in range(target_w):
                x0 = int(x * width / target_w)
                x1 = max(x0 + 1, int((x + 1) * width / target_w))
                block = arr[y0:y1, x0:x1]
                result[y, x] = self._sample_block(block, sample_method)
        return result

    @staticmethod
    def _sample_block(block: np.ndarray, sample_method: str) -> np.ndarray:
        pixels = block.reshape(-1, 4)
        opaque = pixels[pixels[:, 3] >= 128]
        if len(opaque) == 0:
            return np.array([0, 0, 0, 0], dtype=np.uint8)
        if sample_method == "median":
            rgb = np.median(opaque[:, :3], axis=0)
        elif sample_method == "majority":
            colors, counts = np.unique(opaque[:, :3], axis=0, return_counts=True)
            rgb = colors[int(np.argmax(counts))]
        else:
            variances = np.var(opaque[:, :3].astype(np.float32), axis=0)
            if float(np.sum(variances)) > 400.0:
                colors, counts = np.unique(opaque[:, :3], axis=0, return_counts=True)
                rgb = colors[int(np.argmax(counts))]
            else:
                rgb = np.median(opaque[:, :3], axis=0)
        return np.array([*np.clip(rgb, 0, 255).astype(np.uint8), 255], dtype=np.uint8)

    @staticmethod
    def _remove_outliers(
        arr: np.ndarray,
        *,
        min_neighbors: int,
        color_threshold: float,
        min_cluster: int,
    ) -> np.ndarray:
        result = arr.copy()
        alpha = result[:, :, 3]
        opaque = (alpha >= 128).astype(np.uint8)
        if int(opaque.sum()) == 0:
            return result

        kernel = np.ones((3, 3), dtype=np.float32)
        kernel[1, 1] = 0
        neighbor_count = cv2.filter2D(opaque.astype(np.float32), -1, kernel)
        isolated = (opaque > 0) & (neighbor_count < 0.5)
        result[isolated, 3] = 0

        needs_check = (result[:, :, 3] >= 128) & (neighbor_count < min_neighbors + 0.5)
        coords = np.argwhere(needs_check)
        rgb = result[:, :, :3].astype(np.float32)
        for y, x in coords:
            y0, y1 = max(0, y - 1), min(result.shape[0], y + 2)
            x0, x1 = max(0, x - 1), min(result.shape[1], x + 2)
            neighbors = result[y0:y1, x0:x1]
            neighbor_rgb = neighbors[neighbors[:, :, 3] >= 128][:, :3].astype(np.float32)
            if len(neighbor_rgb) <= 1:
                result[y, x, 3] = 0
                continue
            distances = np.sqrt(np.sum((neighbor_rgb - rgb[y, x]) ** 2, axis=1))
            if not np.any(distances < color_threshold):
                result[y, x, 3] = 0

        alpha_mask = (result[:, :, 3] >= 128).astype(np.uint8)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(alpha_mask, connectivity=8)
        if num_labels <= 2:
            return result
        areas = stats[1:, cv2.CC_STAT_AREA]
        largest_label = int(np.argmax(areas)) + 1
        largest_area = int(areas[largest_label - 1])
        threshold = max(min_cluster, int(largest_area * 0.05))
        for label_id in range(1, num_labels):
            if label_id != largest_label and stats[label_id, cv2.CC_STAT_AREA] < threshold:
                result[labels == label_id, 3] = 0
        result[result[:, :, 3] == 0] = [0, 0, 0, 0]
        return result
