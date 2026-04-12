from __future__ import annotations

# 桌面版主程序：
# 1. 读取 preset 参数
# 2. 实时拉取 OKX ETH-USDT 15m 数据
# 3. 以更接近行情软件的方式显示中文界面
# 4. 绘制最近一段 K 线图
# 5. 显示信号、仓位、最近成交、原始 JSON
# 6. 出错时把详细日志写入用户目录，便于排查

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

BG = "#0b1220"
PANEL = "#111827"
PANEL_ALT = "#172033"
BORDER = "#23314d"
TEXT = "#e5e7eb"
MUTED = "#94a3b8"
GREEN = "#22c55e"
RED = "#ef4444"
YELLOW = "#f59e0b"
BLUE = "#38bdf8"
WHITE = "#f8fafc"
GRID = "#24324a"


class SignalDesktopApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("ETH 15分钟量化信号终端")
        self.root.geometry("1440x920")
        self.root.minsize(1180, 780)
        self.root.configure(bg=BG)

        self.preset_path_var = tk.StringVar(value=str(DEFAULT_PRESET))
        self.refresh_seconds_var = tk.StringVar(value="15")
        self.status_var = tk.StringVar(value="系统已就绪")
        self.last_update_var = tk.StringVar(value="尚未刷新")

        self.strategy_var = tk.StringVar(value="-")
        self.price_var = tk.StringVar(value="-")
        self.signal_var = tk.StringVar(value="-")
        self.position_var = tk.StringVar(value="-")
        self.recommend_var = tk.StringVar(value="-")
        self.equity_var = tk.StringVar(value="-")
        self.cash_var = tk.StringVar(value="-")
        self.candle_var = tk.StringVar(value="-")
        self.badge_var = tk.StringVar(value="观望")

        self.signal_badge_bg = PANEL_ALT
        self.signal_badge_fg = WHITE
        self.last_candles = []
        self._refresh_job = None

        self._configure_style()
        self._build_ui()
        self.root.after(100, self.refresh_snapshot)

    def _configure_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("App.TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("AltPanel.TFrame", background=PANEL_ALT)
        style.configure("Card.TFrame", background=PANEL_ALT)
        style.configure("TLabelframe", background=PANEL, foreground=TEXT, bordercolor=BORDER)
        style.configure("TLabelframe.Label", background=PANEL, foreground=TEXT)
        style.configure("TLabel", background=PANEL, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", background=BG, foreground=WHITE, font=("Microsoft YaHei UI", 22, "bold"))
        style.configure("SubTitle.TLabel", background=BG, foreground=MUTED, font=("Microsoft YaHei UI", 10))
        style.configure("Header.TLabel", background=PANEL, foreground=TEXT, font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("MetricTitle.TLabel", background=PANEL_ALT, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("MetricValue.TLabel", background=PANEL_ALT, foreground=WHITE, font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Mini.TLabel", background=PANEL, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("Toolbar.TLabel", background=BG, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("TEntry", fieldbackground="#0f172a", foreground=WHITE, insertcolor=WHITE, bordercolor=BORDER)
        style.map("TEntry", fieldbackground=[("disabled", "#0f172a")])
        style.configure("Accent.TButton", background=BLUE, foreground="#08111d", borderwidth=0, focusthickness=0, padding=8)
        style.map("Accent.TButton", background=[("active", "#7dd3fc")])
        style.configure("Ghost.TButton", background=PANEL_ALT, foreground=TEXT, borderwidth=0, focusthickness=0, padding=8)
        style.map("Ghost.TButton", background=[("active", "#25324a")])
        style.configure("Treeview", background="#0f172a", fieldbackground="#0f172a", foreground=TEXT, bordercolor=BORDER, rowheight=26)
        style.configure("Treeview.Heading", background="#1d2940", foreground=WHITE, relief="flat", font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#1d4ed8")])
        style.map("Treeview.Heading", background=[("active", "#25324a")])
        style.configure("TNotebook", background=PANEL, borderwidth=0)
        style.configure("TNotebook.Tab", background="#152033", foreground=MUTED, padding=(14, 8), font=("Microsoft YaHei UI", 10))
        style.map("TNotebook.Tab", background=[("selected", PANEL_ALT)], foreground=[("selected", WHITE)])

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, style="App.TFrame", padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        self._build_top_bar(container)
        self._build_toolbar(container)
        self._build_summary_board(container)
        self._build_main_content(container)

    def _build_top_bar(self, parent) -> None:
        top = ttk.Frame(parent, style="App.TFrame")
        top.pack(fill=tk.X, pady=(0, 10))

        left = ttk.Frame(top, style="App.TFrame")
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(left, text="ETH 15分钟量化信号终端", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            left,
            text="OKX 实时行情 / 策略信号 / K线图 / 最近成交 / 原始数据",
            style="SubTitle.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        right = ttk.Frame(top, style="App.TFrame")
        right.pack(side=tk.RIGHT, anchor="e")
        self.signal_badge_label = tk.Label(
            right,
            textvariable=self.badge_var,
            bg=self.signal_badge_bg,
            fg=self.signal_badge_fg,
            font=("Microsoft YaHei UI", 12, "bold"),
            padx=16,
            pady=8,
            relief="flat",
        )
        self.signal_badge_label.pack(anchor="e")
        ttk.Label(right, textvariable=self.last_update_var, style="Toolbar.TLabel").pack(anchor="e", pady=(6, 0))

    def _build_toolbar(self, parent) -> None:
        bar = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        bar.pack(fill=tk.X, pady=(0, 10))
        bar.columnconfigure(1, weight=1)

        ttk.Label(bar, text="策略配置文件", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(bar, textvariable=self.preset_path_var).grid(row=0, column=1, sticky="ew", padx=10)
        ttk.Button(bar, text="立即刷新", style="Accent.TButton", command=self.refresh_snapshot).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(bar, text="重置为默认配置", style="Ghost.TButton", command=self._reset_preset).grid(row=0, column=3)

        ttk.Label(bar, text="自动刷新(秒)", style="Mini.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(bar, textvariable=self.refresh_seconds_var, width=10).grid(row=1, column=1, sticky="w", padx=10, pady=(10, 0))
        ttk.Label(bar, textvariable=self.status_var, style="Mini.TLabel").grid(row=1, column=2, columnspan=2, sticky="e", pady=(10, 0))

    def _build_summary_board(self, parent) -> None:
        board = ttk.Frame(parent, style="App.TFrame")
        board.pack(fill=tk.X, pady=(0, 10))
        for col in range(4):
            board.columnconfigure(col, weight=1)

        self._make_card(board, 0, 0, "策略", self.strategy_var)
        self._make_card(board, 0, 1, "最新价格", self.price_var)
        self._make_card(board, 0, 2, "交易信号", self.signal_var)
        self._make_card(board, 0, 3, "建议动作", self.recommend_var)
        self._make_card(board, 1, 0, "当前仓位", self.position_var)
        self._make_card(board, 1, 1, "账户权益", self.equity_var)
        self._make_card(board, 1, 2, "账户现金", self.cash_var)
        self._make_card(board, 1, 3, "最新K线时间", self.candle_var)

    def _make_card(self, parent, row: int, col: int, title: str, variable: tk.StringVar) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=12)
        card.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
        ttk.Label(card, text=title, style="MetricTitle.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=variable, style="MetricValue.TLabel", wraplength=280).pack(anchor="w", pady=(8, 0))

    def _build_main_content(self, parent) -> None:
        body = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(body, style="Panel.TFrame")
        right = ttk.Frame(body, style="Panel.TFrame")
        body.add(left, weight=4)
        body.add(right, weight=2)

        self._build_chart_panel(left)
        self._build_right_panel(right)

    def _build_chart_panel(self, parent) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(frame, style="Panel.TFrame")
        header.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(header, text="行情主图", style="Header.TLabel").pack(side=tk.LEFT)
        ttk.Label(header, text="最近80根 15m K线", style="Mini.TLabel").pack(side=tk.RIGHT)

        self.chart_canvas = tk.Canvas(frame, bg=BG, highlightthickness=0)
        self.chart_canvas.pack(fill=tk.BOTH, expand=True)
        self.chart_canvas.bind("<Configure>", lambda _event: self._redraw_chart())

        footer = ttk.Frame(frame, style="Panel.TFrame")
        footer.pack(fill=tk.X, pady=(8, 0))
        self.chart_footer_var = tk.StringVar(value="等待行情数据...")
        ttk.Label(footer, textvariable=self.chart_footer_var, style="Mini.TLabel").pack(side=tk.LEFT)

        self._draw_placeholder_chart()

    def _build_right_panel(self, parent) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        quick = ttk.LabelFrame(frame, text="交易面板", padding=10)
        quick.pack(fill=tk.X, pady=(0, 10))
        self.quick_hint_var = tk.StringVar(value="等待信号刷新")
        ttk.Label(quick, textvariable=self.quick_hint_var, style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            quick,
            text="说明：本桌面版只负责信号分析，不会自动下单。请结合风险管理手动执行。",
            style="Mini.TLabel",
            wraplength=360,
        ).pack(anchor="w", pady=(8, 0))

        notebook = ttk.Notebook(frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        trades_tab = ttk.Frame(notebook, style="Panel.TFrame")
        json_tab = ttk.Frame(notebook, style="Panel.TFrame")
        notebook.add(trades_tab, text="最近成交")
        notebook.add(json_tab, text="原始数据")

        columns = ("time", "side", "price", "qty", "reason")
        self.trade_tree = ttk.Treeview(trades_tab, columns=columns, show="headings", height=12)
        headings = {
            "time": "时间",
            "side": "方向",
            "price": "价格",
            "qty": "数量",
            "reason": "原因",
        }
        widths = {"time": 138, "side": 60, "price": 82, "qty": 82, "reason": 180}
        anchors = {"time": "w", "side": "center", "price": "e", "qty": "e", "reason": "w"}
        for col in columns:
            self.trade_tree.heading(col, text=headings[col])
            self.trade_tree.column(col, width=widths[col], anchor=anchors[col], stretch=col == "reason")
        self.trade_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        trade_scroll = ttk.Scrollbar(trades_tab, orient="vertical", command=self.trade_tree.yview)
        self.trade_tree.configure(yscrollcommand=trade_scroll.set)
        trade_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.json_text = tk.Text(json_tab, wrap=tk.WORD, font=("Consolas", 10), bg="#0f172a", fg=TEXT, insertbackground=WHITE, relief="flat")
        self.json_text.pack(fill=tk.BOTH, expand=True)
        self.json_text.insert(tk.END, "等待行情数据...")
        self.json_text.config(state=tk.DISABLED)

    def _reset_preset(self) -> None:
        self.preset_path_var.set(str(DEFAULT_PRESET))

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
            self.last_candles = candles[-CHART_CANDLES:]
            snapshot_dict = snapshot.to_dict()
            self._update_summary(snapshot_dict)
            self._redraw_chart()
            self._update_trades(snapshot_dict.get("recent_trades", []))
            self._set_json_text(json.dumps(snapshot_dict, indent=2, ensure_ascii=False))
            self.status_var.set("连接正常，数据已刷新")
            self.last_update_var.set(f"上次刷新：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as exc:
            details = traceback.format_exc()
            LOG_PATH.write_text(details, encoding="utf-8")
            self.status_var.set(f"刷新失败：{exc}")
            self.last_update_var.set(f"上次刷新：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            self.last_candles = []
            self._draw_placeholder_chart(str(exc))
            self._update_trades([])
            self.quick_hint_var.set("界面刷新失败，请查看日志")
            self._set_json_text(
                "刷新失败\n\n"
                f"错误信息：{exc}\n\n"
                f"日志文件：{LOG_PATH}\n\n"
                "请把错误截图或日志发给我。"
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
        self.cash_var.set(f"{snapshot['cash']:.2f} USDT")
        self.candle_var.set(snapshot["latest_timestamp"].replace("T", " "))
        self.quick_hint_var.set(f"当前建议：{recommendation_text} | 最新信号：{signal_text}")
        self._set_badge(snapshot["latest_signal_action"], snapshot["recommendation"])

    def _set_badge(self, action: str, recommendation: str) -> None:
        if action == "buy" or recommendation == "enter_long":
            text = "买入信号"
            bg = GREEN
            fg = "#052e16"
        elif action == "sell" or recommendation == "exit_long":
            text = "卖出信号"
            bg = RED
            fg = "#fff1f2"
        else:
            text = "观望中"
            bg = YELLOW
            fg = "#1f2937"
        self.badge_var.set(text)
        self.signal_badge_bg = bg
        self.signal_badge_fg = fg
        self.signal_badge_label.configure(bg=bg, fg=fg)

    def _update_trades(self, trades: list[dict]) -> None:
        for item in self.trade_tree.get_children():
            self.trade_tree.delete(item)
        for trade in trades:
            side = "买入" if trade["side"] == "buy" else "卖出"
            self.trade_tree.insert(
                "",
                tk.END,
                values=(
                    trade["timestamp"].replace("T", " "),
                    side,
                    f"{trade['price']:.2f}",
                    f"{trade['quantity']:.6f}",
                    trade.get("reason", ""),
                ),
            )

    def _set_json_text(self, value: str) -> None:
        self.json_text.config(state=tk.NORMAL)
        self.json_text.delete("1.0", tk.END)
        self.json_text.insert(tk.END, value)
        self.json_text.config(state=tk.DISABLED)

    def _draw_placeholder_chart(self, extra_text: str | None = None) -> None:
        canvas = self.chart_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 500)
        height = max(canvas.winfo_height(), 340)
        canvas.create_rectangle(0, 0, width, height, fill=BG, outline=BG)
        message = "等待行情数据..."
        if extra_text:
            message = f"图表暂时不可用\n{extra_text}"
        canvas.create_text(width / 2, height / 2, text=message, fill=MUTED, font=("Microsoft YaHei UI", 15, "bold"))
        self.chart_footer_var.set("暂无K线数据")

    def _redraw_chart(self) -> None:
        if not self.last_candles:
            self._draw_placeholder_chart()
            return
        self._draw_candles(self.last_candles)

    def _draw_candles(self, candles) -> None:
        canvas = self.chart_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 700)
        height = max(canvas.winfo_height(), 420)
        canvas.create_rectangle(0, 0, width, height, fill=BG, outline=BG)

        if not candles:
            self._draw_placeholder_chart()
            return

        pad_left, pad_top, pad_right, pad_bottom = 72, 24, 22, 44
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
        body_width = max(min(candle_gap * 0.62, 12), 3)

        canvas.create_rectangle(pad_left, pad_top, width - pad_right, height - pad_bottom, outline=BORDER, width=1)

        for i in range(6):
            y = pad_top + chart_h * i / 5
            canvas.create_line(pad_left, y, width - pad_right, y, fill=GRID, dash=(2, 4))
            price = max_price - price_span * i / 5
            canvas.create_text(pad_left - 8, y, text=f"{price:.0f}", fill=MUTED, anchor="e", font=("Consolas", 10))

        step = max(1, count // 6)
        for i in range(0, count, step):
            x = pad_left + candle_gap * i + candle_gap / 2
            canvas.create_line(x, pad_top, x, height - pad_bottom, fill="#182338", dash=(2, 6))
            canvas.create_text(
                x,
                height - pad_bottom + 16,
                text=candles[i].timestamp.strftime("%m-%d\n%H:%M"),
                fill=MUTED,
                anchor="n",
                font=("Consolas", 9),
            )

        prev_close = None
        for index, candle in enumerate(candles):
            center_x = pad_left + candle_gap * index + candle_gap / 2
            open_y = price_to_y(candle.open)
            close_y = price_to_y(candle.close)
            high_y = price_to_y(candle.high)
            low_y = price_to_y(candle.low)
            color = GREEN if candle.close >= candle.open else RED
            wick_color = color
            canvas.create_line(center_x, high_y, center_x, low_y, fill=wick_color, width=1)
            top = min(open_y, close_y)
            bottom = max(open_y, close_y)
            if abs(bottom - top) < 1:
                bottom = top + 1
            canvas.create_rectangle(center_x - body_width / 2, top, center_x + body_width / 2, bottom, fill=color, outline=color)

            if prev_close is not None:
                prev_y = price_to_y(prev_close)
                canvas.create_line(center_x - candle_gap, prev_y, center_x, close_y, fill=BLUE, width=1, smooth=True)
            prev_close = candle.close

        last = candles[-1]
        change = last.close - candles[0].close
        change_pct = change / candles[0].close * 100 if candles[0].close else 0
        change_color = GREEN if change >= 0 else RED
        canvas.create_text(
            pad_left,
            10,
            text=f"ETH-USDT  15m   O {last.open:.2f}  H {last.high:.2f}  L {last.low:.2f}  C {last.close:.2f}",
            anchor="w",
            fill=WHITE,
            font=("Consolas", 11, "bold"),
        )
        canvas.create_text(
            width - pad_right,
            10,
            text=f"区间变化 {change:+.2f} ({change_pct:+.2f}%)",
            anchor="e",
            fill=change_color,
            font=("Consolas", 11, "bold"),
        )
        self.chart_footer_var.set(
            f"显示区间：{candles[0].timestamp.strftime('%Y-%m-%d %H:%M')}  ->  {candles[-1].timestamp.strftime('%Y-%m-%d %H:%M')}"
        )

    def _map_signal(self, action: str, reason: str) -> str:
        action_map = {"buy": "买入", "sell": "卖出", "hold": "观望"}
        prefix = action_map.get(action, action)
        return f"{prefix} / {reason}" if reason else prefix

    def _map_position(self, state: str, qty: float) -> str:
        state_map = {"flat": "空仓", "long": "持多"}
        prefix = state_map.get(state, state)
        return f"{prefix} ({qty:.6f})"

    def _map_recommendation(self, recommendation: str) -> str:
        mapping = {
            "enter_long": "建议开多",
            "exit_long": "建议平仓",
            "hold_long": "继续持有",
            "stand_aside": "继续观望",
        }
        return mapping.get(recommendation, recommendation)

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    try:
        SignalDesktopApp().run()
    except Exception as exc:
        messagebox.showerror("ETH 15分钟量化信号终端", str(exc))
        raise
