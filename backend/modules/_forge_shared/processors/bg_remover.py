"""背景去除處理器。"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from .base import BaseProcessor


class BackgroundRemover(BaseProcessor):
    """移除生成圖背景，優先支援品紅 chroma key 與安全主體分離。"""

    name = "bg_remover"
    label = "去除背景"

    def process(self, image: Image.Image, **kwargs) -> Image.Image:
        source = image.convert("RGBA")
        method = str(kwargs.get("method", "subject"))
        if method in {"magenta", "chroma_key", "chroma-key"}:
            return self._remove_magenta(
                source,
                threshold=int(kwargs.get("threshold", 100)),
                edge_threshold=int(kwargs.get("edge_threshold", 150)),
                shadow_threshold=int(kwargs.get("shadow_threshold", 230)),
                shadow_component_ratio=float(kwargs.get("shadow_component_ratio", 0.06)),
                keep_component_ratio=float(kwargs.get("keep_component_ratio", 0.02)),
            )
        if method == "subject":
            processed = self._subject_separation(source, **kwargs)
            if processed is not None:
                if self._has_magenta_background(source):
                    return self._remove_magenta(
                        processed,
                        threshold=int(kwargs.get("threshold", 100)),
                        edge_threshold=int(kwargs.get("edge_threshold", 150)),
                        shadow_threshold=int(kwargs.get("shadow_threshold", 230)),
                        shadow_component_ratio=float(kwargs.get("shadow_component_ratio", 0.06)),
                        keep_component_ratio=float(kwargs.get("keep_component_ratio", 0.02)),
                    )
                return processed
            if self._has_magenta_background(source):
                return self._remove_magenta(
                    source,
                    threshold=int(kwargs.get("threshold", 100)),
                    edge_threshold=int(kwargs.get("edge_threshold", 150)),
                    shadow_threshold=int(kwargs.get("shadow_threshold", 230)),
                    shadow_component_ratio=float(kwargs.get("shadow_component_ratio", 0.06)),
                    keep_component_ratio=float(kwargs.get("keep_component_ratio", 0.02)),
                )
            method = "flood_fill"
        if method == "flood_fill":
            processed = self._flood_fill(source, **kwargs)
            if processed is not None:
                return processed
        return self._threshold_remove(source, int(kwargs.get("threshold", 245)))

    def _subject_separation(self, image: Image.Image, **kwargs) -> Image.Image | None:
        data = np.array(image, dtype=np.uint8)
        height, width = data.shape[:2]
        if height < 8 or width < 8:
            return None

        existing_alpha = data[:, :, 3] > 0
        rgb = data[:, :, :3]
        background_seed = self._edge_background_mask(
            rgb,
            tolerance=int(kwargs.get("tolerance", 18)),
            seed_count=int(kwargs.get("seed_count", 9)),
        )
        background_seed |= ~existing_alpha
        background_ratio = float(background_seed.sum()) / float(height * width)
        if background_ratio < 0.03:
            return None

        mask = np.full((height, width), cv2.GC_PR_FGD, dtype=np.uint8)
        mask[background_seed] = cv2.GC_BGD

        border_width = max(2, min(height, width) // 32)
        mask[:border_width, :] = cv2.GC_BGD
        mask[-border_width:, :] = cv2.GC_BGD
        mask[:, :border_width] = cv2.GC_BGD
        mask[:, -border_width:] = cv2.GC_BGD

        foreground_seed = self._foreground_seed(background_seed, existing_alpha)
        if foreground_seed is None:
            return None
        mask[foreground_seed] = cv2.GC_FGD

        try:
            bg_model = np.zeros((1, 65), dtype=np.float64)
            fg_model = np.zeros((1, 65), dtype=np.float64)
            cv2.grabCut(
                rgb,
                mask,
                None,
                bg_model,
                fg_model,
                int(kwargs.get("iterations", 3)),
                cv2.GC_INIT_WITH_MASK,
            )
        except cv2.error:
            return None

        foreground = ((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)) & existing_alpha
        foreground = self._clean_foreground(
            foreground,
            min_component_area=int(kwargs.get("min_component_area", 16)),
            keep_ratio=float(kwargs.get("keep_component_ratio", 0.02)),
        )
        foreground_ratio = float(foreground.sum()) / float(height * width)
        min_foreground_ratio = float(kwargs.get("min_foreground_ratio", 0.04))
        if foreground_ratio < min_foreground_ratio or foreground_ratio > 0.95:
            return None

        if bool(kwargs.get("edge_cleanup", True)):
            foreground = self._remove_edge_halo(foreground, rgb)

        result = data.copy()
        result[:, :, 3] = np.where(foreground, result[:, :, 3], 0).astype(np.uint8)
        result[result[:, :, 3] == 0] = [0, 0, 0, 0]
        return Image.fromarray(result, "RGBA")

    @staticmethod
    def _remove_magenta(
        image: Image.Image,
        *,
        threshold: int,
        edge_threshold: int,
        shadow_threshold: int,
        shadow_component_ratio: float,
        keep_component_ratio: float,
    ) -> Image.Image:
        data = np.array(image.convert("RGBA"), dtype=np.uint8)
        rgb = data[:, :, :3].astype(np.int32)
        alpha = data[:, :, 3] > 0
        magenta = np.array([255, 0, 255], dtype=np.int32)
        distance = np.sqrt(np.sum((rgb - magenta) ** 2, axis=2))

        direct_mask = (distance < threshold) & alpha
        data[:, :, 3][direct_mask] = 0

        height, width = data.shape[:2]
        edge_mask = np.zeros((height, width), dtype=np.uint8)
        magenta_shadow = BackgroundRemover._magenta_shadow_mask(
            rgb,
            alpha,
            max_distance=shadow_threshold,
        )
        seed = (
            (distance < edge_threshold)
            | magenta_shadow
            | (data[:, :, 3] == 0)
        ).astype(np.uint8)
        queue = []
        for x in range(width):
            queue.append((x, 0))
            queue.append((x, height - 1))
        for y in range(height):
            queue.append((0, y))
            queue.append((width - 1, y))

        while queue:
            x, y = queue.pop()
            if x < 0 or x >= width or y < 0 or y >= height:
                continue
            if edge_mask[y, x] or not seed[y, x]:
                continue
            edge_mask[y, x] = 1
            queue.extend(
                [
                    (x + 1, y),
                    (x - 1, y),
                    (x, y + 1),
                    (x, y - 1),
                    (x + 1, y + 1),
                    (x - 1, y - 1),
                    (x + 1, y - 1),
                    (x - 1, y + 1),
                ]
            )

        data[:, :, 3][edge_mask > 0] = 0
        data = BackgroundRemover._remove_detached_magenta_artifacts(
            data,
            magenta_shadow,
            max_component_ratio=shadow_component_ratio,
        )
        data = BackgroundRemover._keep_significant_components(
            data,
            keep_ratio=keep_component_ratio,
        )
        data[data[:, :, 3] == 0] = [0, 0, 0, 0]
        return Image.fromarray(data, "RGBA")

    @staticmethod
    def _magenta_shadow_mask(
        rgb: np.ndarray,
        alpha: np.ndarray,
        *,
        max_distance: int,
    ) -> np.ndarray:
        """辨識 AI 常產生的暗品紅背景殘影。"""
        magenta = np.array([255, 0, 255], dtype=np.int32)
        distance = np.sqrt(np.sum((rgb - magenta) ** 2, axis=2))
        red = rgb[:, :, 0]
        green = rgb[:, :, 1]
        blue = rgb[:, :, 2]
        red_blue_min = np.minimum(red, blue)
        return (
            alpha
            & (distance < max_distance)
            & (red_blue_min >= 96)
            & ((red_blue_min - green) >= 45)
            & (np.abs(red - blue) <= 96)
        )

    @staticmethod
    def _remove_detached_magenta_artifacts(
        data: np.ndarray,
        magenta_shadow: np.ndarray,
        *,
        max_component_ratio: float,
    ) -> np.ndarray:
        """移除不屬於主體連通區的品紅陰影殘片。"""
        result = data.copy()
        alpha = result[:, :, 3] > 0
        if not np.any(alpha):
            return result

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
            alpha.astype(np.uint8),
            connectivity=8,
        )
        if num_labels <= 1:
            return result

        areas = stats[1:, cv2.CC_STAT_AREA]
        largest_label = int(np.argmax(areas)) + 1
        max_area = max(16, int(alpha.size * max_component_ratio))
        removable_labels = {
            label_id
            for label_id in range(1, num_labels)
            if label_id != largest_label and int(stats[label_id, cv2.CC_STAT_AREA]) <= max_area
        }
        if not removable_labels:
            return result

        removable = magenta_shadow & np.isin(labels, list(removable_labels))
        result[:, :, 3][removable] = 0
        return result

    @staticmethod
    def _keep_significant_components(data: np.ndarray, *, keep_ratio: float) -> np.ndarray:
        """保留主要主體與足夠大的附屬部件，移除背景碎片。"""
        result = data.copy()
        alpha = result[:, :, 3] > 0
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
            alpha.astype(np.uint8),
            connectivity=8,
        )
        if num_labels <= 2:
            return result

        areas = stats[1:, cv2.CC_STAT_AREA]
        largest_area = int(areas.max())
        area_threshold = max(16, int(largest_area * keep_ratio))
        remove = np.zeros_like(alpha, dtype=bool)
        for label_id in range(1, num_labels):
            if int(stats[label_id, cv2.CC_STAT_AREA]) < area_threshold:
                remove |= labels == label_id
        result[:, :, 3][remove] = 0
        return result

    @staticmethod
    def _has_magenta_background(image: Image.Image) -> bool:
        data = np.array(image.convert("RGBA"), dtype=np.uint8)
        if data.size == 0:
            return False
        rgb = data[:, :, :3].astype(np.int32)
        alpha = data[:, :, 3] > 0
        border = np.zeros(alpha.shape, dtype=bool)
        border[0, :] = True
        border[-1, :] = True
        border[:, 0] = True
        border[:, -1] = True
        edge_alpha = alpha & border
        if not np.any(edge_alpha):
            return False
        magenta = np.array([255, 0, 255], dtype=np.int32)
        distance = np.sqrt(np.sum((rgb - magenta) ** 2, axis=2))
        magenta_edge = (distance < 180) & edge_alpha
        return float(magenta_edge.sum()) / float(edge_alpha.sum()) >= 0.25

    @staticmethod
    def _edge_background_mask(rgb: np.ndarray, *, tolerance: int, seed_count: int) -> np.ndarray:
        height, width = rgb.shape[:2]
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        full_mask = np.zeros((height, width), dtype=np.uint8)
        x_positions = np.linspace(0, width - 1, max(2, seed_count)).astype(int)
        y_positions = np.linspace(0, height - 1, max(2, seed_count)).astype(int)
        seeds = [(int(x), 0) for x in x_positions]
        seeds.extend((int(x), height - 1) for x in x_positions)
        seeds.extend((0, int(y)) for y in y_positions)
        seeds.extend((width - 1, int(y)) for y in y_positions)

        for x, y in seeds:
            mask = np.zeros((height + 2, width + 2), dtype=np.uint8)
            working = lab.copy()
            cv2.floodFill(
                working,
                mask,
                (x, y),
                (0, 0, 0),
                loDiff=(tolerance, tolerance, tolerance),
                upDiff=(tolerance, tolerance, tolerance),
                flags=4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY,
            )
            full_mask |= mask[1:-1, 1:-1]
        return full_mask > 0

    @staticmethod
    def _foreground_seed(
        background_seed: np.ndarray,
        existing_alpha: np.ndarray,
    ) -> np.ndarray | None:
        candidate = (~background_seed & existing_alpha).astype(np.uint8)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(candidate, connectivity=8)
        if num_labels <= 1:
            return None
        largest_label = int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1
        largest = (labels == largest_label).astype(np.uint8)
        kernel = np.ones((3, 3), dtype=np.uint8)
        eroded = cv2.erode(largest, kernel, iterations=1).astype(bool)
        return eroded if np.any(eroded) else largest.astype(bool)

    @staticmethod
    def _clean_foreground(
        foreground: np.ndarray,
        *,
        min_component_area: int,
        keep_ratio: float,
    ) -> np.ndarray:
        mask = foreground.astype(np.uint8)
        kernel = np.ones((3, 3), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if num_labels <= 1:
            return mask.astype(bool)

        areas = stats[1:, cv2.CC_STAT_AREA]
        largest_area = int(areas.max())
        area_threshold = max(min_component_area, int(largest_area * keep_ratio))
        cleaned = np.zeros_like(mask, dtype=bool)
        for label_id in range(1, num_labels):
            if int(stats[label_id, cv2.CC_STAT_AREA]) >= area_threshold:
                cleaned |= labels == label_id
        return cleaned

    @staticmethod
    def _remove_edge_halo(foreground: np.ndarray, rgb: np.ndarray) -> np.ndarray:
        mask = foreground.astype(np.uint8)
        kernel = np.ones((3, 3), dtype=np.uint8)
        edge = (mask > 0) & (cv2.erode(mask, kernel, iterations=1) == 0)
        if not np.any(edge):
            return foreground

        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        halo = edge & (saturation < 32) & (value > 208)
        if not np.any(halo):
            return foreground

        cleaned = foreground.copy()
        cleaned[halo] = False
        return cleaned

    def _flood_fill(self, image: Image.Image, **kwargs) -> Image.Image | None:
        data = np.array(image, dtype=np.uint8)
        height, width = data.shape[:2]
        if height == 0 or width == 0:
            return image

        bgr = cv2.cvtColor(data[:, :, :3], cv2.COLOR_RGB2BGR)
        full_mask = np.zeros((height, width), dtype=np.uint8)
        corner_threshold = int(kwargs.get("corner_threshold", 200))
        tolerance = int(kwargs.get("tolerance", 10))
        corners = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]

        for x, y in corners:
            if float(np.mean(bgr[y, x])) < corner_threshold:
                continue
            mask = np.zeros((height + 2, width + 2), dtype=np.uint8)
            working = bgr.copy()
            cv2.floodFill(
                working,
                mask,
                (x, y),
                (0, 0, 0),
                loDiff=(tolerance, tolerance, tolerance),
                upDiff=(tolerance, tolerance, tolerance),
                flags=4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY,
            )
            full_mask |= mask[1:-1, 1:-1]

        if not np.any(full_mask):
            return None
        data[:, :, 3][full_mask > 0] = 0
        return Image.fromarray(data, "RGBA")

    @staticmethod
    def _threshold_remove(image: Image.Image, threshold: int) -> Image.Image:
        source = image.convert("RGBA")
        data = np.array(source, dtype=np.uint8)
        rgb = data[:, :, :3]
        mask = np.all(rgb >= threshold, axis=2) & (data[:, :, 3] > 0)
        data[:, :, 3][mask] = 0
        return Image.fromarray(data, "RGBA")
