"""Shared usage/temperature thresholds and colors, independent of GUI/Win32."""
import math
import re
from typing import Any
from ping_config import save_settings

LEVELS = ('low', 'warning', 'high')


def validate_limits(values):
    result = {}
    for metric in ('cpu', 'gpu', 'mem'):
        try:
            numbers = tuple(float(v) for v in values[metric])
            low, warning, high = numbers
            if not all(math.isfinite(v) for v in numbers) or not 0 <= low < warning < high <= 100:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ValueError(f'{metric.upper()}: use 0 ≤ Low < Warning < High ≤ 100.') from None
        result[metric] = numbers
    return result


def load_limits(cfg):
    section = cfg['usage_limits'] if cfg.has_section('usage_limits') else {}
    result = dict(DEFAULT_LIMITS)
    for metric, defaults in DEFAULT_LIMITS.items():
        candidate = tuple(section.get(f'{metric}_{level}', str(default))
                          for level, default in zip(LEVELS, defaults))
        try:
            result[metric] = validate_limits(dict(DEFAULT_LIMITS, **{metric: candidate}))[metric]
        except ValueError:
            pass  # Invalid manual edits fall back for this metric only; never rewrite on load.
    return result


def validate_preferences(values) -> dict[str, Any]:
    """Validate a complete snapshot, filling omitted rows/colors with defaults."""
    result: dict[str, Any] = validate_limits(dict(DEFAULT_LIMITS, **{k: v for k, v in values.items() if k in DEFAULT_LIMITS}))
    for metric in DEFAULT_TEMP_LIMITS:
        try:
            numbers = tuple(float(v) for v in values.get(metric, DEFAULT_TEMP_LIMITS[metric]))
            low, warning, high = numbers
            if not all(math.isfinite(v) for v in numbers) or not 0 <= low < warning < high <= 120:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError(f'Temperatura {metric[:3].upper()}: use 0 ≤ Low < Warning < High ≤ 120.') from None
        result[metric] = numbers
    colors = values.get('colors', DEFAULT_COLORS)
    if not isinstance(colors, (tuple, list)) or len(colors) != 3:
        raise ValueError('Cores: informe três cores #rrggbb.')
    for level, color in zip(LEVELS, colors):
        if not isinstance(color, str) or re.fullmatch(r'#[0-9a-fA-F]{6}', color) is None:
            raise ValueError(f'Cor {level}: use #rrggbb.')
    result['colors'] = tuple(colors)
    return result


def load_preferences(cfg) -> dict[str, Any]:
    result: dict[str, Any] = load_limits(cfg)
    section = cfg['usage_limits'] if cfg.has_section('usage_limits') else {}
    for metric in DEFAULT_TEMP_LIMITS:
        candidate = tuple(section.get(f'{metric}_{level}', str(default))
                          for level, default in zip(LEVELS, DEFAULT_TEMP_LIMITS[metric]))
        try:
            result[metric] = validate_preferences({metric: candidate})[metric]
        except ValueError:
            result[metric] = DEFAULT_TEMP_LIMITS[metric]
    colors = []
    for level, default in zip(LEVELS, DEFAULT_COLORS):
        color = section.get(f'{level}_color', default)
        colors.append(color if re.fullmatch(r'#[0-9a-fA-F]{6}', color) else default)
    result['colors'] = tuple(colors)
    return result


def limit_settings(values):
    validated = validate_preferences(values)
    settings = {f'{metric}_{level}': f'{number:g}'
                for metric in values if metric != 'colors'
                for level, number in zip(LEVELS, validated[metric])}
    if 'colors' in values:
        settings.update({f'{level}_color': color for level, color in zip(LEVELS, validated['colors'])})
    return settings


def save_limits(path, values):
    save_settings(path, 'usage_limits', limit_settings(values))


DEFAULT_LIMITS = {name: (50, 75, 90) for name in ('cpu', 'gpu', 'mem')}
DEFAULT_TEMP_LIMITS = {'cpu_temp': (60, 75, 85), 'gpu_temp': (60, 75, 85)}
LOW_COLOR = '#5fb0ff'
WARNING_COLOR = '#ff9d5f'
HIGH_COLOR = '#ff6b6b'
DEFAULT_COLORS = (LOW_COLOR, WARNING_COLOR, HIGH_COLOR)


def color_text_color(background):
    """Choose the higher-contrast text using linear sRGB relative luminance."""
    channels = (int(background[i:i+2], 16) / 255 for i in (1, 3, 5))
    linear = tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                   for c in channels)
    luminance = sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    dark_luminance = ((16 / 255 + 0.055) / 1.055) ** 2.4  # #101010
    dark_contrast = (luminance + 0.05) / (dark_luminance + 0.05)
    light_contrast = 1.05 / (luminance + 0.05)
    return '#101010' if dark_contrast >= light_contrast else '#ffffff'


def usage_color(value, limits, normal, colors=None):
    """Inclusive lower bounds; missing readings keep the normal foreground."""
    if value is not None:
        for threshold, color in reversed(tuple(zip(limits, colors or DEFAULT_COLORS))):
            if value >= threshold:
                return color
    return normal
