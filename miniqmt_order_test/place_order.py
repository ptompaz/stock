from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Optional

from qmt_config import get_qmt_path

from xtquant import xtconstant
from xtquant import xttrader
from xtquant.xttype import StockAccount


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _obj_to_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _obj_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_obj_to_dict(v) for v in obj]
    if hasattr(obj, "__dict__"):
        return {k: _obj_to_dict(v) for k, v in vars(obj).items()}
    return str(obj)


def _fmt_obj(obj: Any) -> str:
    return json.dumps(_obj_to_dict(obj), ensure_ascii=False, indent=2)


def _normalize_code(code: str, default_exchange: str) -> str:
    code = code.strip().upper()
    if "." in code:
        return code
    ex = default_exchange.strip().upper()
    if ex not in ("SH", "SZ"):
        ex = "SH"
    return f"{code}.{ex}"


def _guess_lot_size(code: str) -> int:
    c = code.split(".")[0]
    if c.startswith(("11", "12")):
        return 10
    return 100


class Callback(xttrader.XtQuantTraderCallback):
    """简化版回调，仅用于打印错误信息（不用于等待订单）"""

    def __init__(self) -> None:
        super().__init__()
        self._last_error: Optional[Any] = None
        self._error_time: Optional[float] = None

    def on_order_error(self, order_error):
        """记录并打印错误"""
        self._last_error = order_error
        self._error_time = time.time()
        try:
            fields = {
                "error_id": getattr(order_error, "error_id", None),
                "error_msg": getattr(order_error, "error_msg", None),
                "m_strErrorMsg": getattr(order_error, "m_strErrorMsg", None),
                "m_nErrorID": getattr(order_error, "m_nErrorID", None),
                "order_id": getattr(order_error, "order_id", None),
                "seq": getattr(order_error, "seq", None),
                "strategy_name": getattr(order_error, "strategy_name", None),
                "order_remark": getattr(order_error, "order_remark", None),
                "account_id": getattr(order_error, "account_id", None),
            }
        except Exception:
            fields = None
        if fields:
            print(f"[{_now_str()}] on_order_error fields:\n{json.dumps(fields, ensure_ascii=False, indent=2)}")
        else:
            print(f"[{_now_str()}] on_order_error: {repr(order_error)}")

    def on_stock_order(self, order):
        """仅打印订单信息，不用于等待"""
        print(f"[{_now_str()}] on_stock_order (收到回调但忽略):\n{_fmt_obj(order)}")

    def get_last_error_since(self, since_ts: float) -> Optional[Any]:
        """获取指定时间之后的错误"""
        if self._last_error and self._error_time and self._error_time >= since_ts:
            err = self._last_error
            self._last_error = None
            return err
        return None


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="通过QMT下单，然后主动查询订单状态（不依赖回调等待）。"
    )

    p.add_argument("--side", required=True, choices=["buy", "sell"], help="买入或卖出")
    p.add_argument("--stockid", "--code", dest="code", required=True, help="股票代码，如 601059.SH 或 113033.SH")
    p.add_argument("--price", type=float, required=True, help="委托价格（限价单）")
    p.add_argument("--volume", type=int, required=True, help="委托数量")

    p.add_argument("--qmt-path", default=get_qmt_path(), help="QMT用户目录路径")
    p.add_argument("--session", type=int, default=1, help="XtQuantTrader 会话ID (整数)")
    p.add_argument("--account-id", required=True, help="资金账号")

    p.add_argument("--default-exchange", default="SH", choices=["SH", "SZ"], help="当代码不带后缀时使用的默认交易所")
    p.add_argument("--lot-size", type=int, default=0, help="手数检查，0表示自动推断")

    p.add_argument("--live", action="store_true", help="实际下单（否则为试运行）")
    p.add_argument("--confirm", default="", help="必须为 YES 才能实际下单")

    p.add_argument("--price-type", type=int, default=2, choices=[1, 2], help="1=市价, 2=限价")
    p.add_argument("--strategy-name", default="place_order", help="策略名称")
    p.add_argument("--remark", default="", help="委托备注")

    p.add_argument("--error-wait-ms", type=int, default=1000, help="下单失败后等待错误回调的毫秒数")
    p.add_argument("--query-retries", type=int, default=3, help="查询订单的最大重试次数")
    p.add_argument("--query-interval", type=float, default=1.0, help="每次查询之间的间隔秒数")
    p.add_argument("--cancelable-only", action="store_true", help="查询时是否只返回可撤订单")

    return p.parse_args()


def main() -> int:
    args = _parse_args()

    if not os.path.isdir(args.qmt_path):
        print(f"[{_now_str()}] ERROR: qmt-path 不存在或不是目录: {args.qmt_path}")
        return 2

    if args.live and args.confirm != "YES":
        print(f"[{_now_str()}] ERROR: 实际下单需要 --confirm YES")
        return 2

    # 标准化股票代码
    code = _normalize_code(args.code, args.default_exchange)

    # 手数检查
    lot_size = args.lot_size if args.lot_size > 0 else _guess_lot_size(code)
    if lot_size > 0 and args.volume % lot_size != 0:
        print(f"[{_now_str()}] ERROR: 数量 {args.volume} 必须是手数 {lot_size} 的整数倍，代码 {code}")
        return 2

    order_type = xtconstant.STOCK_BUY if args.side == "buy" else xtconstant.STOCK_SELL

    print(f"[{_now_str()}] 参数: side={args.side} code={code} price={args.price} volume={args.volume} price_type={args.price_type}")
    print(f"[{_now_str()}] QMT路径: {args.qmt_path} 账号: {args.account_id}")

    if not args.live:
        print(f"[{_now_str()}] 试运行模式，不实际下单。使用 --live --confirm YES 来实际下单。")
        return 0

    # 初始化回调与交易接口
    cb = Callback()
    trader = xttrader.XtQuantTrader(args.qmt_path, int(args.session), cb)

    try:
        trader.start()
        trader.connect()

        account = StockAccount(args.account_id)

        # 下单
        submit_start_ts = time.time()
        price_type = xtconstant.LATEST_PRICE if args.price_type == 1 else xtconstant.FIX_PRICE

        order_id = trader.order_stock(
            account=account,
            stock_code=code,
            order_type=order_type,
            order_volume=int(args.volume),
            price_type=price_type,
            price=float(args.price),
            strategy_name=args.strategy_name,
            order_remark=args.remark,
        )

        print(f"[{_now_str()}] order_stock 返回 order_id={order_id}")

        # 如果返回的订单ID无效（<=0），检查错误回调
        if not order_id or int(order_id) <= 0:
            # 等待一小段时间查看是否有错误回调
            time.sleep(args.error_wait_ms / 1000.0)
            err = cb.get_last_error_since(submit_start_ts)
            if err:
                print(f"[{_now_str()}] 收到下单错误:\n{_fmt_obj(err)}")
            else:
                print(f"[{_now_str()}] 未收到错误回调，下单可能失败但无详细信息。")
            return 1

        # 主动查询订单状态（重试多次）
        found_order = None
        for attempt in range(1, args.query_retries + 1):
            print(f"[{_now_str()}] 查询订单 (第 {attempt} 次)...")
            try:
                orders = trader.query_stock_orders(account, cancelable_only=args.cancelable_only)
                # 筛选目标订单
                for o in orders:
                    o_id = getattr(o, "order_id", None) or getattr(o, "m_nOrderID", None)
                    if o_id == int(order_id):
                        found_order = o
                        break
                if found_order:
                    break
            except Exception as e:
                print(f"[{_now_str()}] 查询订单时出错: {e}")

            if attempt < args.query_retries:
                time.sleep(args.query_interval)

        if found_order:
            print(f"[{_now_str()}] 查询到订单状态:\n{_fmt_obj(found_order)}")
            # 可以进一步检查订单状态码等
            return 0
        else:
            print(f"[{_now_str()}] 在 {args.query_retries} 次查询后仍未找到订单 ID={order_id}")
            return 1

    except KeyboardInterrupt:
        print(f"[{_now_str()}] 用户中断")
        return 130
    except Exception as e:
        print(f"[{_now_str()}] 异常: {e}")
        return 1
    finally:
        try:
            trader.stop()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())