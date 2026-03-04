import argparse
import re
import subprocess
import time
from datetime import datetime


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _ping_windows_avg_rtt_ms(output: str):
    m = re.search(r"Average\s*=\s*(\d+)ms", output, flags=re.IGNORECASE)
    if m:
        return float(m.group(1))

    m = re.search(r"平均\s*=\s*(\d+)ms", output)
    if m:
        return float(m.group(1))

    times = [int(x) for x in re.findall(r"time[=<]\s*(\d+)ms", output, flags=re.IGNORECASE)]
    if times:
        return sum(times) / len(times)

    return None


def ping_host(host: str, count: int, timeout_ms: int):
    proc = subprocess.run(
        ["ping", "-n", str(int(count)), "-w", str(int(timeout_ms)), host],
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    avg_rtt_ms = _ping_windows_avg_rtt_ms(out)

    if avg_rtt_ms is None:
        return {
            "host": host,
            "success": False,
            "exit_code": proc.returncode,
            "error": "无法解析ping输出（可能全丢包/被禁ICMP/输出格式变化）",
            "raw": out.strip(),
        }

    return {
        "host": host,
        "success": True,
        "exit_code": proc.returncode,
        "avg_rtt_ms": round(float(avg_rtt_ms), 3),
        "rtt_half_ms": round(float(avg_rtt_ms) / 2.0, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="139.224.114.71")
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--timeout-ms", type=int, default=50)
    args = ap.parse_args()

    start = time.time()
    print(_now(), f"ping host={args.host} count={args.count} timeout_ms={args.timeout_ms}")
    res = ping_host(args.host, args.count, args.timeout_ms)

    if not res.get("success"):
        print(_now(), f"ping failed: exit_code={res.get('exit_code')} error={res.get('error')}")
        raw = res.get("raw")
        if raw:
            print(raw)
        print(_now(), f"elapsed_s={time.time() - start:.3f}")
        return 1

    print(_now(), f"avg_rtt_ms={res['avg_rtt_ms']} rtt_half_ms={res['rtt_half_ms']}")
    print(_now(), f"elapsed_s={time.time() - start:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
