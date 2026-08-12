#!/usr/bin/env python3
"""
龙虎榜选股 v3.0 — 评分制 + 数据层优化 + 动态阈值 + 持仓跟踪
用法: python3 lhb_v3.py [--date YYYY-MM-DD] [--backtest DAYS] [--track]
"""
import urllib.request, json, re, os, sys, time
from collections import defaultdict
from datetime import datetime, timedelta

# ============== 配置 ==============
STATE_DIR = os.path.expanduser("~/.hermes/lhb_state")
os.makedirs(STATE_DIR, exist_ok=True)

THEME_KEYWORDS = {
    '半导体/芯片': ['芯片', '半导体', '微', '电子', '集成', '科技'],
    '新能源/锂电': ['锂', '电池', '新能源', '光伏', '储能'],
    '军工/航天': ['航天', '航空', '军工', '中航', '兵器'],
    '通信/算力': ['通信', '算力', '服务器', '数据中心', '长城', '信息'],
    '材料/化工': ['材料', '化学', '化工', '纤维', '氟'],
    '机械/自动化': ['机械', '装备', '自动化', '机器人'],
    '医药/生物': ['医药', '生物', '药', '医疗', '健康'],
    '消费/食品': ['消费', '食品', '饮料', '酒', '乳'],
    '金融/证券': ['证券', '银行', '保险', '金融'],
    '汽车/智驾': ['汽车', '车', '智驾', '驾驶'],
}

# 评分权重 (总和100%)
SCORE_WEIGHTS = {
    'net_buy': 0.15,      # 净买入额（回测：10亿+反扣，5-10亿最优）
    'jigou_count': 0.20,  # 机构家数（回测：3家+是强信号，权重↑）
    'jigou_rate': 0.05,   # 机构成功率（回测：区分度差，权重↓）
    'chg_5d': 0.15,       # 5日涨幅位置
    'ma20_dev': 0.10,     # MA20偏离
    'turnover': 0.15,     # 换手率（回测：低换手是强信号，权重↑）
    'sector': 0.10,       # 板块联动
    'market': 0.10,       # 大盘环境
}

# ============== 工具函数 ==============
def safe_float(v, default=0):
    try: return float(v) if v is not None else default
    except: return default

def fetch_json(url, timeout=15, encoding='utf-8'):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://data.eastmoney.com/"
    })
    resp = urllib.request.urlopen(req, timeout=timeout)
    raw = resp.read()
    return json.loads(raw.decode(encoding))

def get_kline_sina(code, count=25):
    """新浪K线API"""
    if code == '000001':  # 上证指数
        symbol = 'sh000001'
    else:
        symbol = f"sh{code}" if code.startswith('6') else f"sz{code}"
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={count}"
    data = fetch_json(url, encoding='gbk')
    return data

def get_kline_eastmoney(code, count=25):
    """东方财富K线API"""
    market = "1" if code.startswith('6') else "0"
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={market}.{code}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=1&end=20500101&lmt={count}"
    data = fetch_json(url)
    if data.get("data") and data["data"].get("klines"):
        rows = []
        for line in data["data"]["klines"]:
            parts = line.split(",")
            rows.append({
                "day": parts[0], "open": parts[1], "close": parts[2],
                "high": parts[3], "low": parts[4], "volume": parts[5],
                "amount": parts[6], "chg_pct": parts[8]
            })
        return rows
    return None

def get_kline(code, count=25):
    """获取K线，先试东方财富，失败用新浪"""
    try:
        data = get_kline_eastmoney(code, count)
        if data and len(data) >= count - 5:
            return data, 'em'
    except:
        pass
    try:
        data = get_kline_sina(code, count)
        if data and len(data) >= count - 5:
            return data, 'sina'
    except:
        pass
    return None, None

def calc_kline_metrics(kline, source, is_kcb=False):
    """从K线计算各种指标"""
    if not kline or len(kline) < 6:
        return None
    
    if source == 'sina':
        closes = [safe_float(d['close']) for d in kline]
        volumes = [safe_float(d['volume']) for d in kline]
    else:  # em
        closes = [safe_float(d['close']) for d in kline]
        volumes = [safe_float(d['volume']) for d in kline]
    
    last_close = closes[-1]
    
    # MA20
    if len(closes) >= 20:
        ma20 = sum(closes[-20:]) / 20
    else:
        ma20 = sum(closes) / len(closes)
    
    # MA20偏离
    ma20_dev = (last_close / ma20 - 1) * 100 if ma20 > 0 else 0
    
    # 5日涨幅
    prev_5d = closes[-6] if len(closes) >= 6 else closes[0]
    chg_5d = (last_close / prev_5d - 1) * 100
    
    # 前期涨停板 (近5日不含今天)
    limit_pct = 19.5 if is_kcb else 9.5
    prev_boards = 0
    for i in range(max(1, len(closes) - 6), len(closes) - 1):
        day_chg = (closes[i] / closes[i-1] - 1) * 100
        if day_chg >= limit_pct:
            prev_boards += 1
    
    # 前日放量下跌
    ma5_vol = sum(volumes[-6:-1]) / 5 if len(volumes) >= 6 else 0
    prev_vol = volumes[-2] if len(volumes) >= 2 else 0
    prev_close_chg = (closes[-2] / closes[-3] - 1) * 100 if len(closes) >= 3 else 0
    prev_vol_ratio = prev_vol / ma5_vol if ma5_vol > 0 else 0
    prev_vol_dump = prev_vol_ratio > 1.5 and prev_close_chg < 0
    
    # 成交量趋势: 涨停日量 vs 5日均量
    today_vol = volumes[-1]
    vol_ratio_today = today_vol / ma5_vol if ma5_vol > 0 else 0
    
    return {
        'closes': closes, 'volumes': volumes,
        'ma20': ma20, 'ma20_dev': ma20_dev,
        'chg_5d': chg_5d, 'prev_boards': prev_boards,
        'prev_vol_dump': prev_vol_dump, 'prev_vol_ratio': prev_vol_ratio,
        'ma5_vol': ma5_vol, 'vol_ratio_today': vol_ratio_today,
        'last_close': last_close,
    }

def get_index_ma20():
    """获取上证指数MA20状态"""
    try:
        data = get_kline_sina('000001', 25)
        if data:
            closes = [safe_float(d['close']) for d in data]
            ma20 = sum(closes[-20:]) / 20
            last = closes[-1]
            return {'close': last, 'ma20': ma20, 'above': last >= ma20, 'dev': (last/ma20-1)*100}
    except:
        pass
    return None

# ============== 评分函数 ==============
def score_net_buy(net_amt_yi):
    """净买入评分 (亿) — 回测：5-10亿最优,10亿+反扣(大额=出货信号)"""
    if net_amt_yi >= 10: return 70   # 大额反扣
    if net_amt_yi >= 5: return 100   # 最优区间
    if net_amt_yi >= 2: return 75
    if net_amt_yi >= 1: return 60
    return 40

def score_jigou_count(count):
    """机构家数评分 — 回测：2家=分歧信号降分"""
    if count >= 4: return 100
    if count >= 3: return 90
    if count >= 2: return 65   # 分歧信号，从75→65
    if count >= 1: return 55
    return 0

def score_jigou_rate(rate):
    """机构成功率评分 — 回测：区分度差，简化评分"""
    if rate >= 55: return 90
    if rate >= 50: return 75
    if rate >= 45: return 60
    return 40

def score_chg_5d(chg, dynamic_limit=25):
    """5日涨幅评分 (动态阈值)"""
    if chg < 5: return 100
    if chg < 10: return 90
    if chg < 15: return 80
    if chg < dynamic_limit * 0.8: return 70
    if chg < dynamic_limit: return 60
    return 30  # 超限

def score_ma20_dev(dev):
    """MA20偏离评分"""
    if dev < 3: return 100
    if dev < 5: return 90
    if dev < 8: return 80
    if dev < 11: return 70
    if dev < 15: return 60
    return 30

def score_turnover(turnover, is_kcb=False):
    """换手率评分"""
    good = 25 if is_kcb else 20
    if turnover < 5: return 100
    if turnover < 8: return 90
    if turnover < good * 0.6: return 80
    if turnover < good * 0.8: return 70
    if turnover < good: return 60
    if turnover < 30: return 40
    return 20

def score_sector(sector_count):
    """板块联动评分"""
    if sector_count >= 5: return 100
    if sector_count >= 3: return 80
    if sector_count >= 2: return 60
    return 40  # 独狼

def score_market(above_ma20, dev):
    """大盘环境评分"""
    if above_ma20:
        if dev > 2: return 90
        return 100
    else:
        if dev > -1: return 70  # 微破
        if dev > -3: return 50
        return 30

def compute_total_score(scores):
    """计算加权总分"""
    total = 0
    for key, weight in SCORE_WEIGHTS.items():
        total += scores.get(key, 0) * weight
    return round(total, 1)

def grade_from_score(score):
    """评级"""
    if score >= 85: return 'A+'
    if score >= 75: return 'A'
    if score >= 65: return 'B+'
    if score >= 55: return 'B'
    if score >= 45: return 'B-'
    return 'C'

# ============== 核心流程 ==============
def fetch_lhb(date_str):
    """获取龙虎榜原始数据"""
    url = f"https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_DAILYBILLBOARD_DETAILSNEW&columns=ALL&pageNumber=1&pageSize=500&sortTypes=-1&sortColumns=BILLBOARD_NET_AMT&filter=(TRADE_DATE='{date_str}')"
    data = fetch_json(url)
    if data.get("result") and data["result"].get("data"):
        return data["result"]["data"]
    return []

def aggregate_stocks(raw):
    """聚合到个股"""
    stocks = defaultdict(lambda: {"net_amt": 0, "explains": []})
    for r in raw:
        code = r.get("SECURITY_CODE", "")
        name = r.get("SECURITY_NAME_ABBR", "")
        key = code
        stocks[key]["code"] = code
        stocks[key]["name"] = name
        stocks[key]["net_amt"] += r.get("BILLBOARD_NET_AMT", 0) or 0
        stocks[key]["change_rate"] = r.get("CHANGE_RATE", 0)
        stocks[key]["close_price"] = r.get("CLOSE_PRICE", 0)
        stocks[key]["turnoverrate"] = max(stocks[key].get("turnoverrate", 0), r.get("TURNOVERRATE", 0) or 0)
        stocks[key]["buy_amt"] = stocks[key].get("buy_amt", 0) + (r.get("BUY_AMT") or 0)
        stocks[key]["sell_amt"] = stocks[key].get("sell_amt", 0) + (r.get("SELL_AMT") or 0)
        explain = r.get("EXPLAIN", "")
        if explain:
            stocks[key]["explains"].append(explain)
    return dict(stocks)

def detect_sector(name, all_limit_names):
    """检测板块联动"""
    matched_sector = None
    max_count = 0
    for sector, keywords in THEME_KEYWORDS.items():
        for kw in keywords:
            if kw in name:
                # 统计同板块涨停数
                count = 0
                for n in all_limit_names:
                    for k2 in keywords:
                        if k2 in n:
                            count += 1
                            break
                if count > max_count:
                    max_count = count
                    matched_sector = sector
                break
    return matched_sector, max_count

def check_repeat_lhb(code, date_str, days=3):
    """检查近N日是否重复上龙虎榜"""
    count = 0
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    for i in range(1, days + 1):
        d = dt - timedelta(days=i)
        # 跳过周末
        if d.weekday() >= 5:
            continue
        try:
            raw = fetch_lhb(d.strftime("%Y-%m-%d"))
            for r in raw:
                if r.get("SECURITY_CODE") == code:
                    net = r.get("BILLBOARD_NET_AMT", 0) or 0
                    if net < 0:  # 净卖出
                        return -1  # 机构出货
                    count += 1
            time.sleep(0.5)  # 防限流
        except:
            pass
    return count

def get_north_flow(code):
    """获取北向资金(简化版) - 用westock-data"""
    try:
        import subprocess
        result = subprocess.run(
            ["npx", "-y", "westock-data-skillhub@1.0.5", "fund", "north-holding", code],
            capture_output=True, text=True, timeout=15
        )
        output = result.stdout
        # 简化：只看最新季度持仓比例变化
        if "持股比例" in output or "%" in output:
            # 提取最新和次新的持仓比例
            lines = output.split('\n')
            ratios = []
            for line in lines:
                m = re.search(r'(\d+\.\d+)%', line)
                if m:
                    ratios.append(float(m.group(1)))
            if len(ratios) >= 2:
                return {'latest': ratios[0], 'prev': ratios[1], 'trend': 'up' if ratios[0] > ratios[1] else 'down'}
        return None
    except:
        return None

# ============== 主选股流程 ==============
def run_screener(date_str=None, enable_track=True, enable_north=False, enable_repeat=False, output_json=False):
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    def log(msg):
        if not output_json:
            print(msg)
    
    log(f"🔍 龙虎榜选股 v3.0 — {date_str}")
    log("")
    
    # 1. 获取龙虎榜
    raw = fetch_lhb(date_str)
    if not raw:
        log(f"❌ {date_str} 无龙虎榜数据")
        if output_json:
            return {"success": False, "error": "no_data", "date": date_str}
        return
    log(f"✅ 龙虎榜: {len(raw)} 条记录")
    
    # 2. 聚合
    stocks = aggregate_stocks(raw)
    
    # 3. 大盘环境
    idx_info = get_index_ma20()
    market_above = idx_info['above'] if idx_info else True
    market_dev = idx_info['dev'] if idx_info else 0
    market_status = "站上MA20✅" if market_above else "跌破MA20❌"
    log(f"📈 上证: {idx_info['close']:.2f} MA20={idx_info['ma20']:.2f} {market_status} 偏离{market_dev:.2f}%")
    
    # 动态阈值
    if market_above:
        dynamic_chg_limit = 30  # 牛市放宽
    else:
        dynamic_chg_limit = 20  # 熊市收紧
    log(f"🎯 动态5日涨幅阈值: {dynamic_chg_limit}% (基于大盘环境)")
    log("")
    
    # 4. 收集所有涨停股名称(板块联动用)
    all_limit_names = []
    for s in stocks.values():
        code = s["code"]
        is_kcb = code.startswith('688') or code.startswith('30')
        limit_pct = 19.5 if is_kcb else 9.5
        if safe_float(s["change_rate"]) >= limit_pct:
            all_limit_names.append(s["name"])
    
    # 5. 初筛 + 评分
    candidates = []
    removed = defaultdict(int)
    
    for s in stocks.values():
        code = s["code"]
        name = s["name"]
        net_amt = s["net_amt"]
        change_rate = safe_float(s["change_rate"])
        close_price = safe_float(s["close_price"])
        turnover = safe_float(s["turnoverrate"])
        explains = s.get("explains", [])
        all_explain = "；".join(explains)
        
        # === 硬过滤 ===
        if not code.startswith(('6','0','3')):
            removed["非A股"] += 1; continue
        if code.startswith('92'):
            removed["北交所"] += 1; continue
        if net_amt < 100000000:
            removed["净买<1亿"] += 1; continue
        
        is_kcb = code.startswith('688') or code.startswith('30')
        limit_pct = 19.5 if is_kcb else 9.5
        if change_rate < limit_pct:
            removed["未封板"] += 1; continue
        
        if code.startswith('688'):
            if close_price > 75: removed["科创价>75"] += 1; continue
        else:
            if close_price > 150: removed["主板价>150"] += 1; continue
        
        if 'ST' in name or '退' in name:
            removed["ST"] += 1; continue
        
        # === 市值过滤 ===
        # 简化：用收盘价粗估(无总股本数据，跳过精确市值，仅过滤明显小票)
        
        # === 机构过滤 ===
        if not explains:
            removed["无EXPLAIN"] += 1; continue
        
        if "普通席位" in all_explain and "机构" not in all_explain:
            removed["纯游资"] += 1; continue
        if "主力做T" in all_explain:
            removed["做T"] += 1; continue
        if "机构卖出" in all_explain and "机构买入" not in all_explain:
            removed["机构净卖出"] += 1; continue
        
        jigou_count = 0
        jigou_success_rate = 0
        buy_match = re.search(r'(\d+)家机构买入', all_explain)
        if buy_match:
            jigou_count = int(buy_match.group(1))
        rate_match = re.search(r'成功率(\d+\.?\d*)%', all_explain)
        if rate_match:
            jigou_success_rate = float(rate_match.group(1))
        
        if jigou_count < 1:
            removed["无机构买入"] += 1; continue
        if jigou_success_rate < 45:
            removed[f"成功率<45%"] += 1; continue
        
        # === K线指标 ===
        kline, ksource = get_kline(code, 25)
        kmetrics = calc_kline_metrics(kline, ksource, is_kcb) if kline else None
        
        chg_5d = kmetrics['chg_5d'] if kmetrics else 0
        prev_boards = kmetrics['prev_boards'] if kmetrics else 0
        ma20_dev = kmetrics['ma20_dev'] if kmetrics else 0
        prev_vol_dump = kmetrics['prev_vol_dump'] if kmetrics else False
        
        if chg_5d > dynamic_chg_limit:
            removed[f"5日涨>{dynamic_chg_limit}%"] += 1; continue
        if prev_boards >= 2:
            removed["前期板≥2"] += 1; continue
        if prev_vol_dump:
            removed["前日放量跌"] += 1; continue
        if turnover > 30:
            removed["换手>30%"] += 1; continue
        
        # === 板块联动 ===
        sector_name, sector_count = detect_sector(name, all_limit_names)
        
        # === 评分 ===
        net_yi = net_amt / 1e8
        scores = {
            'net_buy': score_net_buy(net_yi),
            'jigou_count': score_jigou_count(jigou_count),
            'jigou_rate': score_jigou_rate(jigou_success_rate),
            'chg_5d': score_chg_5d(chg_5d, dynamic_chg_limit),
            'ma20_dev': score_ma20_dev(ma20_dev),
            'turnover': score_turnover(turnover, is_kcb),
            'sector': score_sector(sector_count),
            'market': score_market(market_above, market_dev),
        }
        total_score = compute_total_score(scores)
        grade = grade_from_score(total_score)
        
        # 成交额过滤(涨停日<3亿排除)
        if kmetrics and kmetrics['vol_ratio_today'] > 0:
            # 用量比间接判断
            pass
        
        # 涨停日换手质量
        board_quality = "优质板" if (turnover <= 20 if not is_kcb else turnover <= 25) else "分歧板" if turnover <= 25 else "烂板"
        
        # 北向共振(可选)
        north_info = None
        if enable_north:
            north_info = get_north_flow(code)
            time.sleep(0.5)
        
        # 重复上榜(可选)
        repeat_info = None
        if enable_repeat:
            repeat_info = check_repeat_lhb(code, date_str)
            if repeat_info == -1:
                removed["近3日龙虎榜净卖出"] += 1
                continue
        
        candidates.append({
            'code': code, 'name': name, 'net_amt': net_amt, 'net_yi': net_yi,
            'change_rate': change_rate, 'close_price': close_price,
            'turnover': turnover, 'jigou_count': jigou_count,
            'jigou_success_rate': jigou_success_rate,
            'chg_5d': chg_5d, 'prev_boards': prev_boards,
            'ma20_dev': ma20_dev, 'board_quality': board_quality,
            'sector_name': sector_name, 'sector_count': sector_count,
            'scores': scores, 'total_score': total_score, 'grade': grade,
            'is_kcb': is_kcb, 'ksource': ksource,
            'north_info': north_info, 'repeat_info': repeat_info,
        })
    
    # 按评分排序
    candidates.sort(key=lambda x: x['total_score'], reverse=True)
    
    # 构建执行计划
    candidates_with_plan = []
    total_net = 0
    for c in candidates:
        total_net += c['net_yi']
        entry = c['close_price']
        sl = round(entry * 0.97, 2)
        tp1 = round(entry * 1.05, 2)
        tp2 = round(entry * 1.10, 2)
        
        if c['grade'] in ('A+', 'A'):
            pos = "1/3仓"
        elif c['grade'] in ('B+', 'B'):
            pos = "1/5仓"
        elif c['grade'] == 'B-':
            pos = "观察为主"
        else:
            pos = "不建议操作"
        
        # 评分明细
        score_detail = []
        for key, label in [('net_buy','净买入'), ('jigou_count','机构家数'), ('jigou_rate','成功率'),
                           ('chg_5d','5日涨幅'), ('ma20_dev','MA20偏离'), ('turnover','换手率'),
                           ('sector','板块联动'), ('market','大盘环境')]:
            weight = int(SCORE_WEIGHTS[key] * 100)
            score = c['scores'][key]
            contrib = round(score * SCORE_WEIGHTS[key], 1)
            score_detail.append({
                'key': key, 'label': label, 'score': score, 'weight': weight, 'contrib': contrib
            })
        
        sector_str = f"{c['sector_name']}({c['sector_count']})" if c['sector_name'] else "独狼"
        
        plan = {
            **c,
            'sector_str': sector_str,
            'position': pos,
            'stop_loss': sl,
            'tp1': tp1,
            'tp2': tp2,
            'score_detail': score_detail,
        }
        candidates_with_plan.append(plan)
    
    # 持仓跟踪
    track_file = None
    if enable_track:
        track_file = os.path.join(STATE_DIR, f"track_{date_str}.json")
        track_data = []
        for c in candidates:
            if c['grade'] not in ('C',):
                track_data.append({
                    'code': c['code'], 'name': c['name'],
                    'entry_date': date_str, 'entry_price': c['close_price'],
                    'grade': c['grade'], 'score': c['total_score'],
                    'stop_loss': round(c['close_price'] * 0.97, 2),
                    'tp1': round(c['close_price'] * 1.05, 2),
                    'tp2': round(c['close_price'] * 1.10, 2),
                    'days_held': 0, 'max_profit': 0, 'status': 'active',
                })
        with open(track_file, 'w') as f:
            json.dump(track_data, f, ensure_ascii=False, indent=2)
    
    # 构建结果dict
    result = {
        'success': True,
        'date': date_str,
        'version': '3.0',
        'market': {
            'index_close': idx_info['close'] if idx_info else 0,
            'ma20': idx_info['ma20'] if idx_info else 0,
            'above_ma20': market_above,
            'deviation': round(market_dev, 2),
        },
        'dynamic_chg_limit': dynamic_chg_limit,
        'screening': {
            'total_records': len(raw),
            'total_stocks': len(stocks),
            'candidates': len(candidates_with_plan),
            'removed': dict(removed),
        },
        'candidates': candidates_with_plan,
        'total_net_buy_yi': round(total_net, 1),
        'track_file': track_file,
    }
    
    if output_json:
        return result
    
    # === 控制台输出 ===
    log(f"上榜{len(stocks)}只 → 初筛后{len(candidates)}只")
    log(f"🗑 移除: {dict(removed)}")
    log("")
    
    if not candidates:
        log("## 📊 龙虎榜 · {0} · 精选0只".format(date_str))
        log("")
        log(f"{len(stocks)}只上榜 → 0只精选")
        log("")
        log("> 📌 **今日无符合标的，建议空仓观察**")
        log("")
        if not market_above:
            log(f"⚠️ 上证跌破MA20({idx_info['close']:.0f}<{idx_info['ma20']:.0f})，按20日均线框架应降低仓位/观望")
        return
    
    log(f"## 📊 龙虎榜 · {date_str} · 精选{len(candidates)}只")
    log(f"{len(stocks)}只上榜 → {len(candidates)}只精选")
    log("")
    
    # 表头
    log("| # | 代码 | 名称 | 评分 | 评级 | 净买入 | 收盘 | 5日涨 | 换手 | 机构 | 成功率 | 板块 | 板质量 |")
    log("|:--:|------|------|:--:|:--:|------|------|:--:|:--:|:--:|:--:|------|------|")
    
    for i, cp in enumerate(candidates_with_plan):
        log(f"| {i+1} | {cp['code']} | {cp['name']} | {cp['total_score']} | {cp['grade']} | {cp['net_yi']:.1f}亿 | {cp['close_price']:.2f} | {cp['chg_5d']:.1f}% | {cp['turnover']:.1f}% | {cp['jigou_count']}家 | {cp['jigou_success_rate']:.0f}% | {cp['sector_str']} | {cp['board_quality']} |")
    
    log("")
    log(f"> 📌 总净买入 **{total_net:.1f}亿**")
    log(f"> 🗑 移除: {dict(removed)}")
    log("")
    
    log("### 评分明细")
    log("")
    for cp in candidates_with_plan[:5]:
        log(f"**{cp['name']}({cp['code']}) — {cp['grade']} ({cp['total_score']}分)**")
        for sd in cp['score_detail']:
            log(f"  - {sd['label']}: {sd['score']}分 × {sd['weight']}% = {sd['contrib']}")
        extras = []
        if cp.get('north_info'):
            n = cp['north_info']
            extras.append(f"北向{'加仓' if n['trend']=='up' else '减仓'}({n['latest']:.2f}%←{n['prev']:.2f}%)")
        if cp.get('repeat_info') is not None and cp['repeat_info'] > 0:
            extras.append(f"近3日{cp['repeat_info']}次上榜")
        if extras:
            log(f"  - 附加: {', '.join(extras)}")
        log("")
    
    log("### 执行建议")
    log("")
    for cp in candidates_with_plan:
        log(f"- **{cp['name']}({cp['grade']})**: {cp['position']} | 买入区间14:30-14:50确认站上分时均线 | 止损{cp['stop_loss']}(-3%) | 止盈{cp['tp1']}(+5%减半)/{cp['tp2']}(+10%清仓)")
    
    if not market_above:
        log("")
        log("⚠️ **上证跌破MA20，整体降级，建议减半仓位或观望**")
    
    if track_file:
        log(f"\n💾 持仓跟踪已保存: {track_file}")
    
    return result

# ============== 持仓跟踪 ==============
def run_tracker(today_str=None):
    """跟踪所有active的持仓"""
    if not today_str:
        today_str = datetime.now().strftime("%Y-%m-%d")
    
    all_tracks = []
    # 扫描所有跟踪文件
    for fname in os.listdir(STATE_DIR):
        if fname.startswith("track_") and fname.endswith(".json"):
            fpath = os.path.join(STATE_DIR, fname)
            with open(fpath) as f:
                tracks = json.load(f)
                for t in tracks:
                    if t['status'] == 'active':
                        all_tracks.append((fpath, t))
    
    if not all_tracks:
        print("📭 无活跃跟踪持仓")
        return
    
    print(f"📊 龙虎榜持仓跟踪 — {today_str}")
    print()
    
    alerts = []
    for fpath, t in all_tracks:
        code = t['code']
        kline, ksource = get_kline(code, 5)
        if not kline:
            continue
        
        if ksource == 'sina':
            last_close = safe_float(kline[-1]['close'])
        else:
            last_close = safe_float(kline[-1]['close'])
        
        entry = t['entry_price']
        pnl = (last_close / entry - 1) * 100
        t['days_held'] += 1
        
        # 更新最大盈利
        if pnl > t['max_profit']:
            t['max_profit'] = round(pnl, 2)
        
        status_emoji = "🟢" if pnl > 0 else "🔴"
        
        # 止损止盈检查
        if last_close <= t['stop_loss']:
            t['status'] = 'stopped'
            alerts.append(f"⛔ {t['name']}({code}) 触发止损 {last_close}≤{t['stop_loss']}，亏损{pnl:.1f}%")
        elif last_close >= t['tp2']:
            t['status'] = 'tp2_hit'
            alerts.append(f"🎯 {t['name']}({code}) 触达止盈2 {last_close}≥{t['tp2']}，盈利{pnl:.1f}%，建议清仓")
        elif last_close >= t['tp1']:
            alerts.append(f"⚠️ {t['name']}({code}) 触达止盈1 {last_close}≥{t['tp1']}，盈利{pnl:.1f}%，建议减半仓")
        
        # 超过3天自动结束跟踪
        if t['days_held'] >= 3 and t['status'] == 'active':
            t['status'] = 'expired'
            alerts.append(f"⏰ {t['name']}({code}) 跟踪3日到期，最终{pnl:+.1f}%")
        
        print(f"  {status_emoji} {t['name']}({code}) 入场{entry}→现{last_close} {pnl:+.1f}% 第{t['days_held']}天 止损{t['stop_loss']}/止盈{t['tp1']}/{t['tp2']}")
    
    # 保存更新
    # (简化：重建所有跟踪文件)
    all_by_file = defaultdict(list)
    for fpath, t in all_tracks:
        all_by_file[fpath].append(t)
    for fpath, tracks in all_by_file.items():
        with open(fpath, 'w') as f:
            json.dump(tracks, f, ensure_ascii=False, indent=2)
    
    if alerts:
        print()
        print("### ⚡ 预警")
        for a in alerts:
            print(f"- {a}")

# ============== 回测 ==============
def run_backtest(days=60):
    """回测过去N个交易日"""
    end_date = datetime.now()
    # 获取交易日列表(简化：跳过周末)
    trade_dates = []
    d = end_date - timedelta(days=int(days * 1.5))  # 留余量
    while d <= end_date:
        if d.weekday() < 5:  # 工作日
            trade_dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    trade_dates = trade_dates[-days:]
    
    print(f"🔬 回测 {len(trade_dates)} 个交易日")
    print()
    
    results = []  # (date, stock, entry, next_close, pnl_1d, pnl_3d, pnl_5d, grade)
    
    for date_str in trade_dates:
        print(f"  处理 {date_str}...", end=" ")
        raw = fetch_lhb(date_str)
        if not raw:
            print("无数据")
            continue
        
        stocks = aggregate_stocks(raw)
        
        # 简化初筛（不做K线，只用API数据快速过滤）
        for s in stocks.values():
            code = s["code"]
            name = s["name"]
            net_amt = s["net_amt"]
            change_rate = safe_float(s["change_rate"])
            close_price = safe_float(s["close_price"])
            turnover = safe_float(s["turnoverrate"])
            explains = s.get("explains", [])
            all_explain = "；".join(explains)
            
            if not code.startswith(('6','0','3')): continue
            if code.startswith('92'): continue
            if net_amt < 100000000: continue
            is_kcb = code.startswith('688') or code.startswith('30')
            limit_pct = 19.5 if is_kcb else 9.5
            if change_rate < limit_pct: continue
            if code.startswith('688') and close_price > 75: continue
            if not code.startswith('688') and close_price > 150: continue
            if 'ST' in name or '退' in name: continue
            if turnover > 30: continue
            if not explains: continue
            if "普通席位" in all_explain and "机构" not in all_explain: continue
            if "主力做T" in all_explain: continue
            
            jigou_count = 0
            jigou_success_rate = 0
            buy_match = re.search(r'(\d+)家机构买入', all_explain)
            if buy_match: jigou_count = int(buy_match.group(1))
            rate_match = re.search(r'成功率(\d+\.?\d*)%', all_explain)
            if rate_match: jigou_success_rate = float(rate_match.group(1))
            
            if jigou_count < 1: continue
            if jigou_success_rate < 45: continue
            
            # 获取后续K线判断盈亏
            time.sleep(0.3)
            kline, ksource = get_kline(code, 15)
            if not kline or len(kline) < 8:
                continue
            
            if ksource == 'sina':
                closes = [safe_float(d['close']) for d in kline]
            else:
                closes = [safe_float(d['close']) for d in kline]
            
            # 找到入选日位置
            entry_idx = None
            for idx, d in enumerate(kline):
                day_str = d.get('day', d.get('日期', ''))
                if date_str in str(day_str):
                    entry_idx = idx
                    break
            
            if entry_idx is None:
                # 用倒数第N天近似
                continue
            
            entry_price = closes[entry_idx]
            
            pnl_1d = (closes[entry_idx + 1] / entry_price - 1) * 100 if entry_idx + 1 < len(closes) else None
            pnl_3d = (closes[min(entry_idx + 3, len(closes) - 1)] / entry_price - 1) * 100 if entry_idx + 3 <= len(closes) - 1 else None
            pnl_5d = (closes[min(entry_idx + 5, len(closes) - 1)] / entry_price - 1) * 100 if entry_idx + 5 <= len(closes) - 1 else None
            
            results.append({
                'date': date_str, 'code': code, 'name': name,
                'entry': entry_price, 'net_yi': net_amt / 1e8,
                'jigou_count': jigou_count, 'jigou_rate': jigou_success_rate,
                'turnover': turnover, 'pnl_1d': pnl_1d, 'pnl_3d': pnl_3d, 'pnl_5d': pnl_5d,
            })
        
        print(f"累计{len(results)}条")
        time.sleep(0.5)
    
    # 统计
    print()
    print("=" * 60)
    print(f"📊 回测结果汇总 ({len(results)} 条记录)")
    print("=" * 60)
    
    # 按持仓天数统计
    for period, key in [("次日", "pnl_1d"), ("3日", "pnl_3d"), ("5日", "pnl_5d")]:
        valid = [r[key] for r in results if r[key] is not None]
        if not valid:
            continue
        wins = [v for v in valid if v > 0]
        avg = sum(valid) / len(valid)
        win_rate = len(wins) / len(valid) * 100
        max_profit = max(valid)
        max_loss = min(valid)
        print(f"\n{period}表现:")
        print(f"  胜率: {win_rate:.1f}% ({len(wins)}/{len(valid)})")
        print(f"  平均收益: {avg:.2f}%")
        print(f"  最大盈利: {max_profit:.2f}%")
        print(f"  最大亏损: {max_loss:.2f}%")
        print(f"  盈亏比: {sum(wins)/len(wins)/abs(sum(v for v in valid if v<=0)/max(len(valid)-len(wins),1)):.2f}" if wins and len(valid) > len(wins) else "")
    
    # 按净买入额分组
    print("\n按净买入额分组:")
    for label, lo, hi in [("1-2亿", 1, 2), ("2-5亿", 2, 5), ("5-10亿", 5, 10), ("10亿+", 10, 999)]:
        group = [r for r in results if lo <= r['net_yi'] < hi]
        if not group: continue
        valid_3d = [r['pnl_3d'] for r in group if r['pnl_3d'] is not None]
        if valid_3d:
            wr = len([v for v in valid_3d if v > 0]) / len(valid_3d) * 100
            avg = sum(valid_3d) / len(valid_3d)
            print(f"  {label}: {len(group)}只, 3日胜率{wr:.0f}%, 平均{avg:.2f}%")
    
    # 按机构家数分组
    print("\n按机构家数分组:")
    for label, lo, hi in [("1家", 1, 2), ("2家", 2, 3), ("3家+", 3, 99)]:
        group = [r for r in results if lo <= r['jigou_count'] < hi]
        if not group: continue
        valid_3d = [r['pnl_3d'] for r in group if r['pnl_3d'] is not None]
        if valid_3d:
            wr = len([v for v in valid_3d if v > 0]) / len(valid_3d) * 100
            avg = sum(valid_3d) / len(valid_3d)
            print(f"  {label}: {len(group)}只, 3日胜率{wr:.0f}%, 平均{avg:.2f}%")
    
    # 输出详细记录到文件
    result_file = os.path.join(STATE_DIR, f"backtest_{datetime.now().strftime('%Y%m%d_%H%M')}.json")
    with open(result_file, 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n💾 详细结果已保存: {result_file}")



# ============== HTML 报告生成器 (v3 - 暗黑终端风) ==============
def generate_html_report(result, output_path=None):
    from report_v3 import build
    return build(result, output_path)

# ============== 入口 ==============
if __name__ == "__main__":
    args = sys.argv[1:]
    date_arg = None
    do_backtest = False
    backtest_days = 60
    do_track = False
    do_json = False
    do_html = False
    html_output = None

    i = 0
    while i < len(args):
        if args[i] == '--date' and i + 1 < len(args):
            date_arg = args[i + 1]
            i += 2
        elif args[i] == '--backtest':
            do_backtest = True
            if i + 1 < len(args) and args[i + 1].isdigit():
                backtest_days = int(args[i + 1])
                i += 2
            else:
                i += 1
        elif args[i] == '--track':
            do_track = True
            i += 1
        elif args[i] == '--json':
            do_json = True
            i += 1
        elif args[i] == '--html':
            do_html = True
            if i + 1 < len(args) and not args[i + 1].startswith('--'):
                html_output = args[i + 1]
                i += 2
            else:
                i += 1
        else:
            i += 1

    if do_backtest:
        run_backtest(backtest_days)
    elif do_track:
        run_tracker(date_arg)
    else:
        enable_print = not (do_json or do_html)
        result = run_screener(date_arg, enable_track=True, enable_north=False,
                              enable_repeat=False, output_json=(do_json or do_html))
        if do_json and result:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif do_html and result:
            path = generate_html_report(result, html_output)
            if path:
                print('Report saved: ' + path)
                if enable_print:
                    print('HTML report: ' + path)
            else:
                if result.get('success') == False:
                    print('No data for ' + result.get('date', 'this date'))

