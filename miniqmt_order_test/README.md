# miniQMT 下单流程冒烟测试

本目录用于测试 `xtquant.xttrader` 通过本机 MiniQMT/QMT 进行：

- 连接/启动交易会话
- 查询资金/持仓/委托/成交
- （可选）发出一笔真实委托（默认不下单）

## 前置条件

- 已安装并能正常登录 MiniQMT/QMT（普通股票账户）。
- 本机 Python 已可 `import xtquant`。

## 运行方式

### 1）仅连接 + 查询（默认，安全）

```bash
python order_smoke_test.py --qmt-path "<MiniQMT用户数据目录或安装目录>" --account-id "<资金账号/证券账号>" --query-only --wait 2
```

### 2）真实下单（高风险：需要显式开启）

脚本默认 `--dry-run`，只有同时满足以下条件才会真实下单：

- 传 `--live`
- 传 `--confirm YES`

示例：

```bash
python order_smoke_test.py --qmt-path "<MiniQMT用户数据目录或安装目录>" --account-id "<资金账号/证券账号>" --live --confirm YES --code 000001.SZ --side buy --volume 100 --limit --price 10.23
```

## 参数说明

- `--qmt-path`
  - 传给 `XtQuantTrader(path=...)` 的路径。
  - 不同券商/安装方式可能不同；如果报连接错误，优先用你实际的 MiniQMT/QMT 工作目录/用户数据目录尝试。
- `--account-id`
  - `StockAccount(account_id=...)` 的 `account_id`。
  - 以你在券商侧看到的资金账号/证券账号为准。

## 注意事项

- 本脚本不尝试“选择 LDP/VIP 通道”。是否走 LDP 属于券商侧账户/席位配置；既然你已开通 LDP，通常由券商侧切换完成。
- 如果你希望做延迟统计，请在回调 `on_order_stock_async_response / on_stock_order / on_stock_trade` 等事件里打本机时间戳，并结合回报字段做对比（不同券商字段不同）。
