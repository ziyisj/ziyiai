from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk


def get_runtime_root() -> Path:
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root)
    return Path(__file__).resolve().parents[1]


ROOT = get_runtime_root()
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from eth_backtester.cli import apply_preset_args, build_parser
from eth_backtester.live import build_okx_live_signal_snapshot

DEFAULT_PRESET = ROOT / "presets" / "okx_15m_mtf_production_candidate.json"
LOG_PATH = Path.home() / "ETH_15M_Signal_Desktop.log"


class SignalDesktopApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("ETH 15m Signal Desktop")
        self.root.geometry("840x640")
        self.root.minsize(760, 560)

        self.preset_path_var = tk.StringVar(value=str(DEFAULT_PRESET))
        self.refresh_seconds_var = tk.StringVar(value="15")
        self.status_var = tk.StringVar(value="Ready")
        self.last_update_var = tk.StringVar(value="Never")

        self._build_ui()
        self._schedule_refresh(initial=True)

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(container, text="ETH 15m Live Signal", font=("Segoe UI", 18, "bold"))
        title.pack(anchor="w")

        subtitle = ttk.Label(
            container,
            text="实时拉取 OKX ETH-USDT 数据并生成当前交易信号快照",
            font=("Segoe UI", 10),
        )
        subtitle.pack(anchor="w", pady=(0, 10))

        controls = ttk.Frame(container)
        controls.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(controls, text="Preset JSON:").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.preset_path_var, width=80).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(controls, text="Refresh Now", command=self.refresh_snapshot).grid(row=0, column=2, padx=(8, 0))

        ttk.Label(controls, text="Auto refresh (sec):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(controls, textvariable=self.refresh_seconds_var, width=10).grid(row=1, column=1, sticky="w", padx=8, pady=(8, 0))

        controls.columnconfigure(1, weight=1)

        meta = ttk.Frame(container)
        meta.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(meta, text="Status:").grid(row=0, column=0, sticky="w")
        ttk.Label(meta, textvariable=self.status_var).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(meta, text="Last update:").grid(row=0, column=2, sticky="w", padx=(20, 0))
        ttk.Label(meta, textvariable=self.last_update_var).grid(row=0, column=3, sticky="w", padx=6)

        self.text = tk.Text(container, wrap=tk.WORD, font=("Consolas", 10))
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.insert(
            tk.END,
            "等待首次刷新...\n\n默认会使用 production-candidate preset，并从 OKX 拉取 15m ETH-USDT 数据。",
        )
        self.text.config(state=tk.DISABLED)

    def _build_args(self):
        preset_path = Path(self.preset_path_var.get()).expanduser()
        parser = build_parser()
        args = parser.parse_args([
            "--preset",
            str(preset_path),
            "--live-okx-snapshot",
            "--okx-inst-id",
            "ETH-USDT",
            "--okx-bar",
            "15m",
            "--okx-candles",
            "300",
        ])
        return apply_preset_args(args)

    def refresh_snapshot(self) -> None:
        try:
            args = self._build_args()
            snapshot = build_okx_live_signal_snapshot(args)
            content = self._format_snapshot(snapshot.to_dict())
            self._set_text(content)
            self.status_var.set("OK")
            self.last_update_var.set(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as exc:
            details = traceback.format_exc()
            LOG_PATH.write_text(details, encoding="utf-8")
            self.status_var.set(f"ERROR: {exc}")
            self.last_update_var.set(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            self._set_text(
                "刷新失败:\n"
                f"{exc}\n\n"
                f"日志文件: {LOG_PATH}\n\n"
                "请把这段报错截图给我，我可以继续修。"
            )

        self._schedule_refresh()

    def _schedule_refresh(self, initial: bool = False) -> None:
        try:
            seconds = max(5, int(self.refresh_seconds_var.get()))
        except ValueError:
            seconds = 15
            self.refresh_seconds_var.set("15")
        delay_ms = 100 if initial else seconds * 1000
        self.root.after(delay_ms, self.refresh_snapshot)

    def _format_snapshot(self, snapshot: dict) -> str:
        lines = [
            f"Strategy: {snapshot['strategy_name']}",
            f"Latest candle: {snapshot['latest_timestamp']}",
            f"Latest close: {snapshot['latest_close']}",
            f"Latest signal: {snapshot['latest_signal_action']} ({snapshot['latest_signal_reason']})",
            f"Position state: {snapshot['current_position_state']}",
            f"Position qty: {snapshot['current_position_qty']}",
            f"Cash: {snapshot['cash']}",
            f"Equity: {snapshot['equity']}",
            f"Recommendation: {snapshot['recommendation']}",
            "",
            "Recent Trades:",
        ]
        trades = snapshot.get("recent_trades", [])
        if not trades:
            lines.append("  (none)")
        for trade in trades:
            lines.append(
                f"  {trade['timestamp']} | {trade['side']} | price={trade['price']:.4f} | qty={trade['quantity']:.6f} | {trade['reason']}"
            )
        lines.append("")
        lines.append("Raw JSON:")
        lines.append(json.dumps(snapshot, indent=2, ensure_ascii=False))
        return "\n".join(lines)

    def _set_text(self, value: str) -> None:
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, value)
        self.text.config(state=tk.DISABLED)

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    try:
        SignalDesktopApp().run()
    except Exception as exc:
        messagebox.showerror("ETH 15m Signal Desktop", str(exc))
        raise
