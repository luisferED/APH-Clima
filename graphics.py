from datetime import date
from html import escape


def icon(code):
    kind = 'sunny' if code == 0 else 'partly' if code in (1, 2) else 'storm' if code >= 95 else 'snow' if code in (71, 73, 75) else 'rain' if code >= 51 else 'cloudy'
    return f'<div class="wx {kind}" aria-label="{kind}"><i class="sun"></i><i class="cloud"></i><div class="drops"><b></b><b></b><b></b><b></b><b></b></div><i class="bolt"></i></div>'


def render_weather(data, days, view):
    if not data:
        content = ''
        city = ''
    else:
        city = escape(data['city_name'].title())
        if view == 'extended':
            names = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
            cards = ''.join(f'<article class="forecast"><header>{names[date.fromisoformat(d["date"]).weekday()]}<small>{date.fromisoformat(d["date"]).strftime("%d/%m")}</small></header>{icon(d["code"])}<strong>{round(d["max"])}°</strong><footer>{round(d["min"])}°<small>Mín.</small></footer></article>' for d in days)
            content = f'<section class="forecast-row">{cards}</section>' if len(days) == 4 else '<div class="missing">Actualiza la base local para cargar el extendido.</div>'
        else:
            content = f'<section class="daily-board"><article class="now"><header>Actual</header>{icon(data["current_code"])}<strong>{round(data["current_temperature"])}°</strong></article><article class="extreme"><strong>{round(data["today_min"])}°</strong>{icon(data["today_code"])}<footer>Mínima</footer></article><article class="extreme"><strong>{round(data["today_max"])}°</strong>{icon(data["today_code"])}<footer>Máxima</footer></article></section>'
    return f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/graphics.css"></head><body><main class="canvas"><div class="climate-heading"><b>CLIMA</b><span><i></i>{city}</span></div>{content}</main><script>function fit(){{document.querySelector(".canvas").style.transform="translate(-50%,-50%) scale("+Math.min(innerWidth/1920,innerHeight/1080)+")";}}onresize=fit;fit();</script></body></html>'
