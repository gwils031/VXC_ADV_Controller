"""Minimal ADV streaming MVP (no GUI).

Connects to the ADV using config/adv_config.yaml, starts streaming,
prints parsed samples, and shuts down cleanly.
"""

import argparse
import logging
import time
from pathlib import Path
import sys

import yaml

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from vxc_adv_visualizer.controllers.adv_controller import ADVController


logger = logging.getLogger(__name__)


def load_adv_config(config_dir: str) -> dict:
    config_path = Path(config_dir) / "adv_config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, "r") as f:
        return yaml.safe_load(f) or {}


def run_mvp(config_dir: str, duration: float, max_samples: int, raw: bool) -> int:
    cfg = load_adv_config(config_dir)

    port = cfg.get("port", "COM4")
    baudrate = cfg.get("baudrate", 9600)
    timeout = cfg.get("timeout", 2.0)
    line_ending = cfg.get("line_ending", "\r")
    start_command = cfg.get("start_command", "START")
    stop_command = cfg.get("stop_command", "STOP")
    expected_fields = cfg.get("expected_fields", 8)

    adv = ADVController(
        port=port,
        baudrate=baudrate,
        timeout=timeout,
        line_ending=line_ending,
        start_command=start_command,
        stop_command=stop_command,
        expected_fields=expected_fields,
    )

    if not adv.connect():
        logger.error("Failed to connect to ADV")
        return 1

    if not adv.start_stream():
        logger.error("Failed to start ADV stream")
        adv.disconnect()
        return 1

    logger.info("Streaming... press Ctrl+C to stop")

    start_time = time.time()
    count = 0

    try:
        while True:
            if duration > 0 and (time.time() - start_time) >= duration:
                break
            if max_samples > 0 and count >= max_samples:
                break

            if raw:
                line = adv.read_raw_line()
                if line:
                    print(line)
                    count += 1
            else:
                sample = adv.read_sample()
                if sample:
                    print(
                        f"t={sample.timestamp:.3f} u={sample.u:.4f} v={sample.v:.4f} "
                        f"w={sample.w:.4f} snr={sample.snr:.1f} corr={sample.correlation:.1f} "
                        f"depth={sample.depth:.3f} temp={sample.temperature:.2f}"
                    )
                    count += 1

    except KeyboardInterrupt:
        pass
    finally:
        adv.stop_stream()
        adv.disconnect()
        logger.info(f"Stopped. Samples: {count}")

    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(description="Minimal ADV streaming MVP")
    default_config_dir = Path(__file__).resolve().parents[1] / "config"
    parser.add_argument("--config-dir", default=str(default_config_dir), help="Config directory")
    parser.add_argument("--duration", type=float, default=10.0, help="Seconds to stream (0=unlimited)")
    parser.add_argument("--max-samples", type=int, default=0, help="Stop after N samples (0=unlimited)")
    parser.add_argument("--raw", action="store_true", help="Print raw lines instead of parsed samples")

    args = parser.parse_args()
    return run_mvp(args.config_dir, args.duration, args.max_samples, args.raw)


if __name__ == "__main__":
    raise SystemExit(main())
