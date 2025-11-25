项目目标：构建一个策略池（Strategy Pool），AI 智能体作为“策略调度官”，根据当前市场行情（Market Regime）与舆情（Sentiment），评估各策略的历史/近期表现，动态选择当前最适合运行的子策略。

技术栈：
    - 编程语言：python；
    - 数据库：postgresql;
    - 数据源：from massive import RESTClient
    - 交易接口：Bronco Trade_Contract_API
    - 模块间的数据格式：json
    - AI大模型：deepseek
    - 开发环境：wsl debian 13
    - 测试环境：云服务器 debian 13
    - 代码仓库：github + CICD流水线
    - 交易界面：python rich库

项目构成：
    1. 选股模块：
        - 手动设定交易范围：当前目标交易范围是NASDAQ 100。https://www.nasdaq.com/market-activity/quotes/nasdaq-ndx-index
        - 手动设定选股指标，人工撰写postgresql的查询语句；
            - 行情数据：trade、quotes。
            - （以后再扩展）行情技术指标：SMA、EMA、RSI、MACD。
            - {策略模块时间频率参数}：10分钟、15分钟、30分钟、60分钟；
        - 每到策略模块时间频率参数，就执行postgresql的查询语句，将结果写入{当前时间戳+时间频率参数}.json文件。
        - 将{当前时间戳+时间频率参数}.json文件传递给策略模块。

    2. Data模块：利用选股模块程式化选择符合要求的股票，将对应时段的行业数据与舆情数据，打包合并发送给策略模块。
        2.1 数据API库: from massive import RESTClient
        2.2 API_KEY: {MASSIVE_API_KEY}。
        2.3 数据库：postgresql。
        2.3 采集范围：NASDAQ 100。
        2.4 采集数据时间频率：每分钟采集一次，秒级数据，写入数据库。休市时间不采集。
        2.5 行情数据：
            - 交易数据有：trade、quotes，数据结构见官方文档。
            - （以后再扩展）技术指标数据有：SMA、EMA、RSI、MACD，数据结构见官方文档。
        2.6 舆情数据，注意应当排除舆情数据可能是空数据和重复数据的情况，避免写入数据库。
        2.7 按{采集数据时间频率参数}，将行情数据和舆情数据写入数据库。
        2.8 采集的时间要求:
            2.8.1 采集的时间应当是美股的开市时间。需注意夏令时和冬令时。时区是东部时间ET。
            2.8.2 交易时间：
                - 常规交易时段（Regular Trading Hours）周一到周五：09:30 – 16:00（美国东部时间 ET）
                - 盘前交易（Pre-market）04:00 – 09:30 ET
                - 盘后交易（After-hours）16:00 – 20:00 ET
            2.8.3 休市时间：
                - 美国节假日
                - 美国其他休市时间
            2.8.4 采集的时间要求直接写在一个文件中，方便后续修改。


    3. AI 调度模块（原策略模块）：
        3.1 核心职责：AI 不直接生成买卖信号，而是作为“策略调度官”。
        3.2 输入数据：
            - 宏观/个股行情特征（波动率 VIX、趋势强度 ADX、量能）。
            - 舆情情绪得分。
            - **策略表现矩阵**：策略库中所有策略在过去 [1小时, 4小时, 24小时] 的虚拟回报率与最大回撤。
        3.3 决策逻辑：
            - 识别市场体制 (Market Regime Classification)。
            - 优选策略 (Strategy Selection)。
        3.4 输出指令格式：
            {
                "action": "switch_strategy", 
                "selected_strategy_id": "mean_reversion_v1",
                "reason": "Market is in high volatility oscillation, trend strategies are failing.",
                "risk_weight": 0.5  // 建议仓位权重
            }
    4. 量化策略库：
        4.1 包含多种逻辑互斥的经典策略（硬编码或参数化脚本）：
            - 趋势类：MACD 交叉、均线突破。
            - 震荡类：RSI 超买超卖、布林带回归。
            - 动量类：开盘区间突破 (ORB)。
        4.2 运行机制：
            - 所有策略在后台对目标股票进行全天候“虚拟运行”。
            - 实时计算每个策略的理论盈亏曲线，生成“策略表现矩阵”传给 AI。
        4.3 信号生成：
            - 被 AI 选中的“当前活跃策略”才有权限向交易模块发送真实的下单指令。

    5. 交易动作模块：
        5.1 接收 AI 调度模块的“当前活跃策略”，向交易模块发送真实的下单指令。
        5.2 交易模块解析 json 指令，通过 Bronco Trade_Contract_API 下单。

    6. 观察与交互模块：
        使用tradingagent的UI界面，观察AI的分析状态、交易动作，以及AI交易的历史记录。





---
顺带一个小优化建议
既然你策略模块真正用的是 10/15/30/60 分钟的特征，可以在 Data / 特征层做一个优化：
原始逐笔（trades/quotes）全部存 PostgreSQL（便于回测）；
另外再建一张“已聚合好的 K 线/特征表”（比如 1 分钟 / 10 分钟 bar），
Data 或特征服务定时从原始表聚合，
策略模块查询时优先读“聚合表”，而不是原始逐笔表。
这样：
原始表可以保留更长时间用于研究；
聚合表体积小、查询快，策略决策时压力更小。