import concurrent.futures
from datetime import datetime

import ntplib


def get_ntp_core_data(server: str, *, timeout_s: float = 0.5):
    """Return stable NTP metrics.

    Fields:
    - total_rtt_ms: response.delay * 1000
    - offset_ms_raw: response.offset * 1000 (ntplib's offset)
    - local_minus_ntp_ms: -offset_ms_raw (positive means local clock is earlier)
    """

    ntp_client = ntplib.NTPClient()
    try:
        response = ntp_client.request(server, version=3, timeout=float(timeout_s))
        total_rtt_ms = round(float(response.delay) * 1000.0, 3)
        offset_ms_raw = round(float(response.offset) * 1000.0, 3)
        return {
            "server": server,
            "success": True,
            "total_rtt_ms": total_rtt_ms,
            "offset_ms_raw": offset_ms_raw,
            "local_minus_ntp_ms": round(-offset_ms_raw, 3),
            "ntp_time": datetime.fromtimestamp(float(response.tx_time)),
        }
    except Exception as e:
        return {"server": server, "success": False, "error": str(e)}


def sample_ntp_best_offset(
    servers: list[str],
    *,
    timeout_s: float = 0.5,
    max_workers: int = 2,
):
    """One sampling round: query servers in parallel, pick the best (min abs offset_ms_raw)."""

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(get_ntp_core_data, s, timeout_s=timeout_s) for s in servers]
        server_results = [f.result() for f in futures]

    valid_results = [r for r in server_results if r.get("success")]
    if not valid_results:
        return {"success": False, "results": server_results, "error": "all servers failed"}

    best = min(valid_results, key=lambda x: abs(float(x["offset_ms_raw"])))
    return {"success": True, "best": best, "results": server_results}


def sample_ntp_average(
    servers: list[str],
    *,
    samples: int = 20,
    timeout_s: float = 0.5,
    max_workers: int = 2,
):
    """Multiple rounds sampling.

    Returns average of the BEST result per round (same logic as ntp_detect.py).
    """

    samples = max(1, int(samples))
    check_results = []

    for _ in range(samples):
        one = sample_ntp_best_offset(servers, timeout_s=timeout_s, max_workers=max_workers)
        if not one.get("success"):
            continue
        best = one["best"]
        check_results.append(
            {
                "server": best["server"],
                "offset_ms_raw": float(best["offset_ms_raw"]),
                "local_minus_ntp_ms": float(best["local_minus_ntp_ms"]),
                "total_rtt_ms": float(best["total_rtt_ms"]),
            }
        )

    if not check_results:
        return {"success": False, "error": "no valid samples"}

    avg_offset_raw_ms = sum([r["offset_ms_raw"] for r in check_results]) / len(check_results)
    avg_local_minus_ntp_ms = sum([r["local_minus_ntp_ms"] for r in check_results]) / len(check_results)
    avg_rtt_ms = sum([r["total_rtt_ms"] for r in check_results]) / len(check_results)

    return {
        "success": True,
        "samples": len(check_results),
        "avg_offset_ms_raw": round(avg_offset_raw_ms, 3),
        "avg_local_minus_ntp_ms": round(avg_local_minus_ntp_ms, 3),
        "avg_rtt_ms": round(avg_rtt_ms, 3),
        "details": check_results,
    }
