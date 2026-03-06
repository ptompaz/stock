---
# 券商时钟 delay_ms（target + delay_ms）说明

## 背景：为什么要用 delay_ms
MiniQMT 返回的 `order_time`/`broker_time` 一般是**秒级**（整数秒）。你在同一秒内的不同毫秒提交单子，券商返回的 `order_time` 仍然是同一个整数秒。

实测中经常出现这样的现象：
- 本机下单调用开始 `order_call_start local=14:52:57.845`
- 券商返回 `broker_time=14:52:57`

这说明在本机已经到 `57.845s` 时，券商口径的秒级时间**仍停留在 57 秒**，即：

- `broker_time` 相对 `local_time` **落后**一段时间
- 记作：`delay_ms ≈ (local_time - broker_time) * 1000`

因此，当你希望券商返回的秒级 `order_time` 落在某个目标秒（比如 `14:54:01`）时，本机触发时间应当是：

- `local_trigger ≈ target + delay_ms`

而不是 `target - delay_ms`。

## delay_ms 的定义
- **delay_ms > 0**：券商时钟（秒口径）相对本机**落后** `delay_ms` 毫秒。
- `timed_order.py` 在读取到当日 `delay_ms` 后，会把触发时刻调整为：
  - `adjusted_target = target + delay_ms`

> 注意：这里的 `delay_ms` 是“让本机延后触发”的意思。

## 文件：broker_advance_ms.txt（按天持久化）
为避免每次下单前都测 NTP/RTT，采用一个按天持久化文件：

- 文件路径：`stock/miniqmt_order_test/broker_advance_ms.txt`
- 文件格式：每行一个日期

```text
YYYY-MM-DD=delay_ms
```

例如：
```text
2026-03-06=845
```

`timed_order.py` 会按 `--date`（不传则今天）读取当日值：
- 读到：直接使用，并**跳过 ping/NTP**
- 读不到：视为 0（不做调整），或者你可用 `--calibrate` 走原来的 ping/NTP

## 如何生成当日 delay_ms（estimate_broker_ntp_offset.py）
这个脚本通过“低风险/废单式”的方式反复下单并查询 `order_time`，做步进逼近（默认 `step_ms=5`）来找到让券商秒级时间跨秒的临界点，从而得到一个可用的 `delay_ms`。

运行（真实下单）：

```powershell
python estimate_broker_ntp_offset.py --live --confirm YES
```

你会看到类似输出：
- `test delay_ms=...`
- `order_call_start local=...`
- `broker_order_time_sec=... broker_time=...`
- 最终：`delay_ms_estimates=[...] median=...`
- 并自动写入：
  - `saved broker delay to ...\broker_advance_ms.txt: YYYY-MM-DD=<median>`

## 如何使用 timed_order.py（自动读取 delay_ms）
当 `broker_advance_ms.txt` 有当天值时，直接下单即可：

```powershell
python timed_order.py --at 14:54:01.000 --code 601059.SH --side sell --volume 100 --price 19.0 --live --confirm YES
```

你应该看到：
- `delay_ms=845.000 (broker_advance_ms.txt 2026-03-06), adjusted_target=2026-03-06 14:54:01.845000`
- 然后在 `14:54:01.845xxx` 左右触发 `TRIGGER`

## 常见误区
- 误区 1：把 `delay_ms` 当成“提前量”
  - 如果你用 `target - delay_ms`，会导致本机提前触发，从而券商更可能回到“前一秒”的 `order_time`。

- 误区 2：用本机毫秒去直接对齐券商秒
  - 券商返回是秒级，只能用“跨秒边界”的方法去推一个稳定的 `delay_ms`。

- 误区 3：不同时间测出来值不一样
  - 网络/柜台排队/系统负载会引入抖动，所以脚本用多次验证并用 `median` 落地到文件。
