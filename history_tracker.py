"""
Historical DOM Data Tracker
Stores and retrieves DOM statistics over time for trend analysis.
"""

import json
import os
from datetime import datetime
from typing import Optional
import pandas as pd


class DOMHistoryTracker:
    """Tracks DOM statistics over time."""

    def __init__(self, data_file: str = "dom_history.json"):
        self.data_file = data_file
        self.history = self._load_history()

    def _load_history(self) -> list:
        """Load history from JSON file."""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return []
        return []

    def _save_history(self):
        """Save history to JSON file."""
        with open(self.data_file, 'w') as f:
            json.dump(self.history, f, indent=2)

    def add_snapshot(self, df: pd.DataFrame, label: Optional[str] = None) -> dict:
        """
        Add a new DOM snapshot from the current data.

        Args:
            df: DataFrame with property data
            label: Optional label for this snapshot (e.g., search criteria)

        Returns:
            The snapshot that was added
        """
        if df.empty or "DAYS ON MARKET" not in df.columns:
            return None

        dom = df["DAYS ON MARKET"]
        price = df["PRICE"] if "PRICE" in df.columns else pd.Series([0])

        snapshot = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "timestamp": datetime.now().isoformat(),
            "label": label or "Upload",
            "avg_dom": round(dom.mean(), 1),
            "median_dom": round(dom.median(), 1),
            "min_dom": int(dom.min()),
            "max_dom": int(dom.max()),
            "property_count": len(df),
            "avg_price": round(price.mean(), 0),
            "median_price": round(price.median(), 0),
        }

        self.history.append(snapshot)
        self._save_history()
        return snapshot

    def get_history(self) -> list:
        """Get all historical snapshots."""
        return self.history

    def get_history_df(self) -> pd.DataFrame:
        """Get history as a DataFrame for plotting."""
        if not self.history:
            return pd.DataFrame()

        df = pd.DataFrame(self.history)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        return df

    def delete_snapshot(self, index: int) -> bool:
        """Delete a snapshot by index."""
        if 0 <= index < len(self.history):
            del self.history[index]
            self._save_history()
            return True
        return False

    def delete_by_timestamp(self, timestamp: str) -> bool:
        """Delete a snapshot by its timestamp."""
        for i, snap in enumerate(self.history):
            if snap.get("timestamp") == timestamp:
                del self.history[i]
                self._save_history()
                return True
        return False

    def clear_history(self):
        """Clear all history."""
        self.history = []
        self._save_history()

    def get_latest(self) -> Optional[dict]:
        """Get the most recent snapshot."""
        if not self.history:
            return None
        return max(self.history, key=lambda x: x.get("timestamp", ""))


# Global tracker instance
tracker = DOMHistoryTracker()
