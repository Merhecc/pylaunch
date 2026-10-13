"""
pylaunch.py —— PyLaunch 主程序（现代图形界面 + 管理员模式）
依赖：pip install customtkinter psutil
打包：pyinstaller --onefile --noconsole --icon=tubiao.ico ^
       --add-data "tubiao.ico;." pylaunch.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from manager import (AppManager, BASE_DIR, CONFIG_FILE, DIAG_LOG,
                     IS_WINDOWS, is_admin)

# --------------------------------------------------------------------------- #
# 配色
# --------------------------------------------------------------------------- #
C_BG       = "#14161a"
C_PANEL    = "#1a1d23"
C_CARD     = "#212530"
C_CARD_HL  = "#2a3040"
C_CARD_SEL = "#2c3548"
C_TEXT     = "#e8eaed"
C_MUTED    = "#8b93a7"
C_ACCENT   = "#4f8cff"
C_GREEN    = "#2ecc71"
C_RED      = "#ff5b5b"
C_AMBER    = "#f5b544"
C_BORDER   = "#2a2f3a"

ctk.set_appearance_mode("dark")


# --------------------------------------------------------------------------- #
# 格式化
# --------------------------------------------------------------------------- #
def fmt_duration(sec: float) -> str:
    sec = int(sec)
    d, sec = divmod(sec, 86400)
    h, sec = divmod(sec, 3600)
    m, s = divmod(sec, 60)
    if d:
        return f"{d}天{h}小时"
    if h:
        return f"{h}小时{m}分"
    if m:
        return f"{m}分{s}秒"
    return f"{s}秒"


def fmt_mem(b: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f}{unit}" if unit in ("B", "KB") else f"{b:.1f}{unit}"
        b /= 1024
    return f"{b:.1f}TB"


def fmt_time(ts: float) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M:%S")
    except Exception:
        return "—"


def open_path(path):
    try:
        if IS_WINDOWS:
            os.startfile(str(path))          # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        messagebox.showerror("打开失败", str(e))


# --------------------------------------------------------------------------- #
# 侧栏卡片
# --------------------------------------------------------------------------- #
class AppCard(ctk.CTkFrame):
    def __init__(self, master, app: dict, selected: bool, on_click, on_toggle):
        super().__init__(
            master,
            corner_radius=10,
            fg_color=C_CARD_SEL if selected else C_CARD,
            border_width=1,
            border_color=C_ACCENT if selected else C_BORDER,
            height=64,
            cursor="hand2",
        )
        self.app_id = app["id"]
        self.on_click = on_click
        self.on_toggle = on_toggle

        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure((0, 1), weight=1)

        self.dot = ctk.CTkLabel(self, text="●", width=16,
                                text_color=C_MUTED, font=ctk.CTkFont(size=13))
        self.dot.grid(row=0, column=0, rowspan=2, padx=(12, 2))

        # 名称（管理员加前缀）
        prefix = "🛡 " if app.get("run_as_admin") else ""
        self.name_lbl = ctk.CTkLabel(
            self, text=prefix + app["name"], anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=C_TEXT)
        self.name_lbl.grid(row=0, column=1, sticky="sw", pady=(9, 0))

        self.sub_lbl = ctk.CTkLabel(
            self, text=Path(app["script"]).name, anchor="w",
            font=ctk.CTkFont(size=10), text_color=C_MUTED)
        self.sub_lbl.grid(row=1, column=1, sticky="nw", pady=(0, 9))

        self.toggle_btn = ctk.CTkButton(
            self, text="▶", width=30, height=28, corner_radius=7,
            font=ctk.CTkFont(size=12), fg_color="transparent",
            hover_color=C_CARD_HL, border_width=1, border_color=C_BORDER,
            text_color=C_GREEN, command=self._toggle)
        self.toggle_btn.grid(row=0, column=2, rowspan=2, padx=10)

        for w in (self, self.dot, self.name_lbl, self.sub_lbl):
            w.bind("<Button-1>", self._click)

    def _click(self, _e=None):
        self.on_click(self.app_id)

    def _toggle(self):
        self.on_toggle(self.app_id)

    def set_state(self, running: bool):
        if running:
            self.dot.configure(text_color=C_GREEN)
            self.toggle_btn.configure(text="■", text_color=C_RED)
        else:
            self.dot.configure(text_color=C_MUTED)
            self.toggle_btn.configure(text="▶", text_color=C_GREEN)


# --------------------------------------------------------------------------- #
# 添加 / 编辑 对话框
# --------------------------------------------------------------------------- #
class AppDialog(ctk.CTkToplevel):
    def __init__(self, master, manager: AppManager, app: dict | None = None,
                 on_saved=None):
        super().__init__(master)
        self.manager = manager
        self.app = app
        self.on_saved = on_saved

        self.title("编辑应用" if app else "添加应用")
        self.geometry("640x740")
        self.configure(fg_color=C_BG)
        self.resizable(False, False)
        self.transient(master)
        self.after(80, self.grab_set)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        body.grid_columnconfigure(0, weight=1)

        self._row = 0

        def label(text):
            ctk.CTkLabel(body, text=text, anchor="w",
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=C_TEXT).grid(
                row=self._row, column=0, sticky="ew", padx=6, pady=(14, 4))
            self._row += 1

        def entry_row(placeholder="", browse=None, initial=""):
            fr = ctk.CTkFrame(body, fg_color="transparent")
            fr.grid(row=self._row, column=0, sticky="ew", padx=6)
            self._row += 1
            fr.grid_columnconfigure(0, weight=1)
            e = ctk.CTkEntry(fr, placeholder_text=placeholder, height=36,
                             corner_radius=8, fg_color=C_CARD,
                             border_color=C_BORDER, border_width=1)
            e.grid(row=0, column=0, sticky="ew")
            if initial:
                e.insert(0, initial)
            if browse:
                ctk.CTkButton(fr, text="浏览", width=64, height=36,
                              corner_radius=8, fg_color=C_CARD_HL,
                              hover_color=C_CARD_SEL,
                              command=lambda: browse(e)).grid(
                    row=0, column=1, padx=(8, 0))
            return e

        label("应用名称")
        self.name_entry = entry_row("例如：数据同步服务",
                                    initial=(app or {}).get("name", ""))

        label("脚本路径  *.py / *.pyw")
        self.script_entry = entry_row(
            r"D:\projects\myapp\app.py",
            browse=lambda e: self._browse_file(e),
            initial=(app or {}).get("script", ""))

        label("启动参数（可选，空格分隔）")
        self.args_entry = entry_row("--port 8000 --debug",
                                    initial=(app or {}).get("args", ""))

        label("工作目录（可选，默认脚本所在目录）")
        self.cwd_entry = entry_row(
            r"D:\projects\myapp",
            browse=lambda e: self._browse_dir(e),
            initial=(app or {}).get("cwd", ""))

        label("解释器路径（留空 = 自动使用 pythonw.exe）")
        self.python_entry = entry_row(
            "自动（pythonw.exe）",
            browse=lambda e: self._browse_exe(e),
            initial=(app or {}).get("python", ""))

        label("环境变量（每行一个 KEY=VALUE，可选）")
        self.env_box = ctk.CTkTextbox(body, height=90, corner_radius=8,
                                      fg_color=C_CARD, border_width=1,
                                      border_color=C_BORDER,
                                      font=ctk.CTkFont(family="Consolas", size=12))
        self.env_box.grid(row=self._row, column=0, sticky="ew", padx=6)
        self._row += 1
        env = (app or {}).get("env") or {}
        if env:
            self.env_box.insert("1.0", "\n".join(f"{k}={v}" for k, v in env.items()))

        # 管理员开关
        sw = ctk.CTkFrame(body, fg_color="transparent")
        sw.grid(row=self._row, column=0, sticky="ew", padx=6, pady=(18, 6))
        self._row += 1

        self.admin_var = tk.BooleanVar(
            value=bool((app or {}).get("run_as_admin", False)))
        ctk.CTkSwitch(
            sw, text="以管理员身份运行（每次启动会弹 UAC）",
            variable=self.admin_var,
            progress_color=C_AMBER,
            font=ctk.CTkFont(size=12),
        ).pack(side="left")

        hint = ctk.CTkLabel(
            body,
            text=("提示：使用 pythonw.exe 时子进程没有标准输出，日志区只能看到"
                  "启动记录。以管理员身份运行时，PyLaunch 自身若不是管理员，"
                  "每次启动都会弹 UAC 确认框。"),
            text_color=C_MUTED, anchor="w", justify="left",
            wraplength=580, font=ctk.CTkFont(size=11))
        hint.grid(row=self._row, column=0, sticky="ew", padx=6, pady=(14, 4))
        self._row += 1

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        bottom.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(bottom, text="取消", height=40, corner_radius=9,
                      fg_color=C_CARD_HL, hover_color=C_CARD_SEL,
                      command=self.destroy).grid(row=0, column=0, sticky="ew",
                                                 padx=(0, 6))
        ctk.CTkButton(bottom, text="保存", height=40, corner_radius=9,
                      fg_color=C_ACCENT, hover_color="#3d7be6",
                      command=self._save).grid(row=0, column=1, sticky="ew",
                                               padx=(6, 0))

        self.bind("<Escape>", lambda _e: self.destroy())

    def _browse_file(self, e):
        p = filedialog.askopenfilename(
            title="选择 Python 脚本",
            filetypes=[("Python 脚本", "*.py *.pyw"), ("所有文件", "*.*")])
        if p:
            e.delete(0, "end")
            e.insert(0, p)
            if not self.name_entry.get().strip():
                self.name_entry.insert(0, Path(p).stem)

    def _browse_dir(self, e):
        p = filedialog.askdirectory(title="选择工作目录")
        if p:
            e.delete(0, "end")
            e.insert(0, p)

    def _browse_exe(self, e):
        p = filedialog.askopenfilename(
            title="选择 Python 解释器",
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")])
        if p:
            e.delete(0, "end")
            e.insert(0, p)

    def _save(self):
        script = self.script_entry.get().strip().strip('"')
        if not script:
            messagebox.showwarning("提示", "请填写脚本路径", parent=self)
            return
        if not Path(script).exists():
            if not messagebox.askyesno("路径不存在",
                                       f"文件不存在：\n{script}\n\n仍要保存吗？",
                                       parent=self):
                return

        name = self.name_entry.get().strip() or Path(script).stem

        env = {}
        raw = self.env_box.get("1.0", "end").strip()
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

        data = {
            "name": name,
            "script": str(Path(script).resolve()) if Path(script).exists() else script,
            "args": self.args_entry.get().strip(),
            "cwd": self.cwd_entry.get().strip(),
            "python": self.python_entry.get().strip(),
            "env": env,
            "run_as_admin": bool(self.admin_var.get()),
        }

        if self.app:
            self.manager.update(self.app["id"], data)
        else:
            self.manager.add(data)

        if not CONFIG_FILE.exists():
            messagebox.showerror(
                "保存失败",
                f"配置文件未能写入：\n{CONFIG_FILE}\n\n"
                f"请检查目录权限，或查看诊断日志：\n{DIAG_LOG}",
                parent=self)
            return

        if self.on_saved:
            self.on_saved()
        self.destroy()


# --------------------------------------------------------------------------- #
# 导入外部进程
# --------------------------------------------------------------------------- #
class ImportDialog(ctk.CTkToplevel):
    def __init__(self, master, items: list[dict], on_import):
        super().__init__(master)
        self.items = items
        self.on_import = on_import
        self.title("导入正在运行的 Python 进程")
        self.geometry("640x460")
        self.configure(fg_color=C_BG)
        self.transient(master)
        self.after(80, self.grab_set)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(self, text=f"发现 {len(items)} 个未托管的 Python 进程",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew",
                                      padx=18, pady=(16, 8))

        scroll = ctk.CTkScrollableFrame(self, fg_color=C_CARD, corner_radius=12)
        scroll.grid(row=1, column=0, sticky="nsew", padx=18)
        scroll.grid_columnconfigure(0, weight=1)

        self.vars = []
        for i, it in enumerate(items):
            v = tk.BooleanVar(value=True)
            self.vars.append(v)
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.grid(row=i, column=0, sticky="ew", pady=4)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkCheckBox(row, text="", variable=v, width=24,
                            checkbox_width=20, checkbox_height=20,
                            fg_color=C_ACCENT).grid(row=0, column=0, padx=(6, 4))
            ctk.CTkLabel(row, text=Path(it["path"]).name, anchor="w",
                         font=ctk.CTkFont(size=12, weight="bold")).grid(
                row=0, column=1, sticky="ew")
            ctk.CTkLabel(row, text=f"PID {it['pid']}   {it['path']}",
                         anchor="w", font=ctk.CTkFont(size=10),
                         text_color=C_MUTED).grid(row=1, column=1, sticky="ew")

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=18, pady=16)
        bottom.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(bottom, text="取消", height=38, corner_radius=9,
                      fg_color=C_CARD_HL, hover_color=C_CARD_SEL,
                      command=self.destroy).grid(row=0, column=0, sticky="ew",
                                                 padx=(0, 6))
        ctk.CTkButton(bottom, text="导入选中项", height=38, corner_radius=9,
                      fg_color=C_ACCENT, hover_color="#3d7be6",
                      command=self._do_import).grid(row=0, column=1,
                                                    sticky="ew", padx=(6, 0))

    def _do_import(self):
        chosen = [it for it, v in zip(self.items, self.vars) if v.get()]
        self.on_import(chosen)
        self.destroy()


# --------------------------------------------------------------------------- #
# 主窗口
# --------------------------------------------------------------------------- #
class ManagerApp(ctk.CTk):
    REFRESH_MS = 1500

    def __init__(self):
        super().__init__()
        self.manager = AppManager()
        self.selected_id: str | None = None
        self.cards: dict[str, AppCard] = {}
        self.log_pos = 0
        self._list_sig = None

        self._update_title()
        self.minsize(1040, 680)
        self.configure(fg_color=C_BG)

        w, h = 1240, 790
        x = max(0, (self.winfo_screenwidth() - w) // 2)
        y = max(0, (self.winfo_screenheight() - h) // 2 - 30)
        self.geometry(f"{w}x{h}+{x}+{y}")

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main()

        if self.manager.apps:
            self.selected_id = self.manager.apps[0]["id"]

        self._refresh_list(force=True)
        self._update_detail()
        self.after(500, self._tick)

    def _update_title(self):
        n = len(self.manager.apps)
        tag = " [管理员]" if is_admin() else ""
        self.title(f"PyLaunch{tag} · {n} 个应用 · 配置：{CONFIG_FILE}")

    # ---------------------------------------------------------------- 侧栏
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=300, corner_radius=0, fg_color=C_PANEL)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)
        sb.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(sb, text="  PyLaunch", anchor="w",
                     font=ctk.CTkFont(size=21, weight="bold"),
                     text_color=C_TEXT).grid(row=0, column=0, sticky="ew",
                                             padx=16, pady=(20, 0))
        subtitle = "  Python 后台应用管理器"
        if is_admin():
            subtitle += "（管理员）"
        ctk.CTkLabel(sb, text=subtitle, anchor="w",
                     font=ctk.CTkFont(size=11),
                     text_color=C_AMBER if is_admin() else C_MUTED).grid(
            row=1, column=0, sticky="ew", padx=16, pady=(0, 14))

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh_list(force=True))
        ctk.CTkEntry(sb, placeholder_text="🔍  搜索应用…", height=36,
                     corner_radius=9, fg_color=C_CARD, border_width=0,
                     textvariable=self.search_var).grid(
            row=2, column=0, sticky="ew", padx=14, pady=(0, 10))

        self.list_frame = ctk.CTkScrollableFrame(sb, fg_color="transparent")
        self.list_frame.grid(row=3, column=0, sticky="nsew", padx=6)
        self.list_frame.grid_columnconfigure(0, weight=1)

        bar = ctk.CTkFrame(sb, fg_color="transparent")
        bar.grid(row=4, column=0, sticky="ew", padx=14, pady=(14, 6))
        bar.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(bar, text="＋ 添加", height=36, corner_radius=9,
                      fg_color=C_ACCENT, hover_color="#3d7be6",
                      command=self._on_add).grid(row=0, column=0, sticky="ew",
                                                 padx=(0, 5))
        ctk.CTkButton(bar, text="⇩ 导入", height=36, corner_radius=9,
                      fg_color=C_CARD_HL, hover_color=C_CARD_SEL,
                      command=self._on_import).grid(row=0, column=1, sticky="ew",
                                                    padx=(5, 0))

        bar2 = ctk.CTkFrame(sb, fg_color="transparent")
        bar2.grid(row=5, column=0, sticky="ew", padx=14, pady=(0, 6))
        bar2.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(bar2, text="全部启动", height=32, corner_radius=9,
                      fg_color="transparent", border_width=1,
                      border_color=C_BORDER, hover_color=C_CARD_HL,
                      text_color=C_TEXT,
                      command=self._start_all).grid(row=0, column=0, sticky="ew",
                                                    padx=(0, 5))
        ctk.CTkButton(bar2, text="全部停止", height=32, corner_radius=9,
                      fg_color="transparent", border_width=1,
                      border_color=C_BORDER, hover_color=C_CARD_HL,
                      text_color=C_TEXT,
                      command=self._stop_all).grid(row=0, column=1, sticky="ew",
                                                   padx=(5, 0))

        bar3 = ctk.CTkFrame(sb, fg_color="transparent")
        bar3.grid(row=6, column=0, sticky="ew", padx=14, pady=(0, 6))
        bar3.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(bar3, text="📂 程序目录", height=30, corner_radius=9,
                      fg_color="transparent", border_width=1,
                      border_color=C_BORDER, hover_color=C_CARD_HL,
                      text_color=C_MUTED, font=ctk.CTkFont(size=11),
                      command=self._on_open_data_dir).grid(
            row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkButton(bar3, text="📝 诊断日志", height=30, corner_radius=9,
                      fg_color="transparent", border_width=1,
                      border_color=C_BORDER, hover_color=C_CARD_HL,
                      text_color=C_MUTED, font=ctk.CTkFont(size=11),
                      command=self._on_open_diag).grid(
            row=0, column=1, sticky="ew", padx=(5, 0))

        # 管理员重启按钮
        if IS_WINDOWS:
            self.admin_btn = ctk.CTkButton(
                sb, text=self._admin_btn_text(),
                height=34, corner_radius=9,
                fg_color=C_CARD_HL if not is_admin() else "transparent",
                hover_color=C_CARD_SEL,
                border_width=1 if is_admin() else 0,
                border_color=C_BORDER,
                text_color=C_AMBER if not is_admin() else C_MUTED,
                font=ctk.CTkFont(size=12, weight="bold" if not is_admin() else "normal"),
                command=self._on_restart_as_admin)
            self.admin_btn.grid(row=7, column=0, sticky="ew", padx=14, pady=(0, 16))

    def _admin_btn_text(self) -> str:
        if is_admin():
            return "✓ 已以管理员身份运行"
        return "🛡  以管理员身份重启"

    # ---------------------------------------------------------------- 主区
    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=(0, 16), pady=16)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        # --- 详情卡片 ---
        card = ctk.CTkFrame(main, fg_color=C_CARD, corner_radius=14,
                            border_width=1, border_color=C_BORDER)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        card.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 2))
        head.grid_columnconfigure(1, weight=1)

        self.name_label = ctk.CTkLabel(head, text="未选择应用", anchor="w",
                                       font=ctk.CTkFont(size=19, weight="bold"),
                                       text_color=C_TEXT)
        self.name_label.grid(row=0, column=0, sticky="w")

        self.status_badge = ctk.CTkLabel(head, text="", width=74, height=26,
                                         corner_radius=13,
                                         font=ctk.CTkFont(size=11, weight="bold"))
        self.status_badge.grid(row=0, column=1, sticky="w", padx=12)

        self.admin_badge = ctk.CTkLabel(head, text="", width=74, height=26,
                                        corner_radius=13,
                                        font=ctk.CTkFont(size=11, weight="bold"))
        self.admin_badge.grid(row=0, column=2, sticky="w", padx=(0, 12))

        self.path_label = ctk.CTkLabel(card, text="", anchor="w",
                                       font=ctk.CTkFont(size=11),
                                       text_color=C_MUTED)
        self.path_label.grid(row=1, column=0, sticky="ew", padx=20)

        metrics = ctk.CTkFrame(card, fg_color="transparent")
        metrics.grid(row=2, column=0, sticky="ew", padx=20, pady=(14, 2))
        self.metric_labels: dict[str, ctk.CTkLabel] = {}
        specs = [("pid", "PID"), ("uptime", "运行时长"), ("cpu", "CPU"),
                 ("mem", "内存"), ("ports", "监听端口")]
        for i, (key, title) in enumerate(specs):
            box = ctk.CTkFrame(metrics, fg_color=C_BG, corner_radius=10)
            box.grid(row=0, column=i, padx=(0, 10), sticky="w")
            ctk.CTkLabel(box, text=title, font=ctk.CTkFont(size=10),
                         text_color=C_MUTED).grid(row=0, column=0,
                                                  padx=14, pady=(7, 0),
                                                  sticky="w")
            lbl = ctk.CTkLabel(box, text="—",
                               font=ctk.CTkFont(size=13, weight="bold"),
                               text_color=C_TEXT)
            lbl.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="w")
            self.metric_labels[key] = lbl

        bar = ctk.CTkFrame(card, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="ew", padx=20, pady=(14, 16))

        self.btn_start = self._mkbtn(bar, "▶  启动", self._on_start, C_ACCENT)
        self.btn_stop = self._mkbtn(bar, "■  停止", self._on_stop, C_CARD_HL)

        ctk.CTkFrame(bar, fg_color="transparent", width=20).pack(side="left")

        self.btn_log = self._mkbtn(bar, "日志文件", self._on_open_log, C_CARD_HL)
        self.btn_dir = self._mkbtn(bar, "所在目录", self._on_open_folder, C_CARD_HL)
        self.btn_edit = self._mkbtn(bar, "编辑", self._on_edit, C_CARD_HL)
        self.btn_del = self._mkbtn(bar, "删除", self._on_delete, "#5a2a34")

        # --- 日志卡片 ---
        logcard = ctk.CTkFrame(main, fg_color=C_CARD, corner_radius=14,
                               border_width=1, border_color=C_BORDER)
        logcard.grid(row=1, column=0, sticky="nsew")
        logcard.grid_columnconfigure(0, weight=1)
        logcard.grid_rowconfigure(1, weight=1)

        lh = ctk.CTkFrame(logcard, fg_color="transparent")
        lh.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 8))
        ctk.CTkLabel(lh, text="运行日志", font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=C_TEXT).pack(side="left")
        ctk.CTkLabel(lh, text="（pythonw 无标准输出，仅记录启动信息）",
                     font=ctk.CTkFont(size=10),
                     text_color=C_MUTED).pack(side="left", padx=10)

        self.autoscroll_var = tk.BooleanVar(value=True)
        ctk.CTkSwitch(lh, text="自动滚动", variable=self.autoscroll_var,
                      progress_color=C_ACCENT,
                      font=ctk.CTkFont(size=11)).pack(side="right")
        ctk.CTkButton(lh, text="清空", width=58, height=28, corner_radius=8,
                      fg_color=C_CARD_HL, hover_color=C_CARD_SEL,
                      command=self._clear_log).pack(side="right", padx=(10, 12))
        ctk.CTkButton(lh, text="打开文件", width=78, height=28, corner_radius=8,
                      fg_color=C_CARD_HL, hover_color=C_CARD_SEL,
                      command=self._on_open_log).pack(side="right")

        self.log_box = ctk.CTkTextbox(
            logcard, fg_color="#0e1014", corner_radius=10,
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color="#c3cddf", wrap="none", border_width=0)
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 16))
        self.log_box.configure(state="disabled")

    def _mkbtn(self, parent, text, cmd, color) -> ctk.CTkButton:
        b = ctk.CTkButton(parent, text=text, command=cmd, height=34,
                          corner_radius=8, fg_color=color,
                          hover_color=C_CARD_SEL if color != C_ACCENT else "#3d7be6",
                          font=ctk.CTkFont(size=12), text_color=C_TEXT)
        b.pack(side="left", padx=(0, 8))
        return b

    # ---------------------------------------------------------------- 列表
    def _refresh_list(self, force=False):
        q = self.search_var.get().strip().lower()
        apps = self.manager.apps
        if q:
            apps = [a for a in apps
                    if q in a["name"].lower() or q in a["script"].lower()]

        sig = tuple((a["id"], a["name"], a["script"], a.get("run_as_admin"))
                    for a in apps) + (self.selected_id,)
        if not force and sig == self._list_sig:
            return
        self._list_sig = sig

        for w in self.list_frame.winfo_children():
            w.destroy()
        self.cards.clear()

        if not apps:
            ctk.CTkLabel(self.list_frame,
                         text="暂无应用\n点击下方「＋ 添加」创建",
                         text_color=C_MUTED, justify="center",
                         font=ctk.CTkFont(size=12)).grid(row=0, column=0,
                                                          pady=48)
            return

        for i, app in enumerate(apps):
            card = AppCard(
                self.list_frame, app,
                selected=(app["id"] == self.selected_id),
                on_click=self._select,
                on_toggle=self._quick_toggle)
            card.grid(row=i, column=0, sticky="ew", pady=3, padx=4)
            self.cards[app["id"]] = card

    def _update_cards(self):
        for app_id, card in self.cards.items():
            card.set_state(self.manager.status(app_id) == "running")

    # ---------------------------------------------------------------- 交互
    def _select(self, app_id: str):
        if self.selected_id == app_id:
            return
        self.selected_id = app_id
        self.log_pos = 0
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self._refresh_list(force=True)
        self._update_detail()
        self._update_log()

    def _quick_toggle(self, app_id: str):
        if self.manager.status(app_id) == "running":
            ok, msg = self.manager.stop(app_id)
            if not ok and msg:
                messagebox.showwarning("停止失败", msg, parent=self)
        else:
            ok, msg = self.manager.start(app_id)
            if not ok and msg:
                messagebox.showwarning("启动失败", msg, parent=self)
        self._update_detail()

    def _on_start(self):
        if not self.selected_id:
            return
        ok, msg = self.manager.start(self.selected_id)
        if not ok and msg:
            messagebox.showwarning("启动失败", msg, parent=self)

    def _on_stop(self):
        if not self.selected_id:
            return
        ok, msg = self.manager.stop(self.selected_id)
        if not ok and msg and msg != "应用未在运行":
            messagebox.showwarning("停止失败", msg, parent=self)

    def _on_add(self):
        AppDialog(self, self.manager, None, on_saved=self._on_data_changed)

    def _on_edit(self):
        if not self.selected_id:
            return
        app = self.manager.get(self.selected_id)
        if app:
            AppDialog(self, self.manager, app, on_saved=self._on_data_changed)

    def _on_data_changed(self):
        self._refresh_list(force=True)
        self._update_title()

    def _on_delete(self):
        if not self.selected_id:
            return
        app = self.manager.get(self.selected_id)
        if not app:
            return
        if not messagebox.askyesno(
                "确认删除",
                f"确定删除「{app['name']}」吗？\n（若正在运行会先停止它）",
                parent=self):
            return
        self.manager.remove(self.selected_id)
        self.selected_id = self.manager.apps[0]["id"] if self.manager.apps else None
        self.log_pos = 0
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self._on_data_changed()
        self._update_detail()

    def _on_import(self):
        items = self.manager.scan_external()
        if not items:
            messagebox.showinfo("导入",
                                "没有发现未托管的 Python 进程。",
                                parent=self)
            return

        def do_import(chosen):
            for it in chosen:
                self.manager.add({
                    "name": Path(it["path"]).stem,
                    "script": it["path"],
                    "args": it["args"],
                    "cwd": str(Path(it["path"]).parent),
                    "python": "",
                    "env": {},
                    "run_as_admin": False,
                })
            self._on_data_changed()

        ImportDialog(self, items, do_import)

    def _start_all(self):
        started, failed = self.manager.start_all()
        if started == 0:
            messagebox.showinfo("全部启动",
                                f"没有可启动的应用。\n失败 {failed} 个。",
                                parent=self)

    def _stop_all(self):
        n = self.manager.stop_all()
        if n == 0:
            messagebox.showinfo("全部停止", "没有正在运行的应用。", parent=self)

    def _on_open_log(self):
        if not self.selected_id:
            return
        p = self.manager.log_path(self.selected_id)
        p.touch(exist_ok=True)
        open_path(p)

    def _on_open_folder(self):
        app = self.manager.get(self.selected_id) if self.selected_id else None
        if not app:
            return
        folder = app.get("cwd") or str(Path(app["script"]).parent)
        if Path(folder).exists():
            open_path(folder)

    def _on_open_data_dir(self):
        open_path(BASE_DIR)

    def _on_open_diag(self):
        DIAG_LOG.touch(exist_ok=True)
        open_path(DIAG_LOG)

    def _clear_log(self):
        if not self.selected_id:
            return
        try:
            self.manager.log_path(self.selected_id).write_text("", encoding="utf-8")
        except OSError:
            pass
        self.log_pos = 0
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    # ---------------------------------------------------------------- 管理员重启
    def _on_restart_as_admin(self):
        if not IS_WINDOWS:
            return
        if is_admin():
            messagebox.showinfo("提示",
                                "PyLaunch 已经在以管理员身份运行。",
                                parent=self)
            return
        if not messagebox.askyesno(
                "以管理员身份重启",
                "将关闭当前 PyLaunch，并以管理员身份重新打开。\n"
                "已经启动的应用不受影响。\n\n继续吗？",
                parent=self):
            return

        import ctypes

        if getattr(sys, "frozen", False):
            exe = sys.executable
            params = ""
            workdir = str(BASE_DIR)
        else:
            exe = sys.executable
            params = " ".join(f'"{a}"' for a in sys.argv)
            workdir = str(BASE_DIR)

        try:
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe, params, workdir, 1
            )
        except Exception as e:
            messagebox.showerror("失败", f"无法以管理员身份重启：{e}",
                                 parent=self)
            return

        if ret <= 32:
            msgs = {
                0: "内存不足",
                2: "文件未找到",
                3: "路径未找到",
                5: "你取消了 UAC 授权",
                31: "无法读取",
                32: "无法加载",
            }
            messagebox.showerror(
                "失败",
                f"无法以管理员身份重启：\n{msgs.get(ret, f'错误码 {ret}')}",
                parent=self)
            return

        # 关闭当前实例
        self.destroy()

    # ---------------------------------------------------------------- 刷新
    def _tick(self):
        try:
            self.manager.invalidate()
            self._update_cards()
            self._update_detail()
            self._update_log()
        except Exception as e:
            print("[PyLaunch] 刷新异常:", e)
        self.after(self.REFRESH_MS, self._tick)

    def _update_detail(self):
        app = self.manager.get(self.selected_id) if self.selected_id else None

        if not app:
            self.name_label.configure(text="未选择应用")
            self.path_label.configure(
                text="从左侧列表选择一个应用，或点击「＋ 添加」创建新的托管项")
            for v in self.metric_labels.values():
                v.configure(text="—")
            self._set_badge("")
            self._set_admin_badge(False)
            for b in (self.btn_start, self.btn_stop, self.btn_log,
                      self.btn_dir, self.btn_edit, self.btn_del):
                b.configure(state="disabled")
            return

        for b in (self.btn_start, self.btn_stop, self.btn_log,
                  self.btn_dir, self.btn_edit, self.btn_del):
            b.configure(state="normal")

        running = self.manager.status(app["id"]) == "running"
        self.name_label.configure(text=app["name"])

        path_txt = app["script"]
        if app.get("args"):
            path_txt += f"   {app['args']}"
        self.path_label.configure(text=path_txt)

        if running:
            self._set_badge("运行中", C_GREEN)
        else:
            self._set_badge("已停止", "#4a5162")

        self._set_admin_badge(bool(app.get("run_as_admin", False)))

        st = self.manager.stats(app["id"]) if running else {}
        if st:
            self.metric_labels["pid"].configure(text=str(st.get("pid", "—")))
            self.metric_labels["uptime"].configure(
                text=fmt_duration(st.get("uptime", 0)))
            self.metric_labels["cpu"].configure(
                text=f"{st.get('cpu', 0):.1f}%")
            self.metric_labels["mem"].configure(
                text=fmt_mem(st.get("mem", 0)))
            ports = st.get("ports") or []
            self.metric_labels["ports"].configure(
                text=", ".join(str(p) for p in ports[:3]) if ports else "—")
        else:
            for k in ("pid", "uptime", "cpu", "mem", "ports"):
                self.metric_labels[k].configure(text="—")
            if app.get("last_started"):
                self.metric_labels["uptime"].configure(
                    text=f"上次 {fmt_time(app['last_started'])}")

        self.btn_start.configure(state="disabled" if running else "normal")
        self.btn_stop.configure(state="normal" if running else "disabled")

    def _set_badge(self, text: str, color: str = C_MUTED):
        if not text:
            self.status_badge.configure(text="", fg_color="transparent")
            return
        self.status_badge.configure(text=text, fg_color=color,
                                    text_color="#ffffff")

    def _set_admin_badge(self, is_admin_app: bool):
        if not is_admin_app:
            self.admin_badge.configure(text="", fg_color="transparent")
            return
        self.admin_badge.configure(text="管理员", fg_color=C_AMBER,
                                   text_color="#1a1d23")

    def _update_log(self):
        if not self.selected_id:
            return
        path = self.manager.log_path(self.selected_id)
        if not path.exists():
            return
        try:
            size = path.stat().st_size
        except OSError:
            return

        if size < self.log_pos:
            self.log_pos = 0
            self.log_box.configure(state="normal")
            self.log_box.delete("1.0", "end")
            self.log_box.configure(state="disabled")

        if size == self.log_pos:
            return

        try:
            with open(path, "rb") as f:
                f.seek(self.log_pos)
                chunk = f.read(256 * 1024)
                self.log_pos = f.tell()
        except OSError:
            return

        if not chunk:
            return

        text = chunk.decode("utf-8", errors="replace")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text)

        lines = int(self.log_box.index("end-1c").split(".")[0])
        if lines > 4000:
            self.log_box.delete("1.0", f"{lines - 3000}.0")

        self.log_box.configure(state="disabled")
        if self.autoscroll_var.get():
            self.log_box.see("end")

    # ---------------------------------------------------------------- 关闭
    def _on_close(self):
        self.destroy()


# --------------------------------------------------------------------------- #
def main():
    try:
        app = ManagerApp()
    except Exception as e:
        try:
            import tkinter.messagebox as mb
            mb.showerror("PyLaunch 启动失败", str(e))
        except Exception:
            print("PyLaunch 启动失败:", e)
        return
    app.mainloop()


if __name__ == "__main__":
    main()