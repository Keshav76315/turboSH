"""
Network state data model and in-memory/SQLite persistence store.
"""

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from forecasting.config import (
    DEFAULT_RING_BUFFER_CAPACITY,
    DEFAULT_SQLITE_DB_PATH,
    FEATURE_NAMES,
)


@dataclass
class NetworkState:
    """Represents a single point-in-time network state S(t) for an IP address."""

    timestamp: datetime
    ip_hash: str
    requests_per_ip_10s: float = 0.0
    requests_per_ip_60s: float = 0.0
    endpoint_entropy: float = 0.0
    latency_spike: float = 0.0
    error_rate: float = 0.0
    request_variance: float = 0.0
    anomaly_score: float = 0.0
    action: str = "ALLOW"
    extended_features: Dict[str, Any] = field(default_factory=dict)
    label: Optional[int] = None  # AttackStage label (0-4), assigned by StateLabeler

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NetworkState":
        """Deserialize from dictionary (e.g. from parsed JSONL line)."""
        ts_raw = data.get("timestamp")
        if isinstance(ts_raw, str):
            # Parse ISO 8601 string, handling 'Z' suffix
            clean_ts = ts_raw.replace("Z", "+00:00")
            try:
                ts = datetime.fromisoformat(clean_ts)
            except ValueError:
                ts = datetime.now(timezone.utc)
        elif isinstance(ts_raw, (int, float)):
            ts = datetime.fromtimestamp(ts_raw, timezone.utc)
        elif isinstance(ts_raw, datetime):
            ts = ts_raw
        else:
            ts = datetime.now(timezone.utc)

        return cls(
            timestamp=ts,
            ip_hash=str(data.get("ip_hash", "")),
            requests_per_ip_10s=float(data.get("requests_per_ip_10s", 0.0)),
            requests_per_ip_60s=float(data.get("requests_per_ip_60s", 0.0)),
            endpoint_entropy=float(data.get("endpoint_entropy", 0.0)),
            latency_spike=float(data.get("latency_spike", 0.0)),
            error_rate=float(data.get("error_rate", 0.0)),
            request_variance=float(data.get("request_variance", 0.0)),
            anomaly_score=float(data.get("anomaly_score", 0.0)),
            action=str(data.get("action", "ALLOW")),
            extended_features=data.get("extended_features", {}) or {},
            label=data.get("label"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d

    def feature_vector(self) -> List[float]:
        """Extract the 6 core features as a flat float list in canonical order."""
        return [getattr(self, name, 0.0) for name in FEATURE_NAMES]


class StateStore:
    """Thread-safe state history storage combining an in-memory ring buffer with SQLite disk persistence."""

    def __init__(
        self,
        capacity: int = DEFAULT_RING_BUFFER_CAPACITY,
        db_path: str = DEFAULT_SQLITE_DB_PATH,
    ):
        self.capacity = capacity
        self.db_path = db_path
        self._buffer: deque[NetworkState] = deque(maxlen=capacity)
        self._ip_index: Dict[str, deque[NetworkState]] = {}
        self._unflushed: List[NetworkState] = []
        self._lock = threading.Lock()

        if self.db_path:
            self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite schema if database file is specified."""
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS network_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ip_hash TEXT NOT NULL,
                    requests_per_ip_10s REAL NOT NULL,
                    requests_per_ip_60s REAL NOT NULL,
                    endpoint_entropy REAL NOT NULL,
                    latency_spike REAL NOT NULL,
                    error_rate REAL NOT NULL,
                    request_variance REAL NOT NULL,
                    anomaly_score REAL NOT NULL,
                    action TEXT NOT NULL,
                    extended_features TEXT,
                    label INTEGER
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_states_ip_ts ON network_states (ip_hash, timestamp)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_states_ts ON network_states (timestamp)"
            )
            conn.commit()

    def append(self, state: NetworkState) -> None:
        """Add a NetworkState to in-memory buffers and unflushed queue."""
        with self._lock:
            self._buffer.append(state)

            # Update per-IP sliding index
            if state.ip_hash not in self._ip_index:
                self._ip_index[state.ip_hash] = deque(maxlen=200)
            self._ip_index[state.ip_hash].append(state)

            self._unflushed.append(state)

    def get_ip_history(self, ip_hash: str, n: int = 10) -> List[NetworkState]:
        """Return the most recent N states for a given IP."""
        with self._lock:
            if ip_hash not in self._ip_index:
                return []
            history = list(self._ip_index[ip_hash])
            return history[-n:]

    def get_time_range(
        self, start: datetime, end: datetime
    ) -> List[NetworkState]:
        """Return states within [start, end] from in-memory buffer."""
        # Ensure comparison timezone consistency
        with self._lock:
            results = []
            for s in self._buffer:
                s_ts = s.timestamp
                if s_ts.tzinfo is None and start.tzinfo is not None:
                    s_ts = s_ts.replace(tzinfo=timezone.utc)
                if start <= s_ts <= end:
                    results.append(s)
            return results

    def get_all_sequences(
        self, window_size: int = 5, min_length: int = 5
    ) -> List[List[NetworkState]]:
        """
        Generate sliding window sequences grouped by IP hash.
        Used to prepare training sequences for Markov, LSTM, and Transformer models.
        """
        with self._lock:
            sequences: List[List[NetworkState]] = []
            for ip, states in self._ip_index.items():
                state_list = list(states)
                if len(state_list) < min_length:
                    continue
                for i in range(len(state_list) - window_size + 1):
                    sequences.append(state_list[i : i + window_size])
            return sequences

    def flush_to_sqlite(self) -> int:
        """Persist unflushed states to the SQLite database. Returns count of persisted records."""
        if not self.db_path:
            return 0

        with self._lock:
            if not self._unflushed:
                return 0
            to_save = list(self._unflushed)
            self._unflushed.clear()

        rows = [
            (
                s.timestamp.isoformat(),
                s.ip_hash,
                s.requests_per_ip_10s,
                s.requests_per_ip_60s,
                s.endpoint_entropy,
                s.latency_spike,
                s.error_rate,
                s.request_variance,
                s.anomaly_score,
                s.action,
                json.dumps(s.extended_features),
                s.label,
            )
            for s in to_save
        ]

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """
                INSERT INTO network_states (
                    timestamp, ip_hash, requests_per_ip_10s, requests_per_ip_60s,
                    endpoint_entropy, latency_spike, error_rate, request_variance,
                    anomaly_score, action, extended_features, label
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()

        return len(rows)

    def load_from_sqlite(self, limit: int = 1000) -> int:
        """Load the most recent `limit` records from SQLite into the in-memory buffer."""
        if not self.db_path or not os.path.exists(self.db_path):
            return 0

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT timestamp, ip_hash, requests_per_ip_10s, requests_per_ip_60s,
                       endpoint_entropy, latency_spike, error_rate, request_variance,
                       anomaly_score, action, extended_features, label
                FROM network_states
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()

        loaded_states = []
        for row in reversed(rows):
            ext = {}
            if row[10]:
                try:
                    ext = json.loads(row[10])
                except json.JSONDecodeError:
                    ext = {}
            state = NetworkState(
                timestamp=datetime.fromisoformat(row[0]),
                ip_hash=row[1],
                requests_per_ip_10s=float(row[2]),
                requests_per_ip_60s=float(row[3]),
                endpoint_entropy=float(row[4]),
                latency_spike=float(row[5]),
                error_rate=float(row[6]),
                request_variance=float(row[7]),
                anomaly_score=float(row[8]),
                action=row[9],
                extended_features=ext,
                label=row[11],
            )
            loaded_states.append(state)

        with self._lock:
            for s in loaded_states:
                self._buffer.append(s)
                if s.ip_hash not in self._ip_index:
                    self._ip_index[s.ip_hash] = deque(maxlen=200)
                self._ip_index[s.ip_hash].append(s)

        return len(loaded_states)

    def to_records(self) -> List[Dict[str, Any]]:
        """Export all states in buffer as a list of dicts."""
        with self._lock:
            return [s.to_dict() for s in self._buffer]

    def to_dataframe(self):
        """Export in-memory states to a pandas DataFrame if pandas is installed, else list of dicts."""
        records = self.to_records()
        try:
            import pandas as pd

            return pd.DataFrame(records)
        except ImportError:
            return records

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)
