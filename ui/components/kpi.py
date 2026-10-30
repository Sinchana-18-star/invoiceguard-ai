"""KPI cards with inline SVG icons (no icon-font or CDN dependency)."""
from __future__ import annotations

from ui.format import esc, render_svg_markup

_ICONS = {
    "inbox": '<path d="M4 13h4l2 3h4l2-3h4M4 13l2-8h12l2 8v6H4z"/>',
    "check": '<path d="M5 12l5 5 9-10"/>',
    "clock": '<circle cx="12" cy="12" r="8"/><path d="M12 8v5l3 2"/>',
    "x": '<path d="M7 7l10 10M17 7L7 17"/>',
    "alert": '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.5"/>',
    "percent": '<path d="M6 18L18 6"/><circle cx="7.5" cy="7.5" r="2"/><circle cx="16.5" cy="16.5" r="2"/>',
}
_TINTS = {"accent": ("#EAF1FA", "#3978C5"), "success": ("#E8F5EE", "#23865B"), "warning": ("#FBF3E4", "#D99A32"),
          "danger": ("#FAECEC", "#CC5151")}


def kpi_card(title: str, value: str, icon: str, tint: str = "accent", foot: str | None = None) -> None:
    bg, fg = _TINTS[tint]
    svg = (f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{fg}" stroke-width="2" '
           f'stroke-linecap="round" stroke-linejoin="round">{_ICONS[icon]}</svg>')
    foot_html = f'<div class="ig-kpi-foot">{esc(foot)}</div>' if foot else ""
    render_svg_markup(f'<div class="ig-kpi"><div class="ig-kpi-head"><span>{esc(title)}</span>'
                      f'<span class="ig-kpi-icon" style="background:{bg}">{svg}</span></div>'
                      f'<div class="ig-kpi-value">{esc(value)}</div>{foot_html}</div>')
