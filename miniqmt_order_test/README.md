# miniQMT 下单流程冒烟测试

## QMT_PATH 环境变量（推荐）

本目录脚本默认会读取环境变量 `QMT_PATH` 作为 `--qmt-path` 的默认值；若未设置则回退到 `F:\stock\qmt\userdata_mini`。

### cmd.exe

当前窗口临时生效：

```bat
set QMT_PATH=F:\stock\qmt\userdata_mini
echo %QMT_PATH%
```

写入用户环境变量（新开 cmd 才生效）：

```bat
setx QMT_PATH "F:\stock\qmt\userdata_mini"
```

### PowerShell

当前窗口临时生效：

```powershell
$env:QMT_PATH = "F:\stock\qmt\userdata_mini"
$env:QMT_PATH
```


本目录用于测试 `xtquant.xttrader` 通过本机 MiniQMT/QMT 进行：

- 连接/启动交易会话
- 查询资金/持仓/委托/成交
- （可选）发出一笔真实委托（默认不下单）

## 目录内文件说明（逐个）


使用方式
校准时间在调用
python estimate_broker_ntp_offset.py --live --confirm YES
然后
python timed_order.py --at 09:15:00 --code 601059.SH --side sell --volume 100 --price 19.5 --calibrate --live --confirm YES
来枪单

### 1）`place_order.py`

用途：

- 连接交易服务
- 查询资金/持仓/委托/成交
- 可选下单（默认不下单）

用法（单行）：

buy
>python place_order.py --side buy --stockid 601995.SH --price 33.5  --volume 1000 --account-id 31161458 --live --confirm YES --error-wait-ms 5000

sell
python place_order.py --side sell --stockid 601995.SH --price 35.5  --volume 1000 --account-id 31161458 --live --confirm YES --error-wait-ms 5000

可转债
python place_order.py --side buy --stockid 113033.SH --price 109.1  --volume 500 --account-id 31161458 --live --confirm YES --error-wait-ms 5000


增加一个探测可用状态的，夜间委托使用
python place_order.py --wait-until-ready ^
  --probe-code 601059.SH --probe-price 0.01 --probe-volume 100 --probe-interval 5 --probe-max-tries 0 ^
  --side buy --stockid 113033.SH --price 109.1 --volume 10 --account-id 31161458 ^
  --live --confirm YES --error-wait-ms 5000


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
python timed_order.py --at 14:48:01 --code 601995.SH --side sell --volume 1000 --price 35.5 --live --confirm YES
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
python timed_order.py --at 12:55:32.100 --code 601059.SH --side buy --volume 100 --price 17.0 --calibrate --live --confirm YES --retry-times 1
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

#### 测试“券商时钟/柜台口径时间”相对本机/NTP 的偏差（秒级）

说明：

- 你在券商界面看到的下单时间，通常更接近 `query_stock_orders` 返回的 `order_time`。
- `order_time` 是 Unix 时间戳（秒），只有秒级粒度，常见口径是“柜台受理时间/入队时间”，并可能存在取整/截断。
- 因为只有秒级，下面方法的目标是估算：券商侧时间与本机时间的“秒级偏差/截断边界”，不是毫秒级精准对时。

步骤（建议先小风险标的/小数量测试，且每次只发 1 次）：

1）选择一个未来的“整秒”目标时刻 `T`（例如 `12:27:22.000`）。

2）用不同毫秒偏移去试探，例如 `T+0ms / +50ms / +100ms / +150ms ...`：

```bash
python timed_order.py --at 12:27:22.000 --code 601059.SH --side buy --volume 100 --price 17.0 --calibrate --live --confirm YES --retry-times 1
python timed_order.py --at 12:27:22.050 --code 601059.SH --side buy --volume 100 --price 17.0 --calibrate --live --confirm YES --retry-times 1
python timed_order.py --at 12:27:22.100 --code 601059.SH --side buy --volume 100 --price 17.0 --calibrate --live --confirm YES --retry-times 1
python timed_order.py --at 12:27:22.150 --code 601059.SH --side buy --volume 100 --price 17.0 --calibrate --live --confirm YES --retry-times 1
```

3）每次下单后，用 `query_orders_today.py` 或你自己的查询方式拿到对应订单的 `order_time`，并换算成北京时间 `HH:MM:SS`。

4）观察：当你逐步增加 `mmm` 时，`order_time` 显示的秒数会在某个阈值附近从 `...:SS-1` 跳到 `...:SS`。

经验解释：

- 如果你在本机看到 `TRIGGER` 已经是 `...:SS.xxx`，但 `order_time` 仍落在 `...:SS-1`，通常意味着券商端口径时间相对本机“更慢/更早”，或其取整边界更偏向上一秒。
- 通过“发生跳变的最小偏移毫秒”可以估计一个秒级差异（例如约 1s 内的偏差/截断边界）。

注意：

- 一定使用 `--retry-times 1`，否则会一次产生多笔委托，扰乱统计。
- 只看 `order_time`（秒）无法得到毫秒级对时结论；要毫秒级只能依赖交易所回报时间字段（若系统有提供）或更底层网关日志。


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

需要Python 3.12.10


pip install xtquant
pip install ntplib
pip install icmplib

