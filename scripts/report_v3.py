#!/usr/bin/env python3
"""暗黑高级金融终端风格 HTML 报告生成器"""

import os, json

GRADES = {
    'A+': ('#00D4AA', 'rgba(0,212,170,0.12)', 'rgba(0,212,170,0.25)'),
    'A':  ('#4DA6FF', 'rgba(77,166,255,0.12)', 'rgba(77,166,255,0.25)'),
    'B+': ('#FFB347', 'rgba(255,179,71,0.12)', 'rgba(255,179,71,0.25)'),
    'B':  ('#FFB347', 'rgba(255,179,71,0.12)', 'rgba(255,179,71,0.25)'),
    'B-': ('#FF6B6B', 'rgba(255,107,107,0.12)', 'rgba(255,107,107,0.25)'),
    'C':  ('#FF3838', 'rgba(255,56,56,0.12)', 'rgba(255,56,56,0.25)'),
}

def _gd(g):
    return GRADES.get(g, ('#888', 'rgba(136,136,136,.12)', 'rgba(136,136,136,.25)'))

def build(result, output_path=None):
    if not result.get('success'):
        return None
    if not output_path:
        d = os.path.join(os.path.expanduser('~/.hermes/lhb_state'), 'reports')
        os.makedirs(d, exist_ok=True)
        output_path = os.path.join(d, 'lhb_report_' + result['date'] + '.html')

    M = result['market']
    S = result['screening']
    C = result['candidates']
    L = result['dynamic_chg_limit']
    V = result['version']
    D = result['date']
    bull = M['above_ma20']
    mstat = '牛市' if bull else '熊市'
    idx_val = '{:.2f}'.format(M['index_close'])
    idx_st = '站上' if bull else '跌破'
    dev_sign = '+' if M['deviation'] >= 0 else ''

    # Stats
    stats = (
        '<div class="stats">'
        '<div class="stat anim" style="animation-delay:0s"><div class="lbl">上证指数</div><div class="val">{}</div><div class="sub"><span class="{}">{} MA20 {:.2f} &middot; 偏离{}{:.2f}%</span></div></div>'
        '<div class="stat anim" style="animation-delay:.05s"><div class="lbl">市场状态</div><div class="val" style="color:{}">{}</div><div class="sub">动态阈值 {}%</div></div>'
        '<div class="stat anim" style="animation-delay:.1s"><div class="lbl">精选标的</div><div class="val" style="color:var(--accent)">{}</div><div class="sub">总净买入 {:.1f}亿</div></div>'
        '<div class="stat anim" style="animation-delay:.15s"><div class="lbl">上榜总数</div><div class="val">{}</div><div class="sub">{} 条龙虎榜记录</div></div>'
        '</div>'
    ).format(idx_val, 'up' if bull else 'dn', idx_st, M['ma20'], dev_sign, M['deviation'],
             '#FF6B6B' if bull else '#00D4AA', mstat, L,
             S['candidates'], result.get('total_net_buy_yi', 0),
             S['total_stocks'], S['total_records'])

    # Funnel
    total = max(S['total_records'], 1)
    a, b_rem, c = S['total_stocks'], S['total_stocks'] - S['candidates'], S['candidates']
    p0 = max((total - a) / total * 100, 3)
    p1 = max((a - b_rem) / total * 100, 3)
    p2 = max(b_rem / total * 100, 3)
    p3 = max(c / total * 100, 3)
    funnel = (
        '<div class="funnel-bar">'
        '<div class="fb-seg" style="width:{:.1f}%"><span class="n">{}</span><span class="t">记录</span></div>'
        '<div class="fb-seg" style="width:{:.1f}%"><span class="n">{}</span><span class="t">上榜</span></div>'
        '<div class="fb-seg" style="width:{:.1f}%"><span class="n">{}</span><span class="t">移除</span></div>'
        '<div class="fb-seg" style="width:{:.1f}%"><span class="n">{}</span><span class="t">精选</span></div>'
        '</div>'
    ).format(p0, total, p1, a, p2, b_rem, p3, c)

    # Tags
    tags = ''.join(
        '<span class="tag">{}<b>{}</b></span>'.format(r, ct)
        for r, ct in sorted(S['removed'].items(), key=lambda x: -x[1])
    )

    # Cards
    cards_html = ''
    charts_js = []
    for i, c in enumerate(C):
        g = c['grade']
        gc, gbg, gfill = _gd(g)
        risk = '低' if g in ('A+','A') else '中' if g in ('B+','B') else '高'
        chg = c['chg_5d']
        chg_c = 'up' if chg > 0 else 'dn'
        chg_s = '+' if chg >= 0 else ''
        cid = 'r' + c['code']
        delay = .05 * i + .2

        lbs = json.dumps([sd['label'] for sd in c['score_detail']], ensure_ascii=False)
        scs = json.dumps([sd['score'] for sd in c['score_detail']])

        cards_html += (
            '<div class="card anim" style="animation-delay:{:.2f}s">'.format(delay)
            + '<div class="card-top">'
            + '<div class="card-id">'
            + '<span class="card-num">#{}</span>'.format(i + 1)
            + '<div>'
            + '<div class="card-name">{}<span class="card-code">{}</span></div>'.format(c['name'], c['code'])
            + '<div class="card-tags">'
            + '<span class="grade-badge" style="background:{};color:{}">{}</span>'.format(gbg, gc, g)
            + '<span class="tag">{}</span>'.format(c['board_quality'])
            + '<span class="tag">{}</span>'.format(c['sector_str'])
            + '</div></div></div>'
            + '<div class="card-score-h"><span class="big">{}</span><span class="unit">/100</span></div>'.format(c['total_score'])
            + '</div>'
            + '<div class="card-grid">'
            + '<div class="card-left">'
            + '<div class="kv"><span class="k">收盘价</span><span class="v">{:.2f}</span></div>'.format(c['close_price'])
            + '<div class="kv"><span class="k">净买入</span><span class="v up">{:.1f}亿</span></div>'.format(c['net_yi'])
            + '<div class="kv"><span class="k">5日涨幅</span><span class="v {}">{}{:.1f}%</span></div>'.format(chg_c, chg_s, chg)
            + '<div class="kv"><span class="k">换手率</span><span class="v">{:.1f}%</span></div>'.format(c['turnover'])
            + '<div class="kv"><span class="k">机构买入</span><span class="v">{}家 / {:.0f}%</span></div>'.format(c['jigou_count'], c['jigou_success_rate'])
            + '<div class="kv"><span class="k">MA20偏离</span><span class="v">{:+.1f}%</span></div>'.format(c['ma20_dev'])
            + '</div>'
            + '<div class="card-right"><canvas id="{}"></canvas></div>'.format(cid)
            + '</div>'
            + '<div class="plan-bar">'
            + '<div class="plan-cell"><span class="pl">仓位</span><span class="pv">{}</span></div>'.format(c['position'])
            + '<div class="plan-cell"><span class="pl">风控</span><span class="pv">{}</span></div>'.format(risk)
            + '<div class="plan-cell"><span class="pl">时段</span><span class="pv">14:30-50</span></div>'
            + '<div class="plan-cell plan-sl"><span class="pl">止损 -3%</span><span class="pv">{}</span></div>'.format(c['stop_loss'])
            + '<div class="plan-cell plan-tp"><span class="pl">止盈 +5%</span><span class="pv">{}</span></div>'.format(c['tp1'])
            + '<div class="plan-cell plan-tp"><span class="pl">止盈 +10%</span><span class="pv">{}</span></div>'.format(c['tp2'])
            + '</div></div>'
        )

        charts_js.append(
            'new Chart(document.getElementById("' + cid + '"),{type:"radar",data:{labels:' + lbs
            + ',datasets:[{data:' + scs
            + ',backgroundColor:"' + gfill + '",borderColor:"' + gc
            + '",borderWidth:1.2,pointRadius:2.5,pointBackgroundColor:"' + gc
            + '",pointBorderColor:"transparent",pointHoverRadius:5}]},options:{responsive:true,maintainAspectRatio:true,'
            + 'plugins:{legend:{display:false},tooltip:{backgroundColor:"rgba(17,17,24,.95)",titleFont:{size:12},bodyFont:{size:12},padding:12,cornerRadius:8,displayColors:false}},'
            + 'scales:{r:{min:0,max:100,ticks:{display:false,stepSize:20,backdropColor:"transparent"},'
            + 'grid:{color:"rgba(255,255,255,.06)"},angleLines:{color:"rgba(255,255,255,.06)"},'
            + 'pointLabels:{font:{size:10,family:"-apple-system,sans-serif"},color:"#6B6B78"}}}}});'
        )

    # Risk
    risks = []
    if not bull:
        risks.append('上证跌破MA20，逆势做多风险大，建议降低仓位或观望')
    for c in C:
        if c['grade'] in ('B-','C'):
            risks.append(c['name'] + '(' + c['grade'] + '级) 评分偏低，不建议操作')
        if c['chg_5d'] > L * 0.8:
            risks.append(c['name'] + ' 5日涨幅{:.1f}%接近阈值{}%，高位风险'.format(c['chg_5d'], L))
        if c.get('sector_name') is None:
            risks.append(c['name'] + ' 无板块联动，缺乏板块支撑')
    risk_html = ''
    if risks:
        risk_html = '<div class="risk-box anim" style="animation-delay:.3s"><div class="rh">RISK</div>' + ''.join(
            '<div class="ri">' + r + '</div>' for r in risks) + '</div>'

    # Body
    body = (
        '<div class="hero anim" style="animation-delay:0s">'
        + '<h1>龙虎榜选股</h1>'
        + '<div class="sub"><b>' + D + '</b><span class="dot"></span>v' + V
        + '<span class="dot"></span>8因子量化模型<span class="live"><span class="live-dot"></span>数据驱动</span></div>'
        + '</div>'
        + stats
    )

    if C:
        body += funnel
        if tags:
            body += '<div class="tag-row">' + tags + '</div>'
        body += cards_html
        if risk_html:
            body += risk_html
    else:
        body += '<div class="empty-box anim" style="animation-delay:.2s"><div class="eh">今日无符合标的</div><div class="ed">建议空仓观察，耐心等待机会</div></div>'

    body += '<footer>LHB Screener v' + V + ' &middot; EastMoney Data &middot; For Reference Only</footer>'

    # Chart init
    chart_init = ''
    if C:
        chart_init = (
            '<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>'
            + '<script>' + '\n'.join(charts_js) + '</script>'
        )

    html = TEMPLATE.replace('{{DATE}}', D).replace('{{BODY}}', body).replace('{{CHARTS}}', chart_init)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return output_path


TEMPLATE = '''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LHB &middot; {{DATE}}</title>
<style>
:root{--bg:#0A0A10;--card:#111118;--card2:#161620;--border:rgba(255,255,255,.06);--text:#EEEEF0;--mute:#6B6B78;--dim:#3D3D4A;--up:#FF6B6B;--down:#00D4AA;--accent:#4DA6FF;--gold:#FFB347}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text);-webkit-font-smoothing:antialiased;max-width:940px;margin:0 auto;padding:52px 28px 100px;line-height:1.5}
::selection{background:rgba(77,166,255,.2)}
.hero{margin-bottom:44px}
.hero h1{font-size:42px;font-weight:700;letter-spacing:-1.5px;margin-bottom:6px;background:linear-gradient(135deg,#EEEEF0 0%,#9A9AB0 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.hero .sub{font-size:14px;color:var(--mute);letter-spacing:.3px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.hero .sub .dot{width:5px;height:5px;border-radius:50%;background:var(--dim)}
.hero .sub b{color:var(--text);font-weight:600}
.hero .sub .live{display:inline-flex;align-items:center;gap:6px;color:var(--gold);font-size:12px}
.live-dot{width:6px;height:6px;border-radius:50%;background:var(--gold);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border);border-radius:16px;overflow:hidden;margin-bottom:34px}
.stat{background:var(--card);padding:24px 28px;position:relative;overflow:hidden;transition:background .2s}
.stat:hover{background:var(--card2)}
.stat .lbl{font-size:10px;color:var(--mute);text-transform:uppercase;letter-spacing:1.2px;margin-bottom:12px;font-weight:600}
.stat .val{font-size:34px;font-weight:700;letter-spacing:-1px;font-family:"SF Mono","JetBrains Mono","Fira Code","Consolas",monospace}
.stat .val .unit{font-size:14px;font-weight:400;color:var(--mute)}
.stat .sub{font-size:12px;color:var(--mute);margin-top:10px;line-height:1.4}
.stat .sub .up{color:var(--up)}.stat .sub .dn{color:var(--down)}
.funnel-bar{display:flex;background:var(--card);border-radius:12px;margin-bottom:26px;overflow:hidden;height:52px;border:1px solid var(--border)}
.fb-seg{height:100%;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:600;transition:all .3s;min-width:0}
.fb-seg:first-child{background:var(--card2)}
.fb-seg:last-child{background:rgba(77,166,255,.08);color:var(--accent)}
.fb-seg:nth-child(2){background:rgba(255,255,255,.015)}
.fb-seg:nth-child(3){background:rgba(255,107,107,.05)}
.fb-seg:hover{filter:brightness(1.3)}
.fb-seg .n{font-family:"SF Mono","JetBrains Mono","Consolas",monospace;font-size:18px;font-weight:700;margin-right:8px}
.fb-seg .t{font-size:11px;color:var(--mute);font-weight:400;letter-spacing:.3px}
.fb-seg:last-child .t{color:var(--accent)}
.tag-row{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:30px}
.tag{display:inline-flex;align-items:center;gap:5px;background:var(--card);border:1px solid var(--border);border-radius:24px;padding:5px 14px;font-size:11px;color:var(--mute);font-family:"SF Mono","JetBrains Mono","Consolas",monospace;transition:border-color .2s}
.tag:hover{border-color:rgba(255,255,255,.1)}
.tag b{color:var(--text);font-weight:600;margin-left:2px}
.card{background:var(--card);border-radius:18px;margin-bottom:22px;border:1px solid var(--border);overflow:hidden;transition:border-color .25s,transform .25s}
.card:hover{border-color:rgba(255,255,255,.1)}
.card-top{display:flex;align-items:center;justify-content:space-between;padding:30px 36px 22px;gap:20px}
.card-id{display:flex;align-items:flex-start;gap:18px}
.card-num{font-size:15px;color:var(--dim);font-weight:600;font-family:"SF Mono","JetBrains Mono","Consolas",monospace;padding-top:3px;opacity:.6}
.card-name{font-size:24px;font-weight:700;letter-spacing:-.5px;margin-bottom:10px}
.card-code{font-size:13px;color:var(--dim);font-weight:400;margin-left:12px;font-family:"SF Mono","JetBrains Mono","Consolas",monospace;opacity:.7}
.card-tags{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.grade-badge{display:inline-flex;align-items:center;justify-content:center;min-width:36px;height:36px;padding:0 6px;border-radius:10px;font-size:15px;font-weight:700;font-family:"SF Mono","JetBrains Mono","Consolas",monospace;letter-spacing:.5px}
.card-score-h{text-align:right;flex-shrink:0}
.card-score-h .big{font-size:52px;font-weight:200;letter-spacing:-2.5px;line-height:1;font-family:"SF Mono","JetBrains Mono","Fira Code","Consolas",monospace}
.card-score-h .unit{font-size:16px;color:var(--mute);font-weight:400;margin-left:4px;letter-spacing:0}
.card-grid{display:grid;grid-template-columns:1fr 340px;border-top:1px solid var(--border)}
.card-left{padding:26px 36px;border-right:1px solid var(--border)}
.kv{display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid rgba(255,255,255,.025)}
.kv:last-child{border-bottom:none}
.kv .k{font-size:13px;color:var(--mute);font-weight:400}
.kv .v{font-size:15px;font-weight:600;font-family:"SF Mono","JetBrains Mono","Consolas",monospace;text-align:right;letter-spacing:-.2px}
.kv .v.up{color:var(--up)}.kv .v.dn{color:var(--down)}
.card-right{padding:20px 24px;display:flex;align-items:center;justify-content:center;min-height:280px}
.card-right canvas{max-height:280px}
.plan-bar{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));border-top:1px solid var(--border)}
.plan-cell{display:flex;flex-direction:column;gap:6px;padding:16px 20px;border-right:1px solid var(--border);background:var(--card);transition:background .2s}
.plan-cell:last-child{border-right:none}
.plan-cell:hover{background:var(--card2)}
.plan-cell .pl{font-size:10px;color:var(--mute);text-transform:uppercase;letter-spacing:.8px;font-weight:600}
.plan-cell .pv{font-size:17px;font-weight:600;font-family:"SF Mono","JetBrains Mono","Consolas",monospace;letter-spacing:-.3px}
.plan-sl{background:rgba(255,107,107,.04)}.plan-sl .pv{color:var(--up)}
.plan-tp{background:rgba(0,212,170,.03)}.plan-tp .pv{color:var(--down)}
.risk-box{background:rgba(255,179,71,.03);border:1px solid rgba(255,179,71,.12);border-radius:16px;padding:22px 30px;margin-top:30px}
.risk-box .rh{font-size:13px;font-weight:700;color:var(--gold);margin-bottom:16px;letter-spacing:.6px}
.risk-box .ri{font-size:13px;color:rgba(255,179,71,.65);padding:6px 0;display:flex;align-items:flex-start;gap:12px;line-height:1.5}
.risk-box .ri::before{content:"!";color:var(--gold);font-weight:700;font-size:13px;flex-shrink:0;margin-top:1px}
.empty-box{text-align:center;padding:120px 20px;background:var(--card);border-radius:18px;border:1px solid var(--border)}
.empty-box .eh{font-size:18px;font-weight:600;margin-bottom:10px;color:var(--text)}
.empty-box .ed{font-size:14px;color:var(--mute)}
footer{text-align:center;padding:48px 0 0;font-size:11px;color:var(--dim);letter-spacing:.5px}
@keyframes fadeUp{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}
.anim{animation:fadeUp .6s cubic-bezier(.16,1,.3,1) both}
@media(max-width:700px){
body{padding:28px 16px 80px}
.hero h1{font-size:30px}
.stats{grid-template-columns:repeat(2,1fr)}
.stat .val{font-size:26px}
.card-grid{grid-template-columns:1fr}
.card-left{border-right:none;border-bottom:1px solid var(--border)}
.card-right{padding:16px;min-height:240px}
.card-top{padding:22px 20px}
.card-name{font-size:19px}
.card-score-h .big{font-size:38px}
.funnel-bar{flex-direction:column;height:auto;border-radius:16px}
.fb-seg{padding:12px;width:100%;border-bottom:1px solid var(--border)}
.fb-seg:last-child{border-bottom:none}
.plan-bar{grid-template-columns:repeat(3,1fr)}
}
</style>
</head>
<body>
{{BODY}}
{{CHARTS}}
</body>
</html>'''
