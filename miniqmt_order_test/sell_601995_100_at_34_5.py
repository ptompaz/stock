from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

from typing import Any, Dict

from xtquant import xtconstant
from xtquant import xttrader
from xtquant.xttype import StockAccount


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _obj_to_dict(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    out: Dict[str, Any] = {}
    for k in dir(obj):
        if k.startswith("_"):
            continue
        try:
            v = getattr(obj, k)
        except Exception:
            continue
        if callable(v):
            continue
        if isinstance(v, (int, float, str, bool)) or v is None:
            out[k] = v
    return out


def _fmt(obj: Any) -> str:
    d = _obj_to_dict(obj)
    if d:
        try:
            return json.dumps(d, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(d)
    return str(obj)


def _fmt_list(xs: Any) -> str:
    if xs is None:
        return "[]"
    if not isinstance(xs, (list, tuple)):
        return _fmt(xs)
    rows = []
    for x in xs:
        rows.append(_obj_to_dict(x) or str(x))
    try:
        return json.dumps(rows, ensure_ascii=False)
    except Exception:
        return str(rows)


class Callback(xttrader.XtQuantTraderCallback):
    def on_connected(self):
        print(_now(), "[cb] connected")

    def on_disconnected(self):
        print(_now(), "[cb] disconnected")

    def on_order_error(self, order_error):
        print(_now(), "[cb] order_error:", _fmt(order_error))

    def on_cancel_error(self, cancel_error):
        print(_now(), "[cb] cancel_error:", _fmt(cancel_error))

    def on_stock_order(self, order):
        print(_now(), "[cb] stock_order:", _fmt(order))

    def on_stock_trade(self, trade):
        print(_now(), "[cb] stock_trade:", _fmt(trade))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qmt-path", required=True)
    ap.add_argument("--session", type=int, default=1)
    ap.add_argument("--account-id", required=True)

    ap.add_argument("--live", action="store_true", help="actually place the order")
    ap.add_argument("--confirm", default="", help="must be YES when --live")
    ap.add_argument("--wait", type=float, default=2.0)
    args = ap.parse_args()

    if args.live and args.confirm != "YES":
        print("Refusing to place live order: pass --confirm YES")
        return 2

    code = "601995.SH"
    side = "sell"
    volume = 100
    limit_price = 34.5

    cb = Callback()
    trader = xttrader.XtQuantTrader(args.qmt_path, args.session, cb)

    print(_now(), "starting trader...")
    trader.start()

    try:
        print(_now(), "connecting...")
        trader.connect()

        account = StockAccount(args.account_id)

        try:
            print(_now(), "pre-check: query positions...")
            positions = trader.query_stock_positions(account)
            print(_now(), "positions:", _fmt_list(positions))
        except Exception as e:
            print(_now(), "pre-check positions failed:", e)

        print(
            _now(),
            f"intent: {side} {volume} {code} @ {limit_price} (limit)",
        )

        if not args.live:
            print(_now(), "dry-run: not placing any order")
            time.sleep(max(0.0, float(args.wait)))
            return 0

        print(_now(), "LIVE order placing...")
        order_id = trader.order_stock(
            account=account,
            stock_code=code,
            order_type=xtconstant.STOCK_SELL,
            order_volume=int(volume),
            price_type=xtconstant.FIX_PRICE,
            price=float(limit_price),
            strategy_name="sell_601995_34_5",
            order_remark="miniqmt_order_test",
        )
        print(_now(), "order_id:", order_id)

        try:
            orders = trader.query_stock_orders(account, cancelable_only=False)
            print(_now(), "orders(after submit):", _fmt_list(orders))
        except Exception as e:
            print(_now(), "query orders(after submit) failed:", e)

        time.sleep(max(0.0, float(args.wait)))

        try:
            orders = trader.query_stock_orders(account, cancelable_only=False)
            print(_now(), "orders(after wait):", _fmt_list(orders))
        except Exception as e:
            print(_now(), "query orders(after wait) failed:", e)

        return 0
    finally:
        print(_now(), "stopping trader...")
        try:
            trader.stop()
        except Exception as e:
            print(_now(), "stop error:", e, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
