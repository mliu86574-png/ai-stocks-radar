"""Render the bilingual AI stocks radar (docs/index.html) with ECharts."""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

import pandas as pd

ECHARTS = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"
CSS = (Path(__file__).with_name("style.css")).read_text(encoding="utf-8")


def L(en: str, zh: str) -> str:
    return f'<span lang="en">{html.escape(en)}</span><span lang="zh">{html.escape(zh)}</span>'


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def num(x, dp=2, prefix="") -> str:
    return f"{prefix}{x:,.{dp}f}" if _ok(x) else '<span class="na">–</span>'


def pct(x, dp=1) -> str:
    if not _ok(x):
        return '<span class="na">–</span>'
    cls = "pos" if x > 0 else "neg" if x < 0 else ""
    return f'<span class="{cls}">{x:+.{dp}f}%</span>'


def money(x, signed=False) -> str:
    if not _ok(x):
        return '<span class="na">–</span>'
    a = abs(x)
    s = f"{a / 1e12:,.2f}tn" if a >= 1e12 else f"{a / 1e9:,.1f}bn" if a >= 1e9 else f"{a / 1e6:,.0f}m"
    sign = ("+" if x > 0 else "−" if x < 0 else "") if signed else ("−" if x < 0 else "")
    cls = ("pos" if x > 0 else "neg" if x < 0 else "") if signed else ""
    return f'<span class="{cls}">{sign}${s}</span>'


def shares(x) -> str:
    if not _ok(x):
        return '<span class="na">–</span>'
    a = abs(x)
    s = f"{a / 1e6:,.1f}m" if a >= 1e6 else f"{a / 1e3:,.0f}k" if a >= 1e3 else f"{a:,.0f}"
    cls = "pos" if x > 0 else "neg" if x < 0 else ""
    return f'<span class="{cls}">{"+" if x > 0 else "−" if x < 0 else ""}{s}</span>'


def pill(kind: str, en: str, zh: str) -> str:
    return f'<span class="pill {kind}">{L(en, zh)}</span>'


FLOW = {"in": ("up", "Inflow", "流入"), "out": ("down", "Outflow", "流出"), "neutral": ("flat", "Neutral", "中性")}
TREND = {"up": ("up", "Uptrend", "上升"), "down": ("down", "Downtrend", "下降"), "mixed": ("flat", "Range", "震荡")}
TIME = {"pre": ("pre", "Before open", "盘前"), "after": ("after", "After close", "盘后"), "tbd": ("flat", "TBC", "待定")}
RATING = {"Strong Buy": "强烈买入", "Buy": "买入", "Hold": "持有", "Sell": "卖出", "Strong Sell": "强烈卖出"}


def _table(head, rows, cls=""):
    th = "".join(f"<th>{L(e, z)}</th>" for e, z in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tbl {cls}"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def _card(le, lz, value, sub=""):
    return f'<div class="card"><div class="lbl">{L(le, lz)}</div><div class="val">{value}</div><div class="subv">{sub}</div></div>'


def _chart(cid, te, tz, ne="", nz="", tall=False):
    note = f'<div class="note">{L(ne, nz)}</div>' if ne else ""
    return (f'<figure class="chartbox"><figcaption>{L(te, tz)}</figcaption>'
            f'<div class="chart{" tall" if tall else ""}" id="{cid}"></div>{note}</figure>')


def _summary(en, zh):
    return f'<p class="summary"><span lang="en">{en}</span><span lang="zh">{zh}</span></p>'


def _name(s):
    return f'<b>{html.escape(s["symbol"])}</b> <span class="muted">{L(s["en"], s["zh"])}</span>'


def render(ctx: dict) -> str:
    stocks, groups = ctx["stocks"], ctx["groups"]
    bp, bench_p = ctx["basket_perf"], ctx["bench_perf"]
    bench = ctx["bench"]
    by = {s["symbol"]: s for s in stocks}

    # ---------- overview
    n_in = sum(1 for s in stocks if s.get("flow") == "in")
    n_out = sum(1 for s in stocks if s.get("flow") == "out")
    nxt = next((e for e in ctx["earnings"] if e.get("next_date")), None)
    nxt_txt = (f'{nxt["symbol"]} · {nxt["next_date"][5:]}' if nxt else "–")
    nxt_sub = (pill(TIME[nxt.get("time", "tbd")][0], *TIME[nxt.get("time", "tbd")][1:]) + " "
               + L(f'in {nxt["days"]} days', f'{nxt["days"]} 天后')) if nxt else ""
    overview = ('<div class="grid4">'
                + _card("AI basket, 1 day", "AI 篮子 当日", pct(bp.get("d1"), 2), f'{L("Equal weight", "等权")} · {len(stocks)} {L("stocks", "只")}')
                + _card("AI basket, YTD", "AI 篮子 年初至今", pct(bp.get("ytd")), f'{bench} {pct(bench_p.get("ytd"))}')
                + _card("Flow signals", "资金信号", f'<span class="pos">{n_in}</span> / <span class="neg">{n_out}</span>',
                        L("inflow / outflow", "流入 / 流出"))
                + _card("Next earnings", "下一份财报", nxt_txt, nxt_sub)
                + '</div>' + _summary(*ctx["text"]["overview"])
                + '<div class="grid2">'
                + _chart("c_basket", f"AI basket vs {bench} and S&P 500", f"AI 篮子 vs {bench} 与标普 500",
                         "Rebased to 100 at the start of the window; drag the slider to change it.", "区间起点归 100，可拖动滑块调整。")
                + _chart("c_groups", "Sub-groups, year to date", "细分板块 年初至今", "Equal-weight baskets, rebased to 100.", "等权篮子，起点归 100。")
                + '</div>')

    # ---------- earnings
    erows = []
    for e in ctx["earnings"]:
        if not e.get("next_date"):
            continue
        s = by.get(e["symbol"], {"symbol": e["symbol"], "en": "", "zh": ""})
        t = TIME[e.get("time", "tbd")]
        hist = " ".join(f'<span class="dot {"up" if (h["surprise_pct"] or 0) > 0 else "down"}" title="{h["date"]}: {h["surprise_pct"]}%"></span>'
                        for h in reversed(e["history"]))
        est = f' <span class="muted">{L("(est.)", "（预估）")}</span>' if e.get("estimated") and e.get("time", "tbd") == "tbd" else ""
        erows.append([_name(s), f'<b>{e["next_date"]}</b>{est}',
                      f'<span class="pill {"soon" if e["days"] <= 7 else "flat"}">{L(str(e["days"]) + "d", str(e["days"]) + " 天")}</span>',
                      pill(t[0], t[1], t[2]), num(e.get("eps_forecast")), num(e.get("last_year_eps")),
                      pct(e.get("eps_rev_1m_pct"), 2), f'{e["beats"]}/{e["n_hist"]} {hist}',
                      "–" if e.get("avg_move") is None else f'±{e["avg_move"]:.1f}%'])
    rrows = []
    for e in ctx["earnings"]:
        r = e.get("recent")
        if not r:
            continue
        s = by.get(e["symbol"], {"symbol": e["symbol"], "en": "", "zh": ""})
        rrows.append([_name(s), r["date"], html.escape(r.get("quarter") or ""), num(r.get("eps")), num(r.get("consensus")),
                      pct(r.get("surprise_pct")), pct(r.get("reaction"))])
    earnings = (_summary(*ctx["text"]["earnings"])
                + _table([("Company", "公司"), ("Report date", "财报日"), ("Countdown", "倒计时"), ("Timing", "时段"),
                          ("EPS consensus", "EPS 一致预期"), ("Year-ago EPS", "去年同期 EPS"), ("Estimate revision 1M", "预期 1 月修正"),
                          ("Beats (last 4)", "近4季超预期"), ("Typical move", "历史财报后波动")], erows, "left2")
                + f'<div class="note">{L("Dates and consensus from Nasdaq.com (Zacks). Dates marked est. are projected from past reporting patterns until the company confirms. Typical move = average absolute change from the last close before the report to the first close after it, over the last four reports.", "日期与一致预期来自 Nasdaq.com（Zacks）。标“预估”的日期由历史发布规律推算，公司确认前可能变动。历史财报后波动 = 近 4 次财报前最后收盘价到财报后首个收盘价的平均绝对涨跌幅。")}</div>'
                + ('<h3>' + L("Recently reported", "近期已发布") + '</h3>'
                   + _table([("Company", "公司"), ("Date", "日期"), ("Quarter", "季度"), ("EPS", "EPS"), ("Consensus", "一致预期"),
                             ("Surprise", "超预期"), ("Stock reaction", "股价反应")], rrows) if rrows else "")
                + _chart("c_moves", "Typical post-earnings move", "历史财报后平均波动",
                         "Average absolute two-session move over the last four reports.", "近 4 次财报的两交易日平均绝对波动。"))

    # ---------- flows
    frows = []
    for s in sorted(stocks, key=lambda s: s.get("net_flow20") or 0, reverse=True):
        f = FLOW.get(s.get("flow") or "neutral")
        frows.append([_name(s), money(s.get("dollar_vol")), num(s.get("rel_vol"), 2) + "×", money(s.get("net_flow20"), True),
                      num(s.get("cmf20"), 2), num(s.get("mfi14"), 0), num(s.get("obv_days20"), 1), pill(*f)])
    etf_rows = []
    for e in ctx["etfs"]:
        f = FLOW.get(e.get("flow") or "neutral")
        etf_rows.append([L(e["en"], e["zh"]), num(e.get("last")), pct(e.get("m1")), pct(e.get("ytd")), money(e.get("dollar_vol")),
                         num(e.get("rel_vol"), 2) + "×", money(e.get("net_flow20"), True), num(e.get("cmf20"), 2), pill(*f)])
    flow = (_table([("Company", "公司"), ("Dollar volume", "成交额"), ("Relative volume", "相对成交量"),
                    ("Net flow 20D (est.)", "20日净流入（估算）"), ("CMF 20", "CMF 20"), ("MFI 14", "MFI 14"),
                    ("OBV 20D", "OBV 20日"), ("Signal", "信号")], frows, "left2")
            + f'<div class="note">{L("Estimated from daily price and volume, not from exchange order-flow data. Net flow = dollar volume on up days minus down days over 20 sessions. CMF = Chaikin money flow (> 0.05 accumulation). MFI = money flow index (> 60 strong, < 40 weak). OBV 20D = change in on-balance volume, in days of average volume. Signal: two or more of the three agreeing.", "由每日价格和成交量估算，并非交易所逐笔资金数据。净流入 = 20 个交易日中上涨日成交额减去下跌日成交额。CMF 为蔡金资金流（> 0.05 代表吸筹）；MFI 为资金流量指数（> 60 偏强，< 40 偏弱）；OBV 20日为能量潮变化，以平均日成交量天数计。信号：三项中至少两项同向。")}</div>'
            + '<div class="grid2">'
            + _chart("c_flow", "Estimated 20-day net flow", "20 日估算净流入", "USD billions.", "单位：十亿美元。", tall=True)
            + _chart("c_relvol", "Relative volume, latest session", "最新交易日相对成交量", "Volume ÷ 20-day average.", "成交量 ÷ 20 日均量。", tall=True)
            + '</div>'
            + '<h3>' + L("Sector and theme ETFs", "板块与主题 ETF") + '</h3>'
            + _table([("ETF", "ETF"), ("Last", "最新"), ("1M", "1个月"), ("YTD", "年初至今"), ("Dollar volume", "成交额"),
                      ("Relative volume", "相对成交量"), ("Net flow 20D (est.)", "20日净流入（估算）"), ("CMF 20", "CMF 20"),
                      ("Signal", "信号")], etf_rows)
            + _chart("c_flowhist", "AI basket: rolling 20-day net flow", "AI 篮子：滚动 20 日净流入",
                     "Sum across tracked stocks, USD billions.", "观察池合计，单位：十亿美元。"))

    # ---------- holders
    hrows = []
    for s in stocks:
        hrows.append([_name(s), num(s.get("inst_pct"), 1) + ("%" if _ok(s.get("inst_pct")) else ""),
                      pct(s.get("net_pct"), 2), f'{num(s.get("inc_holders"), 0)} / {num(s.get("dec_holders"), 0)}',
                      f'{num(s.get("new_holders"), 0)} / {num(s.get("soldout_holders"), 0)}',
                      shares(s.get("net_shares_3m")), num(s.get("days_to_cover"), 1), pct(s.get("si_change_pct"))])
    holders = (_table([("Company", "公司"), ("Institutional ownership", "机构持股比例"), ("13F net change", "13F 净增减"),
                       ("Holders up / down", "增持 / 减持家数"), ("New / sold out", "新进 / 清仓家数"),
                       ("Insider net 3M (shares)", "内部人 3 月净买卖（股）"), ("Days to cover", "空头回补天数"),
                       ("Short interest change", "空头仓位变化")], hrows, "left2")
               + f'<div class="note">{L("Institutional data from quarterly 13F filings (lagged up to 45 days after quarter end). 13F net change = (shares added by increasing and new holders − shares cut by decreasing and exiting holders) ÷ institutional shares. Short interest is reported twice a month. Source: Nasdaq.com.", "机构数据来自季度 13F 报告（季末后最多滞后 45 天）。13F 净增减 = （增持和新进的股数 − 减持和清仓的股数）÷ 机构持股总数。空头数据每月公布两次。来源：Nasdaq.com。")}</div>'
               + _chart("c_inst", "13F net change by company", "各公司 13F 机构净增减", "% of institutional shares.", "占机构持股的百分比。", tall=True))

    # ---------- performance
    prow = []
    for s in sorted(stocks, key=lambda s: s.get("market_cap") or 0, reverse=True):
        up = None if not (s.get("target_1y") and s.get("last")) else (s["target_1y"] / s["last"] - 1) * 100
        t = TREND.get(s.get("trend") or "mixed")
        rt = s.get("rating")
        prow.append([_name(s), L(groups[s["group"]]["en"], groups[s["group"]]["zh"]), money(s.get("market_cap")),
                     num(s.get("last")), pct(s.get("d1"), 2), pct(s.get("w1")), pct(s.get("m1")), pct(s.get("ytd")),
                     pct(s.get("from_hi")), num(s.get("rsi14"), 0), pill(*t),
                     L(rt, RATING.get(rt, rt)) if rt else "–", pct(up)])
    perf = (_table([("Company", "公司"), ("Group", "板块"), ("Market cap", "市值"), ("Price", "股价"), ("1D", "1日"), ("1W", "1周"),
                    ("1M", "1个月"), ("YTD", "年初至今"), ("From 52w high", "距52周高点"), ("RSI", "RSI"), ("Trend", "趋势"),
                    ("Analysts", "分析师评级"), ("To 1Y target", "距目标价")], prow, "left2")
            + _chart("c_perf", "One-month and year-to-date return", "近一月与年初至今涨跌", tall=True))

    # ---------- method
    status_rows = [[html.escape(s["source"]), html.escape(s["item"]),
                    pill("up", "OK", "正常") if s["ok"] == "ok" else pill("flat", "Cached", "沿用缓存") if s["ok"] == "cached" else pill("flat", "Partial", "部分成功") if s["ok"] == "partial" else pill("down", "Failed", "失败"),
                    html.escape(s.get("note") or "")] for s in ctx["status"]]
    method = (f'<p>{L("Universe: the stocks listed in config.json, grouped into chips, platforms and cloud, AI software, and servers, networking and power. Baskets are equal-weight and rebalanced daily. Prices and volumes: Yahoo Finance (daily, delayed). Earnings dates, consensus, surprises, 13F holdings, insider trades, short interest, ratings and targets: Nasdaq.com public pages (estimates by Zacks). If a Nasdaq request fails, the last successful value is kept and marked as cached. Personal, non-commercial project; data belong to their providers.", "观察池为 config.json 中的股票，分为芯片半导体、平台与云、AI 软件、服务器/网络/电力四组；篮子为等权、每日再平衡。股价与成交量来自 Yahoo Finance（日频，有延迟）；财报日期、一致预期、超预期历史、13F 持仓、内部人交易、空头数据、评级与目标价来自 Nasdaq.com 公开页面（预期数据由 Zacks 提供）。若某次请求失败，沿用上一次成功的数据并标注“沿用缓存”。本项目为个人非商业用途，数据版权归各提供方。")}</p>'
              + '<details><summary>' + L("Data status for this build", "本次更新的数据状态") + '</summary>'
              + _table([("Source", "来源"), ("Item", "项目"), ("Status", "状态"), ("Note", "备注")], status_rows, "left2")
              + '</details>')

    nav = [("overview", "Overview", "总览"), ("earnings", "Earnings", "财报日历"), ("flows", "Fund flows", "资金流向"),
           ("holders", "Holders & shorts", "机构与空头"), ("perf", "Performance", "行情"), ("method", "Method", "方法")]
    nav_html = "".join(f'<a href="#{i}">{L(e, z)}</a>' for i, e, z in nav)

    def section(i, e, z, body):
        return f'<section id="{i}"><h2>{L(e, z)}</h2>{body}</section>'

    body = (section("overview", "AI stocks at a glance", "AI 股票总览", overview)
            + section("earnings", "Earnings calendar", "财报日历", earnings)
            + section("flows", "Fund flows", "资金流向", flow)
            + section("holders", "Institutions, insiders & shorts", "机构、内部人与空头", holders)
            + section("perf", "Performance", "行情表现", perf)
            + section("method", "Methodology & sources", "方法与数据来源", method))
    payload = json.dumps(ctx["payload"], separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    return (PAGE.replace("%%CSS%%", CSS).replace("%%NAV%%", nav_html).replace("%%BODY%%", body)
            .replace("%%UPDATED%%", html.escape(ctx["updated"])).replace("%%DATA%%", payload).replace("%%ECHARTS%%", ECHARTS))


PAGE = r"""<!doctype html>
<html lang="en" data-lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Stocks Radar</title>
<meta name="description" content="Daily radar for US AI stocks: earnings calendar, volume-based fund flows, institutional and short-interest changes, performance.">
<style>%%CSS%%</style></head><body>
<header><div class="bar"><div class="brand"><span lang="en">AI Stocks Radar</span><span lang="zh">美股 AI 雷达</span>
<small><span lang="en">Updated</span><span lang="zh">更新于</span> %%UPDATED%% UTC</small></div>
<nav>%%NAV%%</nav><button class="lang" id="langBtn" type="button">中文 / EN</button></div></header>
<main>%%BODY%%</main>
<footer><span lang="en">For information only. Generated automatically from public data with delays; not investment advice.</span>
<span lang="zh">仅供参考。本页由公开数据自动生成，存在延迟，不构成任何投资建议。</span></footer>
<script>window.DATA=%%DATA%%;</script>
<script src="%%ECHARTS%%"></script>
<script>
(function(){
var D=window.DATA,root=document.documentElement,charts=[],lang='en';
try{var sv=localStorage.getItem('air-lang');if(sv){lang=sv;}else if((navigator.language||'').toLowerCase().indexOf('zh')===0){lang='zh';}}catch(e){if((navigator.language||'').toLowerCase().indexOf('zh')===0){lang='zh';}}
function setLang(l){lang=l;root.setAttribute('data-lang',l);root.setAttribute('lang',l==='zh'?'zh-CN':'en');try{localStorage.setItem('air-lang',l);}catch(e){}draw();}
document.getElementById('langBtn').addEventListener('click',function(){setLang(lang==='en'?'zh':'en');});
var dark=window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches;
var TXT=dark?'#c9ccd1':'#3b4252',GRID=dark?'#2b3038':'#e6e6ef';
var PAL=['#4f46e5','#0f8a8a','#c2410c','#9b5c84','#6b8f3a','#8a8f98'],POS=dark?'#5cc97b':'#1f7a3a',NEG=dark?'#f28b82':'#b42318';
function t(o){return typeof o==='string'?o:(o[lang]||o.en);}
function base(){return{animation:false,textStyle:{color:TXT,fontFamily:'inherit'},grid:{left:56,right:24,top:36,bottom:56},
 tooltip:{trigger:'axis',valueFormatter:function(v){return v==null?'–':(+v).toFixed(2);}},legend:{top:0,textStyle:{color:TXT}},
 xAxis:{type:'time',axisLine:{lineStyle:{color:GRID}},axisLabel:{color:TXT},splitLine:{show:false}},
 yAxis:{type:'value',scale:true,axisLabel:{color:TXT},splitLine:{lineStyle:{color:GRID}}}};}
function ln(name,data,color){return{name:t(name),type:'line',data:data||[],showSymbol:false,lineStyle:{width:1.8,color:color},itemStyle:{color:color}};}
function zoom(s){return[{type:'inside',start:s,end:100},{type:'slider',start:s,end:100,height:18,bottom:6,borderColor:GRID,textStyle:{color:TXT}}];}
function mk(id,o){var el=document.getElementById(id);if(!el)return;var c=echarts.init(el);c.setOption(o);charts.push(c);}
function hbar(id,rows,fmt,signed){var o=base();o.grid={left:64,right:30,top:10,bottom:24};o.legend={show:false};
 o.xAxis={type:'value',axisLabel:{color:TXT,formatter:fmt},splitLine:{lineStyle:{color:GRID}}};
 o.yAxis={type:'category',data:rows.map(function(r){return r.k;}),inverse:true,axisLabel:{color:TXT}};
 o.tooltip={trigger:'axis',axisPointer:{type:'shadow'},valueFormatter:function(v){return v==null?'–':(+v).toFixed(2);}};
 o.series=[{type:'bar',data:rows.map(function(r){return{value:r.v,itemStyle:{color:signed?(r.v>=0?POS:NEG):PAL[0]}};})}];mk(id,o);}
function draw(){
 if(typeof echarts==='undefined')return;charts.forEach(function(c){c.dispose();});charts=[];var S=D.series,o;
 o=base();o.series=[ln({en:'AI basket',zh:'AI 篮子'},S.basket,PAL[0]),ln(D.bench,S.bench,PAL[1]),ln({en:'S&P 500',zh:'标普 500'},S.spy,PAL[5])];
 o.dataZoom=zoom(50);mk('c_basket',o);
 o=base();o.series=(D.groups||[]).map(function(g,i){return ln(g.name,g.data,PAL[i%PAL.length]);});mk('c_groups',o);
 hbar('c_moves',D.bars.moves||[],'±{value}%',false);
 hbar('c_flow',D.bars.flow||[],'{value}',true);
 hbar('c_relvol',D.bars.relvol||[],'{value}×',false);
 hbar('c_inst',D.bars.inst||[],'{value}%',true);
 o=base();o.series=[{name:t({en:'Net flow',zh:'净流入'}),type:'bar',data:(S.flow||[]).map(function(p){return{value:p,itemStyle:{color:p[1]>=0?POS:NEG}};}),barCategoryGap:'0%'}];
 o.dataZoom=zoom(40);mk('c_flowhist',o);
 var P=D.bars.perf||[];o=base();o.grid={left:64,right:24,top:30,bottom:24};
 o.xAxis={type:'value',axisLabel:{color:TXT,formatter:'{value}%'},splitLine:{lineStyle:{color:GRID}}};
 o.yAxis={type:'category',data:P.map(function(r){return r.k;}),inverse:true,axisLabel:{color:TXT}};
 o.tooltip={trigger:'axis',axisPointer:{type:'shadow'},valueFormatter:function(v){return v==null?'–':(+v).toFixed(1)+'%';}};
 o.series=[{name:t({en:'1 month',zh:'1个月'}),type:'bar',data:P.map(function(r){return r.m1;}),itemStyle:{color:PAL[0]}},
  {name:t({en:'Year to date',zh:'年初至今'}),type:'bar',data:P.map(function(r){return r.ytd;}),itemStyle:{color:PAL[2]}}];mk('c_perf',o);
}
window.addEventListener('resize',function(){charts.forEach(function(c){c.resize();});});
setLang(lang);
})();
</script></body></html>"""
