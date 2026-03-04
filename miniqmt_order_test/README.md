# miniQMT 下单流程冒烟测试

本目录用于测试 `xtquant.xttrader` 通过本机 MiniQMT/QMT 进行：

- 连接/启动交易会话
- 查询资金/持仓/委托/成交
- （可选）发出一笔真实委托（默认不下单）

## 目录内文件说明（逐个）

### 1）`order_smoke_test.py`

用途：

- 连接交易服务
- 查询资金/持仓/委托/成交
- 可选下单（默认不下单）

用法（单行）：

```bash
python order_smoke_test.py --qmt-path "F:\stock\qmt\userdata_mini" --account-id "31161458" --query-only --wait 2
```

真实下单（高风险，需要显式开启）：

```bash
python order_smoke_test.py --qmt-path "F:\stock\qmt\userdata_mini" --account-id "31161458" --live --confirm YES --code 000001.SZ --side buy --volume 100 --limit --price 10.23
```

### 2）`sell_601059_100_at_17_5.py`

用途：最简“固定参数卖出”脚本（只做卖单动作，不做查询）。

- 固定：卖出 `601059.SH`、`100` 股、限价 `17.5`
- 默认 dry-run

用法：

```bash
python sell_601059_100_at_17_5.py
```

真实下单：

```bash
python sell_601059_100_at_17_5.py --live --confirm YES
```



### 4）`timed_order.py`  抢涨停，lgh
用途：通用“定时触发下单”脚本。

- 先启动并 `connect()` 预热连接
- 按本机时间卡点到 `--at` 后立刻触发下单（也支持校准后提前触发，见下方 `--calibrate`）
- 参数化：`--code/--side/--volume/--price/--at`
- 默认 dry-run

用法（dry-run，到点只触发不下单）：

```bash
python timed_order.py --at 14:48:01 --code 601059.SH --side sell --volume 100 --price 17.5
```

真实下单：

```bash
python timed_order.py --at 14:48:01 --code 601059.SH --side sell --volume 100 --price 17.5 --live --confirm YES
```

可选：开启“校准触发”（在本机提前触发，目标是在券商机房更接近 0 秒）

- 先 `ping` 券商主机得到 `avg_rtt_ms`，取 `rtt_half_ms = avg_rtt_ms/2`
- 再请求 NTP 得到本机相对 NTP 的偏移 `ntp_offset_ms`
- 计算提前量：

  - `advance_ms = ntp_offset_ms + rtt_half_ms`
  - `adjusted_target = target - advance_ms`

示例（真实下单 + 校准）：

```bash
python timed_order.py --at 09:15:00 --code 601059.SH --side sell --volume 100 --price 17.5 --calibrate --live --confirm YES
```

校准参数（默认值就是你当前常用口径）：

- `--broker-host`（默认 `139.224.114.71`）
- `--ping-count`（默认 `5`）
- `--ping-timeout-ms`（默认 `50`）
- `--ntp-servers`（默认 `ntp.aliyun.com,ntp1.aliyun.com`）
- `--ntp-timeout-ms`（默认 `500`）

校准说明：

- `--calibrate` 是可选开关，不开则完全按本机 `--at` 卡点触发。
- 任一环节失败会自动降级为 `advance_ms=0`（不影响脚本运行，只是不提前）。
- 符号口径：`ntp_offset_ms > 0` 表示“本机时间比 NTP 早”，因此脚本会做“提前触发”（从目标时刻减去该值）。


### 6）`ntp_detect.py`

用途：检测和ntp服务器的误差。

用法：

```bash
python ntp_detect.py
```

可以用w32tm /stripchart /computer:ntp.aliyun.com /samples:5 /dataonly 来做验证
### 7）`icmp_ping.py`

用途：独立的 ICMP ping 测试脚本（用于测券商主机 RTT，并输出 `RTT/2`）。

用法：

```bash
python icmp_ping.py --host 139.224.114.71 --count 5 --timeout-ms 50
```

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
