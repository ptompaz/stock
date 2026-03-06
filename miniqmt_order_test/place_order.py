from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Dict, Optional

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
    def __init__(self) -> None:
        super().__init__()
        self._last_error: Optional[Dict[str, Any]] = None

    def on_order_error(self, order_error):
        self._last_error = {"ts": time.time(), "data": order_error}
        print(f"[{_now_str()}] on_order_error:\n{_fmt_obj(order_error)}")

    def on_stock_order(self, order):
        print(f"[{_now_str()}] on_stock_order:\n{_fmt_obj(order)}")

    def consume_last_error_since(self, since_ts: float) -> Optional[Any]:
        if not self._last_error:
            return None
        if self._last_error["ts"] < since_ts:
            return None
        data = self._last_error["data"]
        self._last_error = None
        return data


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()

    p.add_argument("--side", required=True, choices=["buy", "sell"], help="buy or sell")
    p.add_argument("--stockid", "--code", dest="code", required=True, help="e.g. 601059.SH or 113033.SH")
    p.add_argument("--price", type=float, required=True, help="limit price")
    p.add_argument("--volume", type=int, required=True, help="order volume")

    p.add_argument("--qmt-path", default=r"F:\\stock\\qmt\\userdata_mini")
    p.add_argument("--session", type=int, default=1, help="XtQuantTrader session id (int)")
    p.add_argument("--account-id", required=True)

    p.add_argument("--default-exchange", default="SH", choices=["SH", "SZ"])
    p.add_argument("--lot-size", type=int, default=0, help="override lot size check; 0 means auto")

    p.add_argument("--live", action="store_true", help="actually submit order")
    p.add_argument("--confirm", default="", help="must be YES when --live")

    p.add_argument("--price-type", type=int, default=2, help="1=market, 2=limit")
    p.add_argument("--strategy-name", default="place_order")
    p.add_argument("--remark", default="")

    p.add_argument("--error-wait-ms", type=int, default=1000)

    return p.parse_args()


def main() -> int:
    args = _parse_args()

    if not os.path.isdir(args.qmt_path):
        print(f"[{_now_str()}] ERROR: qmt-path not found or not a directory: {args.qmt_path}")
        return 2

    if args.live and args.confirm != "YES":
        print(f"[{_now_str()}] ERROR: live mode requires --confirm YES")
        return 2

    code = _normalize_code(args.code, args.default_exchange)

    lot_size = args.lot_size if args.lot_size > 0 else _guess_lot_size(code)
    if lot_size > 0 and args.volume % lot_size != 0:
        print(f"[{_now_str()}] ERROR: volume={args.volume} must be multiple of lot_size={lot_size} for {code}")
        return 2

    order_type = xtconstant.STOCK_BUY if args.side == "buy" else xtconstant.STOCK_SELL

    print(f"[{_now_str()}] params: side={args.side} code={code} price={args.price} volume={args.volume} price_type={args.price_type}")
    print(f"[{_now_str()}] qmt_path={args.qmt_path} account_id={args.account_id}")

    if not args.live:
        print(f"[{_now_str()}] DRY-RUN: not submitting order. Use --live --confirm YES to submit.")
        return 0

    cb = Callback()
    trader = xttrader.XtQuantTrader(args.qmt_path, int(args.session), cb)

    try:
        trader.start()
        trader.connect()

        account = StockAccount(args.account_id)

        submit_start_ts = time.time()
        price_type = None
        if int(args.price_type) == 1:
            price_type = xtconstant.LATEST_PRICE
        elif int(args.price_type) == 2:
            price_type = xtconstant.FIX_PRICE
        else:
            price_type = int(args.price_type)

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

        print(f"[{_now_str()}] order_stock returned order_id={order_id}")

        if not order_id or int(order_id) <= 0:
            deadline = time.time() + max(0, args.error_wait_ms) / 1000.0
            while time.time() < deadline:
                err = cb.consume_last_error_since(submit_start_ts)
                if err is not None:
                    print(f"[{_now_str()}] ERROR_DETAIL:\n{_fmt_obj(err)}")
                    break
                time.sleep(0.01)
            else:
                print(f"[{_now_str()}] no on_order_error received within error_wait_ms={args.error_wait_ms}")
            return 1

        return 0

    except KeyboardInterrupt:
        print(f"[{_now_str()}] interrupted")
        return 130
    except Exception as e:
        print(f"[{_now_str()}] exception: {e}")
        return 1
    finally:
        try:
            trader.stop()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
