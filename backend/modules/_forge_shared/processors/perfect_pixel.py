"""自動格線偵測的完美像素處理器。"""

from __future__ import annotations

from typing import Literal

import cv2
import numpy as np
from PIL import Image

from .base import BaseProcessor

SampleMethod = Literal["center", "median", "majority"]


class PerfectPixelProcessor(BaseProcessor):
    """以 FFT 偵測像素格線，並用邊緣峰值微調後重新取樣。"""

    name = "perfect_pixel"
    label = "完美像素"

    def process(self, image: Image.Image, **kwargs) -> Image.Image:
        arr = np.array(image.convert("RGBA"), dtype=np.uint8)
        sample_method = self._resolve_sample_method(kwargs.get("sample_method", "center"))
        grid_size = self._resolve_grid_size(kwargs)
        min_size = float(kwargs.get("min_size", 4.0))
        peak_width = int(kwargs.get("peak_width", 6))
        refine_intensity = float(kwargs.get("refine_intensity", 0.25))
        fix_square = bool(kwargs.get("fix_square", True))

        refined = self._get_perfect_pixel(
            arr,
            sample_method=sample_method,
            grid_size=grid_size,
            min_size=min_size,
            peak_width=peak_width,
            refine_intensity=refine_intensity,
            fix_square=fix_square,
        )
        return Image.fromarray(refined, "RGBA")

    @staticmethod
    def _resolve_sample_method(value: object) -> SampleMethod:
        sample_method = str(value or "center").strip().lower()
        if sample_method not in {"center", "median", "majority", "adaptive"}:
            raise ValueError("sample_method 僅支援 center、median、majority")
        return "median" if sample_method == "adaptive" else sample_method  # type: ignore[return-value]

    @staticmethod
    def _resolve_grid_size(kwargs: dict) -> tuple[int, int] | None:
        raw_grid_size = kwargs.get("grid_size")
        if isinstance(raw_grid_size, (list, tuple)) and len(raw_grid_size) == 2:
            grid_w = int(raw_grid_size[0])
            grid_h = int(raw_grid_size[1])
            if grid_w <= 0 or grid_h <= 0:
                raise ValueError("grid_size 必須大於 0")
            return grid_w, grid_h

        value = kwargs.get("target_size", "none")
        if value in (None, "", "none", "original", "keep", 0, "0"):
            return None
        target_size = int(value)
        if target_size not in {16, 32, 64, 128}:
            raise ValueError("target_size 僅支援 none、16、32、64、128")
        return target_size, target_size

    def _get_perfect_pixel(
        self,
        image: np.ndarray,
        *,
        sample_method: SampleMethod,
        grid_size: tuple[int, int] | None,
        min_size: float,
        peak_width: int,
        refine_intensity: float,
        fix_square: bool,
    ) -> np.ndarray:
        if grid_size is None:
            detected = self._detect_grid_scale(image, peak_width=peak_width, min_size=min_size)
            if detected is None:
                return self._normalize_alpha(image)
            grid_size = detected

        grid_w, grid_h = grid_size
        x_coords, y_coords = self._refine_grids(image, grid_w, grid_h, refine_intensity)
        if len(x_coords) < 2 or len(y_coords) < 2:
            return self._normalize_alpha(image)

        if sample_method == "majority":
            refined = self._sample_majority(image, x_coords, y_coords)
        elif sample_method == "median":
            refined = self._sample_median(image, x_coords, y_coords)
        else:
            refined = self._sample_center(image, x_coords, y_coords)

        if fix_square:
            refined = self._fix_almost_square(refined)
        return self._normalize_alpha(refined)

    @classmethod
    def _detect_grid_scale(
        cls,
        image: np.ndarray,
        *,
        peak_width: int,
        min_size: float,
        max_ratio: float = 1.5,
    ) -> tuple[int, int] | None:
        gray = cls._rgb_to_gray(image)
        height, width = gray.shape
        detected = cls._estimate_grid_fft(gray, peak_width=peak_width)
        if detected is None:
            detected = cls._estimate_grid_gradient(gray)

        if detected is None:
            return None

        grid_w, grid_h = detected
        pixel_size_x = width / grid_w
        pixel_size_y = height / grid_h
        max_pixel_size = 20.0
        invalid_pixel_size = min(pixel_size_x, pixel_size_y) < min_size or max(
            pixel_size_x, pixel_size_y
        ) > max_pixel_size
        invalid_ratio = (
            pixel_size_x / pixel_size_y > max_ratio or pixel_size_y / pixel_size_x > max_ratio
        )
        if invalid_pixel_size or invalid_ratio:
            detected = cls._estimate_grid_gradient(gray)
            if detected is None:
                return None
            grid_w, grid_h = detected
            pixel_size_x = width / grid_w
            pixel_size_y = height / grid_h

        if pixel_size_x / pixel_size_y > max_ratio or pixel_size_y / pixel_size_x > max_ratio:
            pixel_size = min(pixel_size_x, pixel_size_y)
        else:
            pixel_size = (pixel_size_x + pixel_size_y) / 2.0

        return max(1, int(round(width / pixel_size))), max(1, int(round(height / pixel_size)))

    @classmethod
    def _estimate_grid_fft(cls, gray: np.ndarray, *, peak_width: int) -> tuple[int, int] | None:
        height, width = gray.shape
        magnitude = cls._compute_fft_magnitude(gray)
        row_band = width // 2
        col_band = height // 2
        row_sum = np.sum(magnitude[:, width // 2 - row_band : width // 2 + row_band], axis=1)
        col_sum = np.sum(magnitude[height // 2 - col_band : height // 2 + col_band, :], axis=0)
        row_sum = cls._smooth_1d(cls._normalize_minmax(row_sum), k=17)
        col_sum = cls._smooth_1d(cls._normalize_minmax(col_sum), k=17)
        scale_row = cls._detect_peak(row_sum, peak_width=peak_width)
        scale_col = cls._detect_peak(col_sum, peak_width=peak_width)
        if scale_row is None or scale_col is None or scale_col <= 0 or scale_row <= 0:
            return None
        return int(round(scale_col)), int(round(scale_row))

    @classmethod
    def _estimate_grid_gradient(
        cls,
        gray: np.ndarray,
        rel_thr: float = 0.2,
    ) -> tuple[int, int] | None:
        height, width = gray.shape
        grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        grad_x_sum = np.sum(np.abs(grad_x), axis=0).reshape(-1)
        grad_y_sum = np.sum(np.abs(grad_y), axis=1).reshape(-1)
        peaks_x = cls._local_gradient_peaks(grad_x_sum, rel_thr)
        peaks_y = cls._local_gradient_peaks(grad_y_sum, rel_thr)
        if len(peaks_x) < 4 or len(peaks_y) < 4:
            return None
        intervals_x = np.diff(peaks_x)
        intervals_y = np.diff(peaks_y)
        grid_w = int(round(width / np.median(intervals_x)))
        grid_h = int(round(height / np.median(intervals_y)))
        return grid_w, grid_h

    @staticmethod
    def _local_gradient_peaks(values: np.ndarray, rel_thr: float) -> list[int]:
        threshold = float(rel_thr) * float(values.max())
        peaks: list[int] = []
        min_interval = 4
        for index in range(1, len(values) - 1):
            is_peak = values[index] > values[index - 1] and values[index] > values[index + 1]
            if not is_peak or values[index] < threshold:
                continue
            if not peaks or index - peaks[-1] >= min_interval:
                peaks.append(index)
        return peaks

    @classmethod
    def _refine_grids(
        cls,
        image: np.ndarray,
        grid_w: int,
        grid_h: int,
        refine_intensity: float,
    ) -> tuple[list[int], list[int]]:
        height, width = image.shape[:2]
        cell_w = width / grid_w
        cell_h = height / grid_h
        gray = cls._rgb_to_gray(image)
        grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        grad_x_sum = np.sum(np.abs(grad_x), axis=0).reshape(-1)
        grad_y_sum = np.sum(np.abs(grad_y), axis=1).reshape(-1)
        return (
            cls._refine_axis(width, cell_w, grad_x_sum, refine_intensity),
            cls._refine_axis(height, cell_h, grad_y_sum, refine_intensity),
        )

    @classmethod
    def _refine_axis(
        cls,
        length: int,
        cell_size: float,
        gradient_sum: np.ndarray,
        refine_intensity: float,
    ) -> list[int]:
        coords = []
        center = cls._find_best_grid(length / 2, cell_size, cell_size, gradient_sum)

        coord = center
        while coord < length + cell_size / 2:
            coord = cls._find_best_grid(
                coord,
                cell_size * refine_intensity,
                cell_size * refine_intensity,
                gradient_sum,
            )
            coords.append(coord)
            coord += cell_size

        coord = center - cell_size
        while coord > -cell_size / 2:
            coord = cls._find_best_grid(
                coord,
                cell_size * refine_intensity,
                cell_size * refine_intensity,
                gradient_sum,
            )
            coords.append(coord)
            coord -= cell_size

        return sorted({int(np.clip(round(value), 0, length)) for value in coords})

    @staticmethod
    def _find_best_grid(
        origin: float,
        range_val_min: float,
        range_val_max: float,
        gradient_sum: np.ndarray,
        threshold: float = 0.0,
    ) -> int:
        best = round(origin)
        max_value = float(np.max(gradient_sum))
        if max_value < 1e-6:
            return best
        relative_threshold = max_value * threshold
        peaks = []
        for offset in range(-round(range_val_min), round(range_val_max) + 1):
            candidate = round(origin + offset)
            if candidate <= 0 or candidate >= len(gradient_sum) - 1:
                continue
            is_peak = (
                gradient_sum[candidate] > gradient_sum[candidate - 1]
                and gradient_sum[candidate] > gradient_sum[candidate + 1]
            )
            if is_peak and gradient_sum[candidate] >= relative_threshold:
                peaks.append((gradient_sum[candidate], candidate))
        if not peaks:
            return best
        peaks.sort(key=lambda item: item[0], reverse=True)
        return int(peaks[0][1])

    @staticmethod
    def _sample_center(image: np.ndarray, x_coords: list[int], y_coords: list[int]) -> np.ndarray:
        x = np.asarray(x_coords)
        y = np.asarray(y_coords)
        centers_x = np.clip((x[1:] + x[:-1]) * 0.5, 0, image.shape[1] - 1).astype(np.int32)
        centers_y = np.clip((y[1:] + y[:-1]) * 0.5, 0, image.shape[0] - 1).astype(np.int32)
        return image[centers_y[:, None], centers_x[None, :]]

    @staticmethod
    def _sample_median(image: np.ndarray, x_coords: list[int], y_coords: list[int]) -> np.ndarray:
        return PerfectPixelProcessor._sample_cells(image, x_coords, y_coords, method="median")

    @staticmethod
    def _sample_majority(image: np.ndarray, x_coords: list[int], y_coords: list[int]) -> np.ndarray:
        return PerfectPixelProcessor._sample_cells(image, x_coords, y_coords, method="majority")

    @staticmethod
    def _sample_cells(
        image: np.ndarray,
        x_coords: list[int],
        y_coords: list[int],
        *,
        method: SampleMethod,
    ) -> np.ndarray:
        height, width = image.shape[:2]
        out = np.empty((len(y_coords) - 1, len(x_coords) - 1, image.shape[2]), dtype=np.float32)
        for y_index in range(len(y_coords) - 1):
            y0 = int(np.clip(y_coords[y_index], 0, height))
            y1 = int(np.clip(y_coords[y_index + 1], 0, height))
            if y1 <= y0:
                y1 = min(y0 + 1, height)
            for x_index in range(len(x_coords) - 1):
                x0 = int(np.clip(x_coords[x_index], 0, width))
                x1 = int(np.clip(x_coords[x_index + 1], 0, width))
                if x1 <= x0:
                    x1 = min(x0 + 1, width)
                cell = image[y0:y1, x0:x1].reshape(-1, image.shape[2]).astype(np.float32)
                out[y_index, x_index] = PerfectPixelProcessor._sample_cell(cell, method)
        return np.clip(np.rint(out), 0, 255).astype(np.uint8)

    @staticmethod
    def _sample_cell(cell: np.ndarray, method: SampleMethod) -> np.ndarray:
        if cell.size == 0:
            return np.zeros((4,), dtype=np.float32)
        if method == "median":
            return np.median(cell, axis=0)

        max_samples = 128
        if cell.shape[0] > max_samples:
            indices = np.linspace(0, cell.shape[0] - 1, max_samples, dtype=np.int32)
            cell = cell[indices]
        color_a = cell[0]
        color_b = cell[np.argmax(np.sum((cell - color_a) ** 2, axis=1))]
        labels = np.zeros((cell.shape[0],), dtype=bool)
        for _ in range(6):
            dist_a = np.sum((cell - color_a) ** 2, axis=1)
            dist_b = np.sum((cell - color_b) ** 2, axis=1)
            labels = dist_b < dist_a
            if np.any(~labels):
                color_a = cell[~labels].mean(axis=0)
            if np.any(labels):
                color_b = cell[labels].mean(axis=0)
        return color_b if int(labels.sum()) >= int((~labels).sum()) else color_a

    @staticmethod
    def _fix_almost_square(image: np.ndarray) -> np.ndarray:
        height, width = image.shape[:2]
        if abs(width - height) != 1:
            return image
        if width > height:
            if width % 2 == 1:
                return image[:, :-1]
            return np.concatenate([image[:1, :], image], axis=0)
        if height % 2 == 1:
            return image[:-1, :]
        return np.concatenate([image[:, :1], image], axis=1)

    @staticmethod
    def _compute_fft_magnitude(gray_image: np.ndarray) -> np.ndarray:
        transformed = np.fft.fftshift(np.fft.fft2(gray_image.astype(np.float32)))
        magnitude = 1 - np.log1p(np.abs(transformed))
        return PerfectPixelProcessor._normalize_minmax(magnitude)

    @staticmethod
    def _detect_peak(
        projection: np.ndarray,
        *,
        peak_width: int,
        rel_thr: float = 0.35,
        min_dist: int = 6,
    ) -> float | None:
        center = len(projection) // 2
        max_value = float(projection.max())
        if max_value < 1e-6:
            return None
        threshold = max_value * rel_thr
        candidates = []
        for index in range(1, len(projection) - 1):
            is_peak = True
            for offset in range(1, peak_width):
                if index - offset < 0 or index + offset >= len(projection):
                    continue
                left_keeps_climbing = projection[index - offset + 1] >= projection[index - offset]
                right_keeps_climbing = projection[index + offset - 1] >= projection[index + offset]
                if not left_keeps_climbing or not right_keeps_climbing:
                    is_peak = False
                    break
            if is_peak and projection[index] >= threshold:
                left_climb = 0.0
                for cursor in range(index, 0, -1):
                    if projection[cursor] > projection[cursor - 1]:
                        left_climb = abs(float(projection[index] - projection[cursor - 1]))
                    else:
                        break
                right_fall = 0.0
                for cursor in range(index, len(projection) - 1):
                    if projection[cursor] > projection[cursor + 1]:
                        right_fall = abs(float(projection[index] - projection[cursor + 1]))
                    else:
                        break
                candidates.append(
                    {
                        "index": index,
                        "score": max(left_climb, right_fall),
                    }
                )
        left = [
            item
            for item in candidates
            if item["index"] < center - min_dist and item["index"] > center * 0.25
        ]
        right = [
            item
            for item in candidates
            if item["index"] > center + min_dist and item["index"] < center * 1.75
        ]
        if not left or not right:
            return None
        left.sort(key=lambda item: item["score"], reverse=True)
        right.sort(key=lambda item: item["score"], reverse=True)
        return abs(right[0]["index"] - left[0]["index"]) / 2

    @staticmethod
    def _smooth_1d(values: np.ndarray, k: int = 17) -> np.ndarray:
        if k < 3:
            return values
        if k % 2 == 0:
            k += 1
        sigma = k / 6.0
        x = np.arange(k) - k // 2
        kernel = np.exp(-(x * x) / (2 * sigma * sigma))
        kernel = kernel / (kernel.sum() + 1e-8)
        return np.convolve(values, kernel, mode="same")

    @staticmethod
    def _normalize_minmax(values: np.ndarray) -> np.ndarray:
        values = values.astype(np.float32, copy=False)
        min_value = float(values.min())
        max_value = float(values.max())
        if max_value - min_value < 1e-8:
            return np.zeros_like(values, dtype=np.float32)
        return ((values - min_value) / (max_value - min_value)).astype(np.float32)

    @staticmethod
    def _rgb_to_gray(image: np.ndarray) -> np.ndarray:
        rgb = image[:, :, :3].astype(np.float32)
        alpha = image[:, :, 3:4].astype(np.float32) / 255.0 if image.shape[2] == 4 else 1.0
        composited = rgb * alpha
        return (
            0.299 * composited[:, :, 0]
            + 0.587 * composited[:, :, 1]
            + 0.114 * composited[:, :, 2]
        ).astype(np.float32)

    @staticmethod
    def _normalize_alpha(arr: np.ndarray) -> np.ndarray:
        result = arr.copy()
        if result.shape[2] == 3:
            alpha = np.full(result.shape[:2] + (1,), 255, dtype=np.uint8)
            result = np.concatenate([result, alpha], axis=2)
        alpha_mask = result[:, :, 3] >= 128
        result[:, :, 3] = np.where(alpha_mask, 255, 0).astype(np.uint8)
        result[~alpha_mask] = [0, 0, 0, 0]
        return result.astype(np.uint8)
