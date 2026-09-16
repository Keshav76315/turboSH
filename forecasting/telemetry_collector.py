"""
Telemetry collector daemon for tailing and ingesting Go state telemetry JSONL into StateStore.
"""

import argparse
import json
import logging
import os
import sys
import time
from typing import Optional

from forecasting.config import (
    DEFAULT_RING_BUFFER_CAPACITY,
    DEFAULT_SQLITE_DB_PATH,
    DEFAULT_STATE_LOG_PATH,
)
from forecasting.state_store import NetworkState, StateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [telemetry_collector] %(message)s",
)
logger = logging.getLogger("telemetry_collector")


class TelemetryCollector:
    """Reads state snapshots from the Go-generated state telemetry JSONL file and feeds them into a StateStore."""

    def __init__(
        self,
        state_store: StateStore,
        log_path: str = DEFAULT_STATE_LOG_PATH,
        auto_flush_interval_sec: float = 5.0,
    ):
        self.state_store = state_store
        self.log_path = log_path
        self.auto_flush_interval = auto_flush_interval_sec
        self._running = False

    def parse_line(self, line: str) -> Optional[NetworkState]:
        """Parse a single JSONL line into a NetworkState dataclass instance."""
        clean_line = line.strip()
        if not clean_line:
            return None
        try:
            data = json.loads(clean_line)
            return NetworkState.from_dict(data)
        except Exception as e:
            logger.warning("Failed to parse telemetry line: %s (error: %s)", clean_line[:100], e)
            return None

    def ingest_file(self, file_path: Optional[str] = None) -> int:
        """Process all existing lines from the telemetry file (batch/single-pass mode)."""
        target = file_path or self.log_path
        if not os.path.exists(target):
            logger.warning("Telemetry file not found: %s", target)
            return 0

        count = 0
        with open(target, "r", encoding="utf-8") as f:
            for line in f:
                state = self.parse_line(line)
                if state:
                    self.state_store.append(state)
                    count += 1

        flushed = self.state_store.flush_to_sqlite()
        logger.info("Ingested %d states from %s (persisted %d to SQLite)", count, target, flushed)
        return count

    def run(self, follow: bool = True, poll_interval: float = 0.5) -> None:
        """
        Tail the telemetry log file and continuously ingest new states.
        If follow=False, processes up to EOF and returns.
        """
        self._running = True
        logger.info("Starting telemetry collector watching %s", self.log_path)

        last_flush = time.time()
        file_obj = None
        last_inode = None

        try:
            while self._running:
                # Open or reopen if file rotated/created
                if not file_obj:
                    if os.path.exists(self.log_path):
                        file_obj = open(self.log_path, "r", encoding="utf-8")
                        last_inode = os.fstat(file_obj.fileno()).st_ino
                        logger.info("Opened telemetry log file %s", self.log_path)
                    else:
                        time.sleep(poll_interval)
                        continue

                # Check if file was rotated (inode changed)
                try:
                    curr_stat = os.stat(self.log_path)
                    if curr_stat.st_ino != last_inode:
                        logger.info("Log file rotation detected. Reopening %s", self.log_path)
                        file_obj.close()
                        file_obj = open(self.log_path, "r", encoding="utf-8")
                        last_inode = os.fstat(file_obj.fileno()).st_ino
                except FileNotFoundError:
                    pass

                line = file_obj.readline()
                if line:
                    state = self.parse_line(line)
                    if state:
                        self.state_store.append(state)
                else:
                    if not follow:
                        break
                    time.sleep(poll_interval)

                # Periodic SQLite flush
                if time.time() - last_flush >= self.auto_flush_interval:
                    flushed = self.state_store.flush_to_sqlite()
                    if flushed > 0:
                        logger.debug("Periodic flush saved %d states to SQLite", flushed)
                    last_flush = time.time()

        except KeyboardInterrupt:
            logger.info("Telemetry collector stopped by user.")
        finally:
            if file_obj:
                file_obj.close()
            final_flush = self.state_store.flush_to_sqlite()
            logger.info("Telemetry collector shutdown. Final flush saved %d states.", final_flush)

    def stop(self) -> None:
        self._running = False


def main():
    parser = argparse.ArgumentParser(description="TurboSH State Telemetry Collector")
    parser.add_argument("--input", default=DEFAULT_STATE_LOG_PATH, help="Path to state telemetry JSONL")
    parser.add_argument("--db", default=DEFAULT_SQLITE_DB_PATH, help="Path to SQLite database")
    parser.add_argument("--buffer-size", type=int, default=DEFAULT_RING_BUFFER_CAPACITY, help="In-memory ring buffer size")
    parser.add_argument("--once", action="store_true", help="Process existing file once and exit (no tailing)")
    args = parser.parse_args()

    store = StateStore(capacity=args.buffer_size, db_path=args.db)
    collector = TelemetryCollector(state_store=store, log_path=args.input)

    if args.once:
        collector.ingest_file()
    else:
        collector.run(follow=True)


if __name__ == "__main__":
    main()
