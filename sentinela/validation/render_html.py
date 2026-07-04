"""
Sentinela HL — render do Scientific Validation Report em HTML estático.

Segue o kit de design: dark, indigo como única cor cromática, Inter, densidade
densa (revisão de dados), zero motion, texto em minúscula. Arquivo local — o
Henrique abre no navegador e revisa cada ficha.
"""

from __future__ import annotations

import html
from typing import Any

_BG0, _BG1, _BG2 = "#08090a", "#0f1011", "#191a1b"
_T0, _T1, _T2, _T3 = "#f7f8f8", "#d0d6e0", "#8a8f98", "#62666d"
_INDIGO = "#5e6ad2"
_BORDER, _BORDER2 = "rgba(255,255,255,0.05)", "rgba(255,255,255,0.08)"
_STATUS = {
    "pass": "#4cb782", "flag": "#f2994a", "fail": "#e5484d",
    "escalate": "#f2994a", "reject": "#e5484d", "error": "#e5484d",
}


def _esc(v: Any) -> str:
    return html.escape(str(v)) if v is not None else ""


def _badge(text: str, color: str) -> str:
    return (f'<span style="display:inline-flex;align-items:center;padding:2px 8px;'
            f'border-radius:9999px;font-size:11px;font-weight:510;color:{color};'
            f'border:1px solid {color}55;background:{color}14">{_esc(text)}</span>')


def _chip(text: str) -> str:
    return (f'<span style="display:inline-block;padding:2px 8px;margin:0 4px 4px 0;'
            f'border-radius:6px;font-size:11px;color:{_T2};background:rgba(255,255,255,0.03);'
            f'border:1px solid {_BORDER}">{_esc(text)}</span>')


def _filter_row(c: dict[str, Any]) -> str:
    color = _STATUS.get(c.get("result"), _T2)
    return (
        f'<div style="display:grid;grid-template-columns:160px 70px 1fr;gap:12px;'
        f'padding:8px 0;border-bottom:1px solid {_BORDER}">'
        f'<div style="color:{_T2};font-size:13px">{_esc(c.get("filter"))}</div>'
        f'<div>{_badge(c.get("result",""), color)}</div>'
        f'<div style="color:{_T1};font-size:13px">{_esc(c.get("rationale") or "—")}</div>'
        f'</div>'
    )


def _item_card(item: dict[str, Any]) -> str:
    inp = item.get("input", {})
    out = item.get("output", {})
    claim = inp.get("claim", {})
    src = inp.get("source", {})
    ctx = inp.get("context", {})

    if not out.get("ok"):
        err = out.get("error", {})
        head = (f'<div style="color:{_T0};font-size:15px;font-weight:510">{_esc(claim.get("statement") or "—")}</div>'
                f'<div style="margin-top:8px">{_badge("erro: " + str(err.get("error")), _STATUS["error"])}</div>'
                f'<div style="color:{_T2};font-size:13px;margin-top:6px">{_esc(err.get("message"))}</div>')
        return f'<div style="background:{_BG1};border:1px solid {_BORDER2};border-radius:8px;padding:20px;margin-bottom:16px">{head}</div>'

    report = out.get("report", {})
    decision = report.get("decision", "")
    dcolor = _STATUS.get(decision, _T2)
    filters = "".join(_filter_row(c) for c in report.get("classifications", []))
    kws = "".join(_chip(k) for k in claim.get("keywords", [])) or f'<span style="color:{_T3};font-size:12px">—</span>'
    usage = item.get("usage")
    tokens = f' · {usage.get("total_tokens")} tokens' if isinstance(usage, dict) and usage.get("total_tokens") else ""
    review = ' · <span style="color:#f2994a">requer revisão humana</span>' if report.get("requires_human_review") else ""

    url = src.get("url")
    url_html = (f'<a href="{_esc(url)}" style="color:{_INDIGO};text-decoration:none;font-size:12px">{_esc(url)}</a>'
                if url else f'<span style="color:{_T3};font-size:12px">sem url</span>')

    return f'''<div style="background:{_BG1};border:1px solid {_BORDER2};border-radius:8px;padding:20px;margin-bottom:16px">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px">
    <div style="color:{_T0};font-size:16px;font-weight:510;line-height:1.4;text-wrap:balance">{_esc(claim.get("statement"))}</div>
    <div style="flex-shrink:0">{_badge(decision, dcolor)}</div>
  </div>
  <div style="margin-top:6px">{url_html}</div>

  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0;padding:12px;background:{_BG2};border-radius:6px">
    <div><div style="color:{_T3};font-size:11px">reliability</div><div style="color:{_T1};font-size:13px">{_esc(claim.get("source_reliability"))}</div></div>
    <div><div style="color:{_T3};font-size:11px">category</div><div style="color:{_T1};font-size:13px">{_esc(claim.get("category"))}</div></div>
    <div><div style="color:{_T3};font-size:11px">confidence</div><div style="color:{_T1};font-size:13px">{_esc(claim.get("confidence_score"))}</div></div>
    <div><div style="color:{_T3};font-size:11px">rótulo provisório</div><div style="color:{_T1};font-size:13px">{_esc(claim.get("epistemic_status"))}</div></div>
  </div>

  <div style="color:{_T3};font-size:11px;margin-bottom:6px">keywords</div>
  <div style="margin-bottom:16px">{kws}</div>

  <div style="color:{_T3};font-size:11px;margin-bottom:4px">excerpt da fonte</div>
  <div style="color:{_T2};font-size:13px;line-height:1.5;margin-bottom:16px;padding-left:12px;border-left:2px solid {_BORDER2}">{_esc(src.get("excerpt"))}</div>

  <div style="color:{_T3};font-size:11px;margin-bottom:4px">auditoria dos filtros</div>
  <div>{filters}</div>

  <div style="color:{_T3};font-size:11px;margin-top:12px">
    {_esc(item.get("elapsed_ms"))} ms{tokens}{review} · run_id {_esc((out.get("run_id") or "")[:8])}
  </div>
</div>'''


def render_html(report: dict[str, Any]) -> str:
    s = report.get("summary", {})
    summary_badges = " ".join([
        _badge(f'{s.get("pass",0)} pass', _STATUS["pass"]),
        _badge(f'{s.get("escalate",0)} escalate', _STATUS["escalate"]),
        _badge(f'{s.get("reject",0)} reject', _STATUS["reject"]),
    ] + ([_badge(f'{s.get("error",0)} erro', _STATUS["error"])] if s.get("error") else []))
    cards = "".join(_item_card(i) for i in report.get("items", []))

    return f'''<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>sentinela hl · validation report</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fontsource/inter/index.min.css">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:{_BG0};color:{_T1};font-family:'Inter',system-ui,sans-serif;
       font-feature-settings:'cv01','ss03';line-height:1.5;padding:32px 24px}}
  .wrap{{max-width:1000px;margin:0 auto}}
  a:hover{{text-decoration:underline}}
</style></head><body><div class="wrap">
  <div style="border-bottom:1px solid {_BORDER2};padding-bottom:16px;margin-bottom:24px">
    <div style="font-size:24px;font-weight:590;color:{_T0};letter-spacing:-0.24px">sentinela hl · scientific validation report</div>
    <div style="color:{_T2};font-size:13px;margin-top:8px">
      gerado {_esc(report.get("generated_at"))} · modelo {_esc(report.get("model") or "—")} ·
      fonte {_esc((report.get("source") or {}).get("name"))}
    </div>
    <div style="margin-top:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <span style="color:{_T2};font-size:13px">{_esc(s.get("total",0))} itens · {_esc(s.get("total_ms",0))} ms total</span>
      {summary_badges}
    </div>
  </div>
  {cards}
  <div style="color:{_T3};font-size:11px;text-align:center;margin-top:24px">
    registro completo em validation-*.json · decisão final humana é do curador
  </div>
</div></body></html>'''
