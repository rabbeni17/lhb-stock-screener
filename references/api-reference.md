# 东方财富龙虎榜 API 参考

## API 端点

### 1. 龙虎榜个股汇总（主力接口）
```
GET https://datacenter-web.eastmoney.com/api/data/v1/get
参数:
  reportName=RPT_DAILYBILLBOARD_DETAILSNEW
  columns=ALL
  pageNumber=1
  pageSize=500
  sortTypes=-1
  sortColumns=BILLBOARD_NET_AMT
  filter=(TRADE_DATE='YYYY-MM-DD')
```

返回字段速查：
- `SECURITY_CODE`: 股票代码
- `SECURITY_NAME_ABBR`: 简称
- `CLOSE_PRICE`: 收盘价
- `CHANGE_RATE`: 涨跌幅(%) — 基于前收，用于封板判断
- `BILLBOARD_NET_AMT`: 龙虎榜净买入(元)
- `BILLBOARD_BUY_AMT`: 买入额(元)
- `BILLBOARD_SELL_AMT`: 卖出额(元)
- `EXPLAIN`: 解读文本（含机构数+成功率）
- `TURNOVERRATE`: 换手率(%) — **可能为None，需safe_float处理**
- `D5_CLOSE_ADJCHRATE`: 5日涨跌幅 — **不可靠，常返回0，需K线自算**
- `D1_CLOSE_ADJCHRATE`: 1日涨跌幅
- `D2_CLOSE_ADJCHRATE`: 2日涨跌幅
- `D10_CLOSE_ADJCHRATE`: 10日涨跌幅
- `MARKET`: 交易所 SH/SZ
- `SECUCODE`: 代码.市场 (如 002245.SZ)
- `SECURITY_TYPE_CODE`: 证券类型

### EXPLAIN 字段模式
常见模式及处理：
- `"N家机构买入，成功率X%"` → 保留（N≥1且X≥45%）
- `"N家机构卖出，成功率X%"` → 排除（机构净卖出）
- `"普通席位买入，成功率X%"` → 排除（纯游资）
- `"普通席位卖出，成功率X%"` → 排除
- `"主力做T，成功率X%"` → 排除（做T=日内对冲，非真实看多）
- `"卖一主卖，成功率X%"` → 排除
- 组合：`"N家机构买入，M家机构卖出"` → 保留（有机构买入即可）

### 数据聚合注意事项
- 同一股票可能有多条记录（不同上榜原因），需按 `SECURITY_CODE` 聚合 `BILLBOARD_NET_AMT`
- 单位：`BILLBOARD_NET_AMT` 返回元，需 `/10000` 转为万
- 换手率取多条记录中的最大值
- 排除非股票：可转债(12xxxx/11xxxx)、B股(20xxxx)、北交所(920xxx)、退市股

## K线数据获取

### 2. 东方财富push2his K线（主用，个股）
```
GET https://push2his.eastmoney.com/api/qt/stock/kline/get
参数:
  secid={market}.{code}  # 沪市1.xxx, 深市0.xxx
  fields1=f1,f2,f3,f4,f5,f6
  fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61
  klt=101          # 101=日K
  fqt=1            # 前复权
  end=20500101
  lmt={N}          # 返回条数
```
返回格式：klines数组，每行 `"日期,开,收,高,低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率"`
- 涨跌幅是前收→今收，与LHB的CHANGE_RATE一致
- **注意**：频率限制较严，连续请求可能被断连（RemoteDisconnected），需加1秒间隔
- **上证指数**：secid=1.000001，但限流更严，建议用新浪API替代

### 3. 新浪财经K线（备用，个股+指数）
```
GET https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData
参数:
  symbol={sh/sz}{code}  # sh000001=上证指数, sz002245=个股
  scale=240             # 240=日K
  ma=no
  datalen={N}           # 返回条数
```
返回JSON数组，每条：`{day, open, close, high, low, volume}`
- **编码GBK**，需 `resp.read().decode('gbk')` 后 json.loads
- 无涨跌幅字段，需自行计算：`(close/open-1)*100` 或用前后日收盘比
- 稳定可靠，不限流
- **上证指数推荐用此API**：`symbol=sh000001&datalen=25`

### 4. westock-data CLI（不稳定）
```bash
npx -y westock-data-skillhub@1.0.3 kline <code> --period day --limit 6
```
- 对个股**常返回"数据为空"**，不推荐依赖
- 上证指数 `sh000001` 偶尔可用
- 字段：symbol | date | open | last | high | low | volume | amount | exchange

## 关键计算

### 涨停判断
- 龙虎榜API的 `CHANGE_RATE`：前收→今收，主板≥9.5% / 创业板科创板≥19.5%
- K线自算：今日收盘/昨日收盘-1，同样阈值
- **不要用Sina的开→收涨幅判断封板**（open→close≠前收→今收）

### 5日涨幅
- 必须从K线计算：`(今日收盘 / 5个交易日前收盘 - 1) × 100`
- 不要依赖 `D5_CLOSE_ADJCHRATE`（可能为0或不准）

### MA20计算
- 取最近20个交易日收盘价均值
- 需至少拉25日K线才能算出可靠的MA20

### 前期涨停板
- 遍历K线（排除当日），涨幅≥9.5%(主板)或≥19.5%(创业/科创)计为1个
- 用K线收盘/前日收盘计算，非open→close

### 前日放量下跌
- 前日成交量 / 前6日至前2日平均量 > 1.5
- 且前日收盘 < 前日开盘（下跌）

## 股票分类规则
- 科创板: 代码以688开头 → 涨停20%, 价格上限75
- 创业板: 300/301开头 → 涨停20%, 价格上限150
- 主板: 其余 → 涨停10%, 价格上限150
- 北交所: 920开头 → 排除（流动性差）
- ST: 名称含"ST"或"退" → 直接排除

## 板块联动关键词分组
```python
theme_keywords = {
    '半导体/芯片': ['芯片', '半导体', '微', '电子', '集成', '科技'],
    '新能源/锂电': ['锂', '电池', '新能源', '光伏', '储能'],
    '军工/航天': ['航天', '航空', '军工', '中航', '兵器'],
    '通信/算力': ['通信', '算力', '服务器', '数据中心', '长城'],
    '材料/化工': ['材料', '化学', '化工', '纤维', '氟'],
    '机械/自动化': ['机械', '装备', '自动化', '机器人'],
}
```
- 每只涨停股按名称匹配关键词归入板块
- 同板块≥3只涨停=强联动；1只=独狼（降级）
