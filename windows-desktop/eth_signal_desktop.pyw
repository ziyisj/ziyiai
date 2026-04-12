from __future__ import annotations

# 桌面版主程序：
# 1. 读取 preset 参数
# 2. 实时拉取 OKX ETH-USDT 15m 数据
# 3. 显示中文信号面板
# 4. 绘制最近一段 K 线图
# 5. 出错时把详细日志写入用户目录，便于排查

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
from eth_backtester.live import build_okx_live_snapshot_bundle

DEFAULT_PRESET = ROOT / "presets" / "okx_15m_mtf_production_candidate.json"
LOG_PATH = Path.home() / "ETH_15M_Signal_Desktop.log"
CHART_CANDLES = 80


class SignalDesktopApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("ETH 15分钟交易信号桌面版")
        self.root.geometry("1260x860")
        self.root.minsize(1080, 760)

        self.preset_path_var = tk.StringVar(value=str(DEFAULT_PRESET))
        self.refresh_seconds_var = tk.StringVar(value="15")
        self.status_var = tk.StringVar(value="就绪")
        self.last_update_var = tk.StringVar(value="尚未刷新")

        self.strategy_var = tk.StringVar(value="-")
        self.price_var = tk.StringVar(value="-")
        self.signal_var = tk.StringVar(value="-")
        self.position_var = tk.StringVar(value="-")
        self.recommend_var = tk.StringVar(value="-")
        self.equity_var = tk.StringVar(value="-")
        self.candle_var = tk.StringVar(value="-")

        self._refresh_job = None
        self._build_ui()
        self.root.after(100, self.refresh_snapshot)

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(container, text="ETH 15分钟实时交易信号", font=("Microsoft YaHei UI", 20, "bold"))
        title.pack(anchor="w")

        subtitle = ttk.Label(
            container,
            text="实时连接 OKX 的 ETH-USDT 15m 数据，显示当前策略信号与最近K线走势",
            font=("Microsoft YaHei UI", 10),
        )
        subtitle.pack(anchor="w", pady=(0, 10))

        controls = ttk.LabelFrame(container, text="运行设置", padding=10)
        controls.pack(fill=tk.X, pady=(0, 10))
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="策略配置文件：").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.preset_path_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(controls, text="立即刷新", command=self.refresh_snapshot).grid(row=0, column=2, padx=(8, 0))

        ttk.Label(controls, text="自动刷新秒数：").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(controls, textvariable=self.refresh_seconds_var, width=10).grid(row=1, column=1, sticky="w", padx=8, pady=(8, 0))

        meta = ttk.Frame(container)
        meta.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(meta, text="运行状态：").grid(row=0, column=0, sticky="w")
        ttk.Label(meta, textvariable=self.status_var, foreground="#0b6b2f").grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(meta, text="上次刷新：").grid(row=0, column=2, sticky="w", padx=(18, 0))
        ttk.Label(meta, textvariable=self.last_update_var).grid(row=0, column=3, sticky="w", padx=6)

        summary = ttk.LabelFrame(container, text="信号总览", padding=10)
        summary.pack(fill=tk.X, pady=(0, 10))
        for col in range(4):
            summary.columnconfigure(col, weight=1)

        self._make_metric(summary, 0, 0, "策略名称", self.strategy_var)
        self._make_metric(summary, 0, 1, "最新收盘价", self.price_var)
        self._make_metric(summary, 0, 2, "最新信号", self.signal_var)
        self._make_metric(summary, 0, 3, "当前仓位", self.position_var)
        self._make_metric(summary, 1, 0, "建议动作", self.recommend_var)
        self._make_metric(summary, 1, 1, "账户权益", self.equity_var)
        self._make_metric(summary, 1, 2, "最新K线时间", self.candle_var)

        body = ttk.PanedWindow(container, orient=tk.VERTICAL)
        body.pack(fill=tk.BOTH, expand=True)

        chart_frame = ttk.LabelFrame(body, text="最近K线图（最新80根15分钟K线）", padding=8)
        detail_frame = ttk.LabelFrame(body, text="详细信息 / 最近交易 / 原始JSON", padding=8)
        body.add(chart_frame, weight=3)
        body.add(detail_frame, weight=2)

        self.chart_canvas = tk.Canvas(chart_frame, bg="#111827", highlightthickness=0)
        self.chart_canvas.pack(fill=tk.BOTH, expand=True)
        self.chart_canvas.bind("<Configure>", lambda _event: self._draw_placeholder_chart())

        self.text = tk.Text(detail_frame, wrap=tk.WORD, font=("Consolas", 10))
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.insert(
            tk.END,
            "欢迎使用 ETH 15分钟信号桌面版。\n\n"
            "界面说明：\n"
            "1. 上方显示当前策略信号与账户状态。\n"
            "2. 中间显示最近K线图。\n"
            "3. 下方显示最近交易和原始 JSON 数据。\n",
        )
        self.text.config(state=tk.DISABLED)

        self._draw_placeholder_chart()

    def _make_metric(self, parent, row: int, col: int, label: str, variable: tk.StringVar) -> None:
        box = ttk.Frame(parent, padding=(4, 6))
        box.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
        ttk.Label(box, text=label, font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        ttk.Label(box, textvariable=variable, font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w", pady=(4, 0))

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
        self._cancel_refresh_job()
        try:
            args = self._build_args()
            candles, snapshot = build_okx_live_snapshot_bundle(args)
            snapshot_dict = snapshot.to_dict()
            self._update_summary(snapshot_dict)
            self._draw_candles(candles[-CHART_CANDLES:])
            self._set_text(self._format_snapshot(snapshot_dict))
            self.status_var.set("运行正常")
            self.last_update_var.set(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as exc:
            details = traceback.format_exc()
            LOG_PATH.write_text(details, encoding="utf-8")
            self.status_var.set(f"刷新失败：{exc}")
            self.last_update_var.set(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            self._draw_placeholder_chart(str(exc))
            self._set_text(
                "刷新失败\n\n"
                f"错误信息：{exc}\n\n"
                f"日志文件：{LOG_PATH}\n\n"
                "请把这段错误或日志发给我，我可以继续修。"
            )

        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        try:
            seconds = max(5, int(self.refresh_seconds_var.get()))
        except ValueError:
            seconds = 15
            self.refresh_seconds_var.set("15")
        self._refresh_job = self.root.after(seconds * 1000, self.refresh_snapshot)

    def _cancel_refresh_job(self) -> None:
        if self._refresh_job is not None:
            try:
                self.root.after_cancel(self._refresh_job)
            except Exception:
                pass
            self._refresh_job = None

    def _update_summary(self, snapshot: dict) -> None:
        signal_text = self._map_signal(snapshot["latest_signal_action"], snapshot["latest_signal_reason"])
        position_text = self._map_position(snapshot["current_position_state"], snapshot["current_position_qty"])
        recommendation_text = self._map_recommendation(snapshot["recommendation"])

        self.strategy_var.set(snapshot["strategy_name"])
        self.price_var.set(f"{snapshot['latest_close']:.2f} USDT")
        self.signal_var.set(signal_text)
        self.position_var.set(position_text)
        self.recommend_var.set(recommendation_text)
        self.equity_var.set(f"{snapshot['equity']:.2f} USDT")
        self.candle_var.set(snapshot["latest_timestamp"].replace("T", " "))

    def _format_snapshot(self, snapshot: dict) -> str:
        lines = [
            "【信号摘要】",
            f"策略：{snapshot['strategy_name']}",
            f"最新K线时间：{snapshot['latest_timestamp']}",
            f"最新收盘价：{snapshot['latest_close']}",
            f"最新信号：{self._map_signal(snapshot['latest_signal_action'], snapshot['latest_signal_reason'])}",
            f"当前仓位：{self._map_position(snapshot['current_position_state'], snapshot['current_position_qty'])}",
            f"账户现金：{snapshot['cash']}",
            f"账户权益：{snapshot['equity']}",
            f"建议动作：{self._map_recommendation(snapshot['recommendation'])}",
            "",
            "【最近交易】",
        ]
        trades = snapshot.get("recent_trades", [])
        if not trades:
            lines.append("暂无最近交易")
        for trade in trades:
            side = "买入" if trade["side"] == "buy" else "卖出"
            lines.append(
                f"{trade['timestamp']} | {side} | 价格={trade['price']:.4f} | 数量={trade['quantity']:.6f} | 原因={trade['reason']}"
            )
        lines.append("")
        lines.append("【原始 JSON】")
        lines.append(json.dumps(snapshot, indent=2, ensure_ascii=False))
        return "\n".join(lines)

    def _draw_placeholder_chart(self, extra_text: str | None = None) -> None:
        canvas = self.chart_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 400)
        height = max(canvas.winfo_height(), 240)
        canvas.create_rectangle(0, 0, width, height, fill="#111827", outline="#111827")
        message = "等待行情数据..."
        if extra_text:
            message = f"图表暂时不可用\n{extra_text}"
        canvas.create_text(width / 2, height / 2, text=message, fill="#d1d5db", font=("Microsoft YaHei UI", 14, "bold"))

    def _draw_candles(self, candles) -> None:
        canvas = self.chart_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 600)
        height = max(canvas.winfo_height(), 320)
        canvas.create_rectangle(0, 0, width, height, fill="#111827", outline="#111827")

        if not candles:
            self._draw_placeholder_chart()
            return

        pad_left, pad_top, pad_right, pad_bottom = 56, 20, 20, 34
        chart_w = width - pad_left - pad_right
        chart_h = height - pad_top - pad_bottom
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        max_price = max(highs)
        min_price = min(lows)
        if max_price == min_price:
            max_price += 1
            min_price -= 1
        price_span = max_price - min_price

        def price_to_y(price: float) -> float:
            return pad_top + (max_price - price) / price_span * chart_h

        count = len(candles)
        candle_gap = max(chart_w / max(count, 1), 3)
        body_width = max(min(candle_gap * 0.6, 10), 2)

        for i in range(6):
            y = pad_top + chart_h * i / 5
            canvas.create_line(pad_left, y, width - pad_right, y, fill="#374151")
            price = max_price - price_span * i / 5
            canvas.create_text(pad_left - 6, y, text=f"{price:.0f}", fill="#d1d5db", anchor="e", font=("Consolas", 9))

        for index, candle in enumerate(candles):
            center_x = pad_left + candle_gap * index + candle_gap / 2
            open_y = price_to_y(candle.open)
            close_y = price_to_y(candle.close)
            high_y = price_to_y(candle.high)
            low_y = price_to_y(candle.low)
            color = "#22c55e" if candle.close >= candle.open else "#ef4444"
            canvas.create_line(center_x, high_y, center_x, low_y, fill=color, width=1)
            top = min(open_y, close_y)
            bottom = max(open_y, close_y)
            if abs(bottom - top) < 1:
                bottom = top + 1
            canvas.create_rectangle(center_x - body_width / 2, top, center_x + body_width / 2, bottom, fill=color, outline=color)

        last = candles[-1]
        canvas.create_text(
            pad_left,
            8,
            text=f"最新: O {last.open:.2f}  H {last.high:.2f}  L {last.low:.2f}  C {last.close:.2f}",
            anchor="w",
            fill="#f9fafb",
            font=("Consolas", 10, "bold"),
        )
        canvas.create_text(
            width - pad_right,
            height - 16,
            text=f"起始 {candles[0].timestamp.strftime('%m-%d %H:%M')}    结束 {candles[-1].timestamp.strftime('%m-%d %H:%M')}",
            anchor="e",
            fill="#d1d5db",
            font=("Consolas", 9),
        )

    def _map_signal(self, action: str, reason: str) -> str:
        action_map = {"buy": "买入", "sell": "卖出", "hold": "观望"}
        prefix = action_map.get(action, action)
        return f"{prefix}（{reason}）" if reason else prefix

    def _map_position(self, state: str, qty: float) -> str:
        state_map = {"flat": "空仓", "long": "持有多单"}
        prefix = state_map.get(state, state)
        return f"{prefix} / 数量 {qty:.6f}"

    def _map_recommendation(self, recommendation: str) -> str:
        mapping = {
            "enter_long": "建议开多",
            "exit_long": "建议平仓",
            "hold_long": "继续持有",
            "stand_aside": "继续观望",
        }
        return mapping.get(recommendation, recommendation)

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
        messagebox.showerror("ETH 15分钟交易信号桌面版", str(exc))
        raise
