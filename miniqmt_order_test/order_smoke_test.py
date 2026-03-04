from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

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


def _side_to_order_type(side: str) -> int:
    s = str(side).strip().lower()
    if s in ("buy", "b"):
        return xtconstant.STOCK_BUY
    if s in ("sell", "s"):
        return xtconstant.STOCK_SELL
    raise ValueError(f"unknown side: {side}")


def _price_type(limit: bool) -> int:
    return xtconstant.FIX_PRICE if limit else xtconstant.LATEST_PRICE


@dataclass
class OrderIntent:
    code: str
    side: str
    volume: int
    price: float


class Callback(xttrader.XtQuantTraderCallback):
    def on_connected(self):
        print(_now(), "[cb] connected")

    def on_disconnected(self):
        print(_now(), "[cb] disconnected")

    def on_account_status(self, status):
        print(_now(), "[cb] account_status:", _fmt(status))

    def on_order_error(self, order_error):
        print(_now(), "[cb] order_error:", _fmt(order_error))

    def on_cancel_error(self, cancel_error):
        print(_now(), "[cb] cancel_error:", _fmt(cancel_error))

    def on_order_stock_async_response(self, response):
        print(_now(), "[cb] order_stock_async_response:", _fmt(response))

    def on_cancel_order_stock_async_response(self, response):
        print(_now(), "[cb] cancel_order_stock_async_response:", _fmt(response))

    def on_stock_asset(self, asset):
        print(_now(), "[cb] stock_asset:", _fmt(asset))

    def on_stock_position(self, position):
        print(_now(), "[cb] stock_position:", _fmt(position))

    def on_stock_order(self, order):
        print(_now(), "[cb] stock_order:", _fmt(order))

    def on_stock_trade(self, trade):
        print(_now(), "[cb] stock_trade:", _fmt(trade))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qmt-path", required=True, help="path passed into XtQuantTrader(path, session, callback)")
    ap.add_argument("--session", type=int, default=1, help="XtQuantTrader session id (int)")
    ap.add_argument("--account-id", required=True, help="account id for StockAccount(account_id)")

    ap.add_argument("--live", action="store_true", help="actually send an order")
    ap.add_argument("--confirm", default="", help="must be YES when --live")

    ap.add_argument("--code", default="000001.SZ")
    ap.add_argument("--side", default="buy", choices=["buy", "sell"])
    ap.add_argument("--volume", type=int, default=100)
    ap.add_argument("--price", type=float, default=0.0, help="limit price when --limit; ignored otherwise")
    ap.add_argument("--limit", action="store_true", help="use limit price (FIX_PRICE). default uses LATEST_PRICE")

    ap.add_argument("--query-only", action="store_true", help="only connect and query, never place order")
    ap.add_argument("--wait", type=float, default=2.0, help="seconds to wait after queries / order")

    args = ap.parse_args()

    if args.live and args.confirm != "YES":
        print("Refusing to place live order: pass --confirm YES")
        return 2

    if args.volume <= 0:
        print("volume must be > 0")
        return 2

    cb = Callback()
    trader = xttrader.XtQuantTrader(args.qmt_path, args.session, cb)

    print(_now(), "starting trader...")
    trader.start()

    try:
        print(_now(), "connecting...")
        trader.connect()

        account = StockAccount(args.account_id)

        print(_now(), "query asset...")
        asset = trader.query_stock_asset(account)
        print(_now(), "asset:", _fmt(asset))

        print(_now(), "query positions...")
        positions = trader.query_stock_positions(account)
        print(_now(), "positions:", _fmt_list(positions))

        print(_now(), "query orders...")
        orders = trader.query_stock_orders(account, cancelable_only=False)
        print(_now(), "orders:", _fmt_list(orders))

        print(_now(), "query trades...")
        trades = trader.query_stock_trades(account)
        print(_now(), "trades:", _fmt_list(trades))

        if args.query_only or not args.live:
            print(_now(), "dry-run: not placing any order")
            time.sleep(max(0.0, float(args.wait)))
            return 0

        order_type = _side_to_order_type(args.side)
        price_type = _price_type(args.limit)
        price = float(args.price) if args.limit else 0.0

        print(_now(), f"LIVE order: code={args.code} side={args.side} volume={args.volume} price_type={price_type} price={price}")
        order_id = trader.order_stock(
            account=account,
            stock_code=args.code,
            order_type=order_type,
            order_volume=int(args.volume),
            price_type=price_type,
            price=price,
            strategy_name="smoke_test",
            order_remark="miniqmt_order_test",
        )
        print(_now(), "order_id:", order_id)

        time.sleep(max(0.0, float(args.wait)))
        return 0
    finally:
        print(_now(), "stopping trader...")
        try:
            trader.stop()
        except Exception as e:
            print(_now(), "stop error:", e, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
