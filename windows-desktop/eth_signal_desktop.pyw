from __future__ import annotations

# 桌面版主程序：
# 1. 读取 preset 参数
# 2. 实时拉取 OKX ETH-USDT 15m 数据
# 3. 用更接近专业行情终端的方式展示中文界面
# 4. 主图支持 K 线、MA 均线、买卖点、十字光标
# 5. 副图支持 RSI 和 MACD
# 6. 支持主题切换、布局切换、自动刷新
# 7. 出错时把详细日志写入用户目录，便于排查

import json
import math
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
from eth_backtester.indicators import exponential_moving_average, relative_strength_index, simple_moving_average
from eth_backtester.live import build_okx_live_snapshot_bundle

DEFAULT_PRESET = ROOT / "presets" / "okx_15m_mtf_production_candidate.json"
LOG_PATH = Path.home() / "ETH_15M_Signal_Desktop.log"
CHART_CANDLES = 100
CROSSHAIR_TAG = "crosshair"

THEMES = {
    "深色专业": {
        "bg": "#0b1220",
        "panel": "#111827",
        "panel_alt": "#172033",
        "panel_soft": "#0f172a",
        "border": "#23314d",
        "text": "#e5e7eb",
        "muted": "#94a3b8",
        "green": "#22c55e",
        "red": "#ef4444",
        "yellow": "#f59e0b",
        "blue": "#38bdf8",
        "purple": "#a78bfa",
        "orange": "#fb923c",
        "white": "#f8fafc",
        "grid": "#24324a",
        "badge_text_dark": "#1f2937",
        "badge_text_light": "#f8fafc",
    },
    "浅色简洁": {
        "bg": "#e8edf5",
        "panel": "#ffffff",
        "panel_alt": "#f3f6fb",
        "panel_soft": "#ffffff",
        "border": "#c8d3e1",
        "text": "#0f172a",
        "muted": "#64748b",
        "green": "#16a34a",
        "red": "#dc2626",
        "yellow": "#d97706",
        "blue": "#0284c7",
        "purple": "#7c3aed",
        "orange": "#ea580c",
        "white": "#ffffff",
        "grid": "#d6deeb",
        "badge_text_dark": "#111827",
        "badge_text_light": "#ffffff",
    },
}


class SignalDesktopApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("ETH 15分钟量化信号终端")
        self.root.geometry("1520x980")
        self.root.minsize(1240, 820)

        self.theme_var = tk.StringVar(value="深色专业")
        self.layout_var = tk.StringVar(value="左右布局")
        self.show_ma_var = tk.BooleanVar(value=True)
        self.show_markers_var = tk.BooleanVar(value=True)
        self.show_crosshair_var = tk.BooleanVar(value=True)
        self.preset_path_var = tk.StringVar(value=str(DEFAULT_PRESET))
        self.refresh_seconds_var = tk.StringVar(value="15")
        self.status_var = tk.StringVar(value="系统已就绪")
        self.last_update_var = tk.StringVar(value="尚未刷新")
        self.chart_footer_var = tk.StringVar(value="等待行情数据...")
        self.hover_info_var = tk.StringVar(value="将鼠标移动到图表上查看详细价格")
        self.quick_hint_var = tk.StringVar(value="等待信号刷新")

        self.strategy_var = tk.StringVar(value="-")
        self.price_var = tk.StringVar(value="-")
        self.signal_var = tk.StringVar(value="-")
        self.position_var = tk.StringVar(value="-")
        self.recommend_var = tk.StringVar(value="-")
        self.equity_var = tk.StringVar(value="-")
        self.cash_var = tk.StringVar(value="-")
        self.candle_var = tk.StringVar(value="-")
        self.badge_var = tk.StringVar(value="观望中")

        self.theme = THEMES[self.theme_var.get()]
        self.signal_badge_bg = self.theme["panel_alt"]
        self.signal_badge_fg = self.theme["white"]

        self.last_candles = []
        self.last_snapshot = None
        self.chart_geometry = None
        self._refresh_job = None

        self._configure_style()
        self._build_ui()
        self.root.after(100, self.refresh_snapshot)

    def _configure_style(self) -> None:
        t = self.theme
        self.root.configure(bg=t["bg"])

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("App.TFrame", background=t["bg"])
        style.configure("Panel.TFrame", background=t["panel"])
        style.configure("Card.TFrame", background=t["panel_alt"])
        style.configure("TLabelframe", background=t["panel"], foreground=t["text"], bordercolor=t["border"])
        style.configure("TLabelframe.Label", background=t["panel"], foreground=t["text"])
        style.configure("TLabel", background=t["panel"], foreground=t["text"], font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", background=t["bg"], foreground=t["white"], font=("Microsoft YaHei UI", 22, "bold"))
        style.configure("SubTitle.TLabel", background=t["bg"], foreground=t["muted"], font=("Microsoft YaHei UI", 10))
        style.configure("Header.TLabel", background=t["panel"], foreground=t["text"], font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("MetricTitle.TLabel", background=t["panel_alt"], foreground=t["muted"], font=("Microsoft YaHei UI", 9))
        style.configure("MetricValue.TLabel", background=t["panel_alt"], foreground=t["white"], font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("Mini.TLabel", background=t["panel"], foreground=t["muted"], font=("Microsoft YaHei UI", 9))
        style.configure("Toolbar.TLabel", background=t["bg"], foreground=t["muted"], font=("Microsoft YaHei UI", 9))
        style.configure("TCheckbutton", background=t["panel"], foreground=t["text"])
        style.map("TCheckbutton", background=[("active", t["panel"])])
        style.configure("TCombobox", fieldbackground=t["panel_soft"], background=t["panel_soft"], foreground=t["text"], bordercolor=t["border"], arrowsize=14)
        style.configure("TEntry", fieldbackground=t["panel_soft"], foreground=t["text"], insertcolor=t["text"], bordercolor=t["border"])
        style.map("TEntry", fieldbackground=[("disabled", t["panel_soft"])])
        style.configure("Accent.TButton", background=t["blue"], foreground=t["white"], borderwidth=0, focusthickness=0, padding=8)
        style.map("Accent.TButton", background=[("active", t["purple"])])
        style.configure("Ghost.TButton", background=t["panel_alt"], foreground=t["text"], borderwidth=0, focusthickness=0, padding=8)
        style.map("Ghost.TButton", background=[("active", t["grid"])])
        style.configure("Treeview", background=t["panel_soft"], fieldbackground=t["panel_soft"], foreground=t["text"], bordercolor=t["border"], rowheight=26)
        style.configure("Treeview.Heading", background=t["panel_alt"], foreground=t["white"], relief="flat", font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Treeview", background=[("selected", t["blue"])])
        style.map("Treeview.Heading", background=[("active", t["grid"])])
        style.configure("TNotebook", background=t["panel"], borderwidth=0)
        style.configure("TNotebook.Tab", background=t["panel_alt"], foreground=t["muted"], padding=(14, 8), font=("Microsoft YaHei UI", 10))
        style.map("TNotebook.Tab", background=[("selected", t["panel_soft"])], foreground=[("selected", t["text"])])

    def _build_ui(self) -> None:
        self.container = ttk.Frame(self.root, style="App.TFrame", padding=12)
        self.container.pack(fill=tk.BOTH, expand=True)

        self._build_top_bar(self.container)
        self._build_toolbar(self.container)
        self._build_summary_board(self.container)
        self._build_main_content(self.container)

    def _build_top_bar(self, parent) -> None:
        top = ttk.Frame(parent, style="App.TFrame")
        top.pack(fill=tk.X, pady=(0, 10))

        left = ttk.Frame(top, style="App.TFrame")
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(left, text="ETH 15分钟量化信号终端", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="OKX 实时行情 / K线主图 / RSI / MACD / 买卖点 / 信号面板", style="SubTitle.TLabel").pack(anchor="w", pady=(3, 0))

        right = ttk.Frame(top, style="App.TFrame")
        right.pack(side=tk.RIGHT, anchor="e")
        self.signal_badge_label = tk.Label(right, textvariable=self.badge_var, bg=self.signal_badge_bg, fg=self.signal_badge_fg, font=("Microsoft YaHei UI", 12, "bold"), padx=16, pady=8, relief="flat")
        self.signal_badge_label.pack(anchor="e")
        ttk.Label(right, textvariable=self.last_update_var, style="Toolbar.TLabel").pack(anchor="e", pady=(6, 0))

    def _build_toolbar(self, parent) -> None:
        bar = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        bar.pack(fill=tk.X, pady=(0, 10))
        for col in (1, 5):
            bar.columnconfigure(col, weight=1)

        ttk.Label(bar, text="策略配置文件", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(bar, textvariable=self.preset_path_var).grid(row=0, column=1, sticky="ew", padx=10)
        ttk.Button(bar, text="立即刷新", style="Accent.TButton", command=self.refresh_snapshot).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(bar, text="重置默认配置", style="Ghost.TButton", command=self._reset_preset).grid(row=0, column=3, padx=(0, 8))
        ttk.Label(bar, text="主题", style="Mini.TLabel").grid(row=0, column=4, sticky="e")
        theme_box = ttk.Combobox(bar, textvariable=self.theme_var, state="readonly", values=list(THEMES.keys()), width=10)
        theme_box.grid(row=0, column=5, sticky="w", padx=8)
        theme_box.bind("<<ComboboxSelected>>", lambda _e: self._on_theme_change())
        ttk.Label(bar, text="布局", style="Mini.TLabel").grid(row=0, column=6, sticky="e")
        layout_box = ttk.Combobox(bar, textvariable=self.layout_var, state="readonly", values=["左右布局", "上下布局"], width=8)
        layout_box.grid(row=0, column=7, sticky="w", padx=8)
        layout_box.bind("<<ComboboxSelected>>", lambda _e: self._apply_layout())

        ttk.Label(bar, text="自动刷新(秒)", style="Mini.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(bar, textvariable=self.refresh_seconds_var, width=10).grid(row=1, column=1, sticky="w", padx=10, pady=(10, 0))
        ttk.Checkbutton(bar, text="显示 MA5/10/20", variable=self.show_ma_var, command=self._redraw_chart).grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Checkbutton(bar, text="显示买卖点", variable=self.show_markers_var, command=self._redraw_chart).grid(row=1, column=3, sticky="w", pady=(10, 0))
        ttk.Checkbutton(bar, text="显示十字光标", variable=self.show_crosshair_var).grid(row=1, column=4, sticky="w", pady=(10, 0))
        ttk.Label(bar, textvariable=self.status_var, style="Mini.TLabel").grid(row=1, column=5, columnspan=3, sticky="e", pady=(10, 0))

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
        ttk.Label(card, textvariable=variable, style="MetricValue.TLabel", wraplength=300).pack(anchor="w", pady=(8, 0))

    def _build_main_content(self, parent) -> None:
        self.body = ttk.Frame(parent, style="App.TFrame")
        self.body.pack(fill=tk.BOTH, expand=True)
        self.body.columnconfigure(0, weight=4)
        self.body.columnconfigure(1, weight=2)
        self.body.rowconfigure(0, weight=1)
        self.body.rowconfigure(1, weight=1)

        self.chart_panel = ttk.Frame(self.body, style="Panel.TFrame", padding=10)
        self.right_panel = ttk.Frame(self.body, style="Panel.TFrame", padding=10)

        self._build_chart_panel(self.chart_panel)
        self._build_right_panel(self.right_panel)
        self._apply_layout()

    def _build_chart_panel(self, parent) -> None:
        header = ttk.Frame(parent, style="Panel.TFrame")
        header.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(header, text="多图联动行情区", style="Header.TLabel").pack(side=tk.LEFT)
        ttk.Label(header, textvariable=self.hover_info_var, style="Mini.TLabel").pack(side=tk.RIGHT)

        self.chart_stack = ttk.Frame(parent, style="Panel.TFrame")
        self.chart_stack.pack(fill=tk.BOTH, expand=True)
        self.chart_stack.columnconfigure(0, weight=1)
        self.chart_stack.rowconfigure(0, weight=5)
        self.chart_stack.rowconfigure(1, weight=2)
        self.chart_stack.rowconfigure(2, weight=2)

        self.price_canvas = tk.Canvas(self.chart_stack, highlightthickness=0)
        self.rsi_canvas = tk.Canvas(self.chart_stack, highlightthickness=0)
        self.macd_canvas = tk.Canvas(self.chart_stack, highlightthickness=0)
        self.price_canvas.grid(row=0, column=0, sticky="nsew")
        self.rsi_canvas.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.macd_canvas.grid(row=2, column=0, sticky="nsew", pady=(8, 0))

        for canvas in (self.price_canvas, self.rsi_canvas, self.macd_canvas):
            canvas.bind("<Configure>", lambda _e: self._redraw_chart())
            canvas.bind("<Motion>", self._on_chart_motion)
            canvas.bind("<Leave>", self._on_chart_leave)

        footer = ttk.Frame(parent, style="Panel.TFrame")
        footer.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(footer, textvariable=self.chart_footer_var, style="Mini.TLabel").pack(side=tk.LEFT)

        self._draw_placeholder_chart()

    def _build_right_panel(self, parent) -> None:
        quick = ttk.LabelFrame(parent, text="交易面板", padding=10)
        quick.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(quick, textvariable=self.quick_hint_var, style="Header.TLabel").pack(anchor="w")
        ttk.Label(quick, text="说明：本桌面版只负责信号分析，不会自动下单。请结合风险管理手动执行。", style="Mini.TLabel", wraplength=420).pack(anchor="w", pady=(8, 0))

        legend = ttk.LabelFrame(parent, text="图表说明", padding=10)
        legend.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(legend, text="绿色K线=上涨  红色K线=下跌", style="Mini.TLabel").pack(anchor="w")
        ttk.Label(legend, text="蓝线=MA5  紫线=MA10  橙线=MA20", style="Mini.TLabel").pack(anchor="w", pady=(4, 0))
        ttk.Label(legend, text="▲=买入点  ▼=卖出点", style="Mini.TLabel").pack(anchor="w", pady=(4, 0))
        ttk.Label(legend, text="下方副图：RSI 与 MACD", style="Mini.TLabel").pack(anchor="w", pady=(4, 0))

        notebook = ttk.Notebook(parent)
        notebook.pack(fill=tk.BOTH, expand=True)

        trades_tab = ttk.Frame(notebook, style="Panel.TFrame")
        json_tab = ttk.Frame(notebook, style="Panel.TFrame")
        notebook.add(trades_tab, text="最近成交")
        notebook.add(json_tab, text="原始数据")

        columns = ("time", "side", "price", "qty", "reason")
        self.trade_tree = ttk.Treeview(trades_tab, columns=columns, show="headings", height=12)
        headings = {"time": "时间", "side": "方向", "price": "价格", "qty": "数量", "reason": "原因"}
        widths = {"time": 142, "side": 60, "price": 86, "qty": 90, "reason": 210}
        anchors = {"time": "w", "side": "center", "price": "e", "qty": "e", "reason": "w"}
        for col in columns:
            self.trade_tree.heading(col, text=headings[col])
            self.trade_tree.column(col, width=widths[col], anchor=anchors[col], stretch=col == "reason")
        self.trade_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        trade_scroll = ttk.Scrollbar(trades_tab, orient="vertical", command=self.trade_tree.yview)
        self.trade_tree.configure(yscrollcommand=trade_scroll.set)
        trade_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.json_text = tk.Text(json_tab, wrap=tk.WORD, font=("Consolas", 10), relief="flat")
        self.json_text.pack(fill=tk.BOTH, expand=True)
        self.json_text.insert(tk.END, "等待行情数据...")
        self.json_text.config(state=tk.DISABLED)
        self._apply_text_theme()

    def _apply_text_theme(self) -> None:
        t = self.theme
        if hasattr(self, "json_text"):
            self.json_text.configure(bg=t["panel_soft"], fg=t["text"], insertbackground=t["text"])
        if hasattr(self, "price_canvas"):
            for canvas in (self.price_canvas, self.rsi_canvas, self.macd_canvas):
                canvas.configure(bg=t["bg"])

    def _on_theme_change(self) -> None:
        self.theme = THEMES[self.theme_var.get()]
        self.signal_badge_bg = self.theme["panel_alt"]
        self.signal_badge_fg = self.theme["white"]
        self._configure_style()
        self._apply_text_theme()
        self.signal_badge_label.configure(bg=self.signal_badge_bg, fg=self.signal_badge_fg)
        self._redraw_chart()

    def _apply_layout(self) -> None:
        self.chart_panel.grid_forget()
        self.right_panel.grid_forget()
        if self.layout_var.get() == "上下布局":
            self.body.columnconfigure(0, weight=1)
            self.body.columnconfigure(1, weight=0)
            self.body.rowconfigure(0, weight=3)
            self.body.rowconfigure(1, weight=2)
            self.chart_panel.grid(row=0, column=0, sticky="nsew")
            self.right_panel.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        else:
            self.body.columnconfigure(0, weight=4)
            self.body.columnconfigure(1, weight=2)
            self.body.rowconfigure(0, weight=1)
            self.body.rowconfigure(1, weight=0)
            self.chart_panel.grid(row=0, column=0, sticky="nsew")
            self.right_panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self._redraw_chart()

    def _reset_preset(self) -> None:
        self.preset_path_var.set(str(DEFAULT_PRESET))

    def _build_args(self):
        preset_path = Path(self.preset_path_var.get()).expanduser()
        parser = build_parser()
        args = parser.parse_args([
            "--preset", str(preset_path), "--live-okx-snapshot", "--okx-inst-id", "ETH-USDT", "--okx-bar", "15m", "--okx-candles", "300"
        ])
        return apply_preset_args(args)

    def refresh_snapshot(self) -> None:
        self._cancel_refresh_job()
        try:
            args = self._build_args()
            candles, snapshot = build_okx_live_snapshot_bundle(args)
            self.last_candles = candles[-CHART_CANDLES:]
            self.last_snapshot = snapshot.to_dict()
            self._update_summary(self.last_snapshot)
            self._redraw_chart()
            self._update_trades(self.last_snapshot.get("recent_trades", []))
            self._set_json_text(json.dumps(self.last_snapshot, indent=2, ensure_ascii=False))
            self.status_var.set("连接正常，数据已刷新")
            self.last_update_var.set(f"上次刷新：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as exc:
            details = traceback.format_exc()
            LOG_PATH.write_text(details, encoding="utf-8")
            self.status_var.set(f"刷新失败：{exc}")
            self.last_update_var.set(f"上次刷新：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            self.last_candles = []
            self.last_snapshot = None
            self._draw_placeholder_chart(str(exc))
            self._update_trades([])
            self.quick_hint_var.set("界面刷新失败，请查看日志")
            self._set_json_text(f"刷新失败\n\n错误信息：{exc}\n\n日志文件：{LOG_PATH}\n\n请把错误截图或日志发给我。")
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
        t = self.theme
        if action == "buy" or recommendation == "enter_long":
            text, bg, fg = "买入信号", t["green"], t["badge_text_dark"]
        elif action == "sell" or recommendation == "exit_long":
            text, bg, fg = "卖出信号", t["red"], t["badge_text_light"]
        else:
            text, bg, fg = "观望中", t["yellow"], t["badge_text_dark"]
        self.badge_var.set(text)
        self.signal_badge_bg = bg
        self.signal_badge_fg = fg
        self.signal_badge_label.configure(bg=bg, fg=fg)

    def _update_trades(self, trades: list[dict]) -> None:
        for item in self.trade_tree.get_children():
            self.trade_tree.delete(item)
        for trade in trades:
            side = "买入" if trade["side"] == "buy" else "卖出"
            self.trade_tree.insert("", tk.END, values=(trade["timestamp"].replace("T", " "), side, f"{trade['price']:.2f}", f"{trade['quantity']:.6f}", trade.get("reason", "")))

    def _set_json_text(self, value: str) -> None:
        self.json_text.config(state=tk.NORMAL)
        self.json_text.delete("1.0", tk.END)
        self.json_text.insert(tk.END, value)
        self.json_text.config(state=tk.DISABLED)

    def _draw_placeholder_chart(self, extra_text: str | None = None) -> None:
        message = "等待行情数据..." if not extra_text else f"图表暂时不可用\n{extra_text}"
        for canvas in (self.price_canvas, self.rsi_canvas, self.macd_canvas):
            width = max(canvas.winfo_width(), 600)
            height = max(canvas.winfo_height(), 150)
            canvas.delete("all")
            canvas.create_rectangle(0, 0, width, height, fill=self.theme["bg"], outline=self.theme["bg"])
            canvas.create_text(width / 2, height / 2, text=message, fill=self.theme["muted"], font=("Microsoft YaHei UI", 14, "bold"))
        self.chart_footer_var.set("暂无K线数据")
        self.hover_info_var.set("将鼠标移动到图表上查看详细价格")
        self.chart_geometry = None

    def _redraw_chart(self) -> None:
        if not self.last_candles:
            self._draw_placeholder_chart()
            return
        self._draw_price_panel(self.last_candles)
        self._draw_rsi_panel(self.last_candles)
        self._draw_macd_panel(self.last_candles)

    def _draw_price_panel(self, candles) -> None:
        t = self.theme
        canvas = self.price_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 700)
        height = max(canvas.winfo_height(), 380)
        canvas.create_rectangle(0, 0, width, height, fill=t["bg"], outline=t["bg"])

        pad_left, pad_top, pad_right, pad_bottom = 72, 28, 22, 30
        chart_w = width - pad_left - pad_right
        chart_h = height - pad_top - pad_bottom
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        max_price = max(highs)
        min_price = min(lows)
        if math.isclose(max_price, min_price):
            max_price += 1
            min_price -= 1
        price_span = max_price - min_price

        def price_to_y(price: float) -> float:
            return pad_top + (max_price - price) / price_span * chart_h

        count = len(candles)
        candle_gap = max(chart_w / max(count, 1), 3)
        body_width = max(min(candle_gap * 0.6, 12), 3)
        self.chart_geometry = {
            "pad_left": pad_left,
            "pad_right": pad_right,
            "pad_top": pad_top,
            "pad_bottom": pad_bottom,
            "chart_w": chart_w,
            "chart_h": chart_h,
            "count": count,
            "candle_gap": candle_gap,
            "price_max": max_price,
            "price_min": min_price,
            "price_to_y": price_to_y,
        }

        canvas.create_rectangle(pad_left, pad_top, width - pad_right, height - pad_bottom, outline=t["border"], width=1)
        for i in range(6):
            y = pad_top + chart_h * i / 5
            canvas.create_line(pad_left, y, width - pad_right, y, fill=t["grid"], dash=(2, 4))
            price = max_price - price_span * i / 5
            canvas.create_text(pad_left - 8, y, text=f"{price:.0f}", fill=t["muted"], anchor="e", font=("Consolas", 10))

        step = max(1, count // 8)
        for i in range(0, count, step):
            x = pad_left + candle_gap * i + candle_gap / 2
            canvas.create_line(x, pad_top, x, height - pad_bottom, fill=t["grid"], dash=(2, 6))

        closes = [c.close for c in candles]
        ma5 = simple_moving_average(closes, 5)
        ma10 = simple_moving_average(closes, 10)
        ma20 = simple_moving_average(closes, 20)

        prev_close = None
        for index, candle in enumerate(candles):
            center_x = pad_left + candle_gap * index + candle_gap / 2
            open_y = price_to_y(candle.open)
            close_y = price_to_y(candle.close)
            high_y = price_to_y(candle.high)
            low_y = price_to_y(candle.low)
            color = t["green"] if candle.close >= candle.open else t["red"]
            canvas.create_line(center_x, high_y, center_x, low_y, fill=color, width=1)
            top = min(open_y, close_y)
            bottom = max(open_y, close_y)
            if abs(bottom - top) < 1:
                bottom = top + 1
            canvas.create_rectangle(center_x - body_width / 2, top, center_x + body_width / 2, bottom, fill=color, outline=color)
            if prev_close is not None:
                prev_y = price_to_y(prev_close)
                canvas.create_line(center_x - candle_gap, prev_y, center_x, close_y, fill=t["blue"], width=1, smooth=True)
            prev_close = candle.close

        if self.show_ma_var.get():
            self._draw_line_series(canvas, ma5, price_to_y, pad_left, candle_gap, t["blue"], width=2)
            self._draw_line_series(canvas, ma10, price_to_y, pad_left, candle_gap, t["purple"], width=2)
            self._draw_line_series(canvas, ma20, price_to_y, pad_left, candle_gap, t["orange"], width=2)

        if self.show_markers_var.get() and self.last_snapshot:
            trades = self.last_snapshot.get("recent_trades", [])
            trade_map = {trade["timestamp"]: trade for trade in trades}
            for idx, candle in enumerate(candles):
                key = candle.timestamp.isoformat()
                trade = trade_map.get(key)
                if not trade:
                    continue
                center_x = pad_left + candle_gap * idx + candle_gap / 2
                if trade["side"] == "buy":
                    y = price_to_y(candle.low) + 14
                    canvas.create_text(center_x, y, text="▲", fill=t["green"], font=("Consolas", 14, "bold"))
                else:
                    y = price_to_y(candle.high) - 14
                    canvas.create_text(center_x, y, text="▼", fill=t["red"], font=("Consolas", 14, "bold"))

        last = candles[-1]
        change = last.close - candles[0].close
        change_pct = change / candles[0].close * 100 if candles[0].close else 0
        change_color = t["green"] if change >= 0 else t["red"]
        canvas.create_text(pad_left, 12, text=f"ETH-USDT  15m   O {last.open:.2f}  H {last.high:.2f}  L {last.low:.2f}  C {last.close:.2f}", anchor="w", fill=t["white"], font=("Consolas", 11, "bold"))
        canvas.create_text(width - pad_right, 12, text=f"区间变化 {change:+.2f} ({change_pct:+.2f}%)", anchor="e", fill=change_color, font=("Consolas", 11, "bold"))
        if self.show_ma_var.get():
            canvas.create_text(pad_left, height - 12, text="MA5", fill=t["blue"], anchor="w", font=("Consolas", 9, "bold"))
            canvas.create_text(pad_left + 45, height - 12, text="MA10", fill=t["purple"], anchor="w", font=("Consolas", 9, "bold"))
            canvas.create_text(pad_left + 98, height - 12, text="MA20", fill=t["orange"], anchor="w", font=("Consolas", 9, "bold"))
        self.chart_footer_var.set(f"显示区间：{candles[0].timestamp.strftime('%Y-%m-%d %H:%M')} -> {candles[-1].timestamp.strftime('%Y-%m-%d %H:%M')}")

    def _draw_rsi_panel(self, candles) -> None:
        t = self.theme
        canvas = self.rsi_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 700)
        height = max(canvas.winfo_height(), 150)
        canvas.create_rectangle(0, 0, width, height, fill=t["bg"], outline=t["bg"])
        pad_left, pad_top, pad_right, pad_bottom = 72, 18, 22, 24
        chart_w = width - pad_left - pad_right
        chart_h = height - pad_top - pad_bottom
        canvas.create_rectangle(pad_left, pad_top, width - pad_right, height - pad_bottom, outline=t["border"], width=1)

        values = relative_strength_index([c.close for c in candles], 14)
        def to_y(value: float) -> float:
            return pad_top + (100 - value) / 100 * chart_h

        for level in (70, 50, 30):
            y = to_y(level)
            color = t["yellow"] if level in (70, 30) else t["grid"]
            canvas.create_line(pad_left, y, width - pad_right, y, fill=color, dash=(3, 4))
            canvas.create_text(pad_left - 8, y, text=str(level), fill=t["muted"], anchor="e", font=("Consolas", 9))
        self._draw_line_series(canvas, values, to_y, pad_left, chart_w / max(len(candles), 1), t["purple"], width=2)
        last_rsi = next((v for v in reversed(values) if v is not None), None)
        label = f"RSI(14): {last_rsi:.2f}" if last_rsi is not None else "RSI(14): -"
        canvas.create_text(pad_left, 10, text=label, anchor="w", fill=t["white"], font=("Consolas", 10, "bold"))

    def _draw_macd_panel(self, candles) -> None:
        t = self.theme
        canvas = self.macd_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 700)
        height = max(canvas.winfo_height(), 150)
        canvas.create_rectangle(0, 0, width, height, fill=t["bg"], outline=t["bg"])
        pad_left, pad_top, pad_right, pad_bottom = 72, 18, 22, 24
        chart_w = width - pad_left - pad_right
        chart_h = height - pad_top - pad_bottom
        canvas.create_rectangle(pad_left, pad_top, width - pad_right, height - pad_bottom, outline=t["border"], width=1)

        closes = [c.close for c in candles]
        ema12 = exponential_moving_average(closes, 12)
        ema26 = exponential_moving_average(closes, 26)
        macd = [None if a is None or b is None else a - b for a, b in zip(ema12, ema26)]
        macd_valid = [v if v is not None else 0.0 for v in macd]
        signal = exponential_moving_average(macd_valid, 9)
        histogram = [None if m is None or s is None else m - s for m, s in zip(macd, signal)]
        valid_vals = [v for v in macd + signal + histogram if v is not None]
        min_v = min(valid_vals) if valid_vals else -1
        max_v = max(valid_vals) if valid_vals else 1
        if math.isclose(max_v, min_v):
            max_v += 1
            min_v -= 1
        span = max_v - min_v

        def to_y(value: float) -> float:
            return pad_top + (max_v - value) / span * chart_h

        zero_y = to_y(0.0)
        canvas.create_line(pad_left, zero_y, width - pad_right, zero_y, fill=t["grid"], dash=(2, 4))
        canvas.create_text(pad_left - 8, zero_y, text="0", fill=t["muted"], anchor="e", font=("Consolas", 9))
        gap = chart_w / max(len(candles), 1)
        for idx, value in enumerate(histogram):
            if value is None:
                continue
            x = pad_left + gap * idx + gap / 2
            y = to_y(value)
            color = t["green"] if value >= 0 else t["red"]
            canvas.create_line(x, zero_y, x, y, fill=color, width=max(1, int(gap * 0.55)))
        self._draw_line_series(canvas, macd, to_y, pad_left, gap, t["blue"], width=2)
        self._draw_line_series(canvas, signal, to_y, pad_left, gap, t["orange"], width=2)
        last_macd = next((v for v in reversed(macd) if v is not None), None)
        last_signal = next((v for v in reversed(signal) if v is not None), None)
        canvas.create_text(pad_left, 10, text=f"MACD: {last_macd:.4f}   Signal: {last_signal:.4f}" if last_macd is not None and last_signal is not None else "MACD: -", anchor="w", fill=t["white"], font=("Consolas", 10, "bold"))

    def _draw_line_series(self, canvas, values, to_y, pad_left: float, gap: float, color: str, width: int = 2) -> None:
        points = []
        for idx, value in enumerate(values):
            if value is None:
                if len(points) >= 4:
                    canvas.create_line(*points, fill=color, width=width, smooth=True)
                points = []
                continue
            x = pad_left + gap * idx + gap / 2
            points.extend([x, to_y(value)])
        if len(points) >= 4:
            canvas.create_line(*points, fill=color, width=width, smooth=True)

    def _on_chart_motion(self, event) -> None:
        if not self.last_candles or not self.chart_geometry or not self.show_crosshair_var.get():
            return
        g = self.chart_geometry
        x = min(max(event.x, g["pad_left"]), g["pad_left"] + g["chart_w"])
        idx = int((x - g["pad_left"]) / g["candle_gap"])
        idx = max(0, min(idx, len(self.last_candles) - 1))
        candle = self.last_candles[idx]
        true_x = g["pad_left"] + g["candle_gap"] * idx + g["candle_gap"] / 2
        self._clear_crosshair()
        for canvas in (self.price_canvas, self.rsi_canvas, self.macd_canvas):
            h = canvas.winfo_height()
            canvas.create_line(true_x, 0, true_x, h, fill=self.theme["muted"], dash=(3, 4), tags=CROSSHAIR_TAG)
        price_y = g["price_to_y"](candle.close)
        self.price_canvas.create_line(g["pad_left"], price_y, g["pad_left"] + g["chart_w"], price_y, fill=self.theme["muted"], dash=(3, 4), tags=CROSSHAIR_TAG)
        self.hover_info_var.set(f"{candle.timestamp.strftime('%Y-%m-%d %H:%M')} | O {candle.open:.2f} H {candle.high:.2f} L {candle.low:.2f} C {candle.close:.2f}")

    def _on_chart_leave(self, _event) -> None:
        self._clear_crosshair()
        self.hover_info_var.set("将鼠标移动到图表上查看详细价格")

    def _clear_crosshair(self) -> None:
        for canvas in (self.price_canvas, self.rsi_canvas, self.macd_canvas):
            canvas.delete(CROSSHAIR_TAG)

    def _map_signal(self, action: str, reason: str) -> str:
        action_map = {"buy": "买入", "sell": "卖出", "hold": "观望"}
        prefix = action_map.get(action, action)
        return f"{prefix} / {reason}" if reason else prefix

    def _map_position(self, state: str, qty: float) -> str:
        state_map = {"flat": "空仓", "long": "持多"}
        return f"{state_map.get(state, state)} ({qty:.6f})"

    def _map_recommendation(self, recommendation: str) -> str:
        mapping = {"enter_long": "建议开多", "exit_long": "建议平仓", "hold_long": "继续持有", "stand_aside": "继续观望"}
        return mapping.get(recommendation, recommendation)

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    try:
        SignalDesktopApp().run()
    except Exception as exc:
        messagebox.showerror("ETH 15分钟量化信号终端", str(exc))
        raise
