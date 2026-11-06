"""AirPlay 課堂投影控制面板。

啟動：  py app\\main.py   或雙擊 run_panel.bat（打包後直接執行 exe）
"""
from __future__ import annotations

import os
import queue
import random
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import uxplay_ctl as ux  # noqa: E402

APP_TITLE = "AirPlay 課堂投影控制面板"
POLL_SEC = 2.0
FONT = "Microsoft JhengHei UI"
RESOLUTIONS = [("1920x1080（高畫質）", "1920x1080"), ("1280x720（較順、延遲較低）", "1280x720"),
               ("2560x1440", "2560x1440")]
FPS_CHOICES = [("60（流暢）", "60"), ("30（省頻寬）", "30")]
PRESETS = {"high": ("1920x1080", "60"), "stable": ("1280x720", "30")}


class Panel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(600, 700)
        self.cfg = config.load()
        self.exe: Path | None = ux.find_exe(config.ROOT, self.cfg.get("uxplay_exe"))
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self._running = False
        self._last_clients: list[str] | None = None
        self._since: float | None = None
        self._applied_pin = ""

        self._build_ui()
        self._load_settings()
        self._log(f"uxplay-windows 位置：{self.exe or '（找不到，請按「變更…」指定）'}")
        if ux.ARGS_PROGRAMDATA.is_file():
            self._log(f"⚠ 偵測到 {ux.ARGS_PROGRAMDATA}，它會蓋過面板的設定；請刪除該檔。")

        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.after(200, self._drain_events)
        if self.cfg.get("autostart_uxplay") and self.exe:
            self.after(500, lambda: self._start_with_settings(restart=False))

    # ================================================================ 介面
    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.configure("Big.TLabel", font=(FONT, 22, "bold"))
        style.configure("Pin.TLabel", font=(FONT, 28, "bold"), foreground="#c62828")
        style.configure("TLabel", font=(FONT, 11))
        style.configure("TCheckbutton", font=(FONT, 11))
        style.configure("TButton", font=(FONT, 11), padding=6)
        style.configure("TLabelframe.Label", font=(FONT, 11, "bold"))
        pad = {"padx": 10, "pady": 5}

        # ---- 狀態
        st = ttk.LabelFrame(self, text="狀態")
        st.pack(fill="x", **pad)
        self.dot = tk.Canvas(st, width=26, height=26, highlightthickness=0)
        self.dot.grid(row=0, column=0, rowspan=2, padx=(10, 6), pady=8, sticky="n")
        self.dot_item = self.dot.create_oval(3, 3, 23, 23, fill="#999", outline="")
        self.lbl_state = ttk.Label(st, text="檢查中…", style="Big.TLabel")
        self.lbl_state.grid(row=0, column=1, sticky="w")
        self.lbl_detail = ttk.Label(st, text="", justify="left")
        self.lbl_detail.grid(row=1, column=1, sticky="w", pady=(0, 8))
        self.lbl_pin = ttk.Label(st, text="", style="Pin.TLabel")
        self.lbl_pin.grid(row=0, column=2, rowspan=2, padx=12, sticky="e")
        st.columnconfigure(1, weight=1)

        # ---- 控制
        ctl = ttk.Frame(self)
        ctl.pack(fill="x", **pad)
        self.btn_start = ttk.Button(ctl, text="▶ 啟動投影服務",
                                    command=lambda: self._start_with_settings(restart=False))
        self.btn_stop = ttk.Button(ctl, text="■ 停止", command=lambda: self._do(self._act_stop))
        self.btn_restart = ttk.Button(ctl, text="⟳ 套用設定並重新啟動",
                                      command=lambda: self._start_with_settings(restart=True))
        for i, b in enumerate((self.btn_start, self.btn_stop, self.btn_restart)):
            b.grid(row=0, column=i, sticky="ew", padx=4)
            ctl.columnconfigure(i, weight=1)
        ttk.Label(self, text="※ 下方設定變更後，需按「套用設定並重新啟動」才生效（iPad 會斷線，需重新點選）",
                  foreground="#666").pack(anchor="w", padx=14)

        # ---- 基本設定
        fm = ttk.LabelFrame(self, text="投影設定")
        fm.pack(fill="x", **pad)
        r = 0
        ttk.Label(fm, text="iPad 上顯示的名稱").grid(row=r, column=0, sticky="w", padx=8, pady=3)
        self.var_name = tk.StringVar()
        ttk.Entry(fm, textvariable=self.var_name, font=(FONT, 11)).grid(row=r, column=1, columnspan=2,
                                                                        sticky="ew", padx=8, pady=3)
        r += 1
        self.var_nh = tk.BooleanVar(value=True)
        ttk.Checkbutton(fm, text="名稱後不加「@電腦名稱」", variable=self.var_nh) \
            .grid(row=r, column=1, columnspan=2, sticky="w", padx=8)

        r += 1
        ttk.Label(fm, text="畫質預設").grid(row=r, column=0, sticky="w", padx=8, pady=3)
        pf = ttk.Frame(fm)
        pf.grid(row=r, column=1, columnspan=2, sticky="ew", padx=8, pady=3)
        ttk.Button(pf, text="高畫質（1080p／60）", command=lambda: self._apply_preset("high")) \
            .pack(side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(pf, text="穩定（720p／30）", command=lambda: self._apply_preset("stable")) \
            .pack(side="left", expand=True, fill="x", padx=(4, 0))
        r += 1
        ttk.Label(fm, text="解析度").grid(row=r, column=0, sticky="w", padx=8, pady=3)
        self.cmb_res = ttk.Combobox(fm, state="readonly", values=[x[0] for x in RESOLUTIONS])
        self.cmb_res.grid(row=r, column=1, columnspan=2, sticky="ew", padx=8, pady=3)
        r += 1
        ttk.Label(fm, text="最高影格率").grid(row=r, column=0, sticky="w", padx=8, pady=3)
        self.cmb_fps = ttk.Combobox(fm, state="readonly", values=[x[0] for x in FPS_CHOICES])
        self.cmb_fps.grid(row=r, column=1, columnspan=2, sticky="ew", padx=8, pady=3)
        fm.columnconfigure(1, weight=1)

        # ---- 課堂功能
        cl = ttk.LabelFrame(self, text="課堂功能")
        cl.pack(fill="x", **pad)
        self.var_fs = tk.BooleanVar()
        ttk.Checkbutton(cl, text="全螢幕顯示投影畫面", variable=self.var_fs) \
            .grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=2)
        self.var_nohold = tk.BooleanVar()
        ttk.Checkbutton(cl, text="有新裝置連線時，直接切換到新裝置（否則需等目前裝置中斷）",
                        variable=self.var_nohold).grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=2)

        self.var_use_pin = tk.BooleanVar()
        ttk.Checkbutton(cl, text="需要 PIN 碼才能連線", variable=self.var_use_pin,
                        command=self._sync_pin_state).grid(row=2, column=0, sticky="w", padx=8, pady=2)
        self.var_pin = tk.StringVar()
        self.ent_pin = ttk.Entry(cl, textvariable=self.var_pin, width=8, font=(FONT, 12))
        self.ent_pin.grid(row=2, column=1, sticky="w", padx=4)
        self.btn_pin = ttk.Button(cl, text="隨機產生", command=self._random_pin)
        self.btn_pin.grid(row=2, column=2, sticky="w", padx=4)

        self.var_rec = tk.BooleanVar()
        ttk.Checkbutton(cl, text="錄下投影畫面（只有影像、無聲音）", variable=self.var_rec) \
            .grid(row=3, column=0, columnspan=3, sticky="w", padx=8, pady=2)
        rf = ttk.Frame(cl)
        rf.grid(row=4, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 6))
        self.lbl_recdir = ttk.Label(rf, text="", foreground="#555")
        self.lbl_recdir.pack(side="left", fill="x", expand=True)
        ttk.Button(rf, text="開啟資料夾", command=self._open_recdir).pack(side="right", padx=2)
        ttk.Button(rf, text="變更…", command=self._pick_recdir).pack(side="right", padx=2)
        cl.columnconfigure(2, weight=1)

        # ---- 其他
        ot = ttk.LabelFrame(self, text="進階")
        ot.pack(fill="x", **pad)
        ttk.Label(ot, text="其他 UxPlay 參數").grid(row=0, column=0, sticky="w", padx=8, pady=3)
        self.var_extra = tk.StringVar()
        ttk.Entry(ot, textvariable=self.var_extra).grid(row=0, column=1, columnspan=2, sticky="ew", padx=8)
        ttk.Label(ot, text="uxplay-windows 位置").grid(row=1, column=0, sticky="w", padx=8, pady=3)
        self.lbl_exe = ttk.Label(ot, text=str(self.exe or "（未找到）"), wraplength=360, foreground="#555")
        self.lbl_exe.grid(row=1, column=1, sticky="w", padx=8)
        ttk.Button(ot, text="變更…", command=self._on_pick_exe).grid(row=1, column=2, sticky="e", padx=8)
        self.var_auto = tk.BooleanVar(value=bool(self.cfg.get("autostart_uxplay")))
        ttk.Checkbutton(ot, text="開啟面板時自動啟動投影服務", variable=self.var_auto,
                        command=self._on_toggle_auto).grid(row=2, column=0, columnspan=3, sticky="w", padx=8)
        ot.columnconfigure(1, weight=1)

        # ---- 紀錄
        lg = ttk.LabelFrame(self, text="紀錄")
        lg.pack(fill="both", expand=True, **pad)
        self.txt = tk.Text(lg, height=6, state="disabled", font=("Consolas", 10), wrap="word")
        self.txt.pack(fill="both", expand=True, padx=6, pady=6)

    def _log(self, msg: str) -> None:
        self.txt.configure(state="normal")
        self.txt.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    # ================================================================ 設定 ⇄ 表單
    def _rec_dir(self) -> Path:
        return Path(self.cfg.get("record_dir") or (Path.home() / "Videos" / "AirPlayRecordings"))

    def _load_settings(self) -> None:
        a = ux.read_args()
        self.var_name.set(a.name)
        self.var_nh.set(a.no_hostname)
        self._select(self.cmb_res, RESOLUTIONS, a.resolution or PRESETS["high"][0])
        self._select(self.cmb_fps, FPS_CHOICES, a.fps or PRESETS["high"][1])
        self.var_fs.set(a.fullscreen)
        self.var_nohold.set(a.nohold)
        self.var_use_pin.set(bool(a.pin) or bool(self.cfg.get("use_pin")))
        self.var_pin.set(a.pin or self.cfg.get("pin", ""))
        self.var_rec.set(bool(self.cfg.get("record")))
        self.var_extra.set(" ".join(a.extra))
        self.lbl_recdir.configure(text=f"存放位置：{self._rec_dir()}")
        self._sync_pin_state()
        self._log(f"目前參數（{ux.active_args_file()}）：{a.to_text()}")

    @staticmethod
    def _select(cmb: ttk.Combobox, choices, value: str) -> None:
        for i, (_, v) in enumerate(choices):
            if v == value:
                cmb.current(i)
                return
        choices.append((value, value))
        cmb.configure(values=[c[0] for c in choices])
        cmb.current(len(choices) - 1)

    def _apply_preset(self, key: str) -> None:
        res, fps = PRESETS[key]
        self._select(self.cmb_res, RESOLUTIONS, res)
        self._select(self.cmb_fps, FPS_CHOICES, fps)
        self._log(f"已選擇預設：{res}／{fps} 格（按「套用設定並重新啟動」生效）")

    def _sync_pin_state(self) -> None:
        on = self.var_use_pin.get()
        self.ent_pin.state(["!disabled"] if on else ["disabled"])
        self.btn_pin.state(["!disabled"] if on else ["disabled"])
        if on and not self.var_pin.get():
            self._random_pin()

    def _random_pin(self) -> None:
        self.var_pin.set(f"{random.randint(0, 9999):04d}")

    def _collect(self) -> ux.UxArgs | None:
        """把表單轉成參數；有錯誤就跳出提示並回傳 None。"""
        name = self.var_name.get().strip()
        pin = self.var_pin.get().strip() if self.var_use_pin.get() else ""
        rec_dir = self._rec_dir()
        errors = [e for e in (ux.validate_name(name), ux.validate_pin(pin)) if e]
        if self.var_rec.get():
            e = ux.validate_path_token(str(rec_dir))
            if e:
                errors.append(e + "（請把錄影資料夾換到沒有空白的路徑）")
        if errors:
            messagebox.showerror("設定有誤", "\n".join(errors), parent=self)
            return None

        record_to = ""
        if self.var_rec.get():
            rec_dir.mkdir(parents=True, exist_ok=True)
            record_to = str(rec_dir / time.strftime("airplay_%Y%m%d_%H%M%S"))

        # 存面板自己的設定
        self.cfg.update(use_pin=self.var_use_pin.get(), pin=self.var_pin.get().strip(),
                        record=self.var_rec.get())
        config.save(self.cfg)
        return ux.UxArgs(
            name=name, no_hostname=self.var_nh.get(),
            resolution=RESOLUTIONS[self.cmb_res.current()][1],
            fps=FPS_CHOICES[self.cmb_fps.current()][1],
            fullscreen=self.var_fs.get(), pin=pin, nohold=self.var_nohold.get(),
            record_to=record_to, extra=self.var_extra.get().split(),
        )

    # ================================================================ 事件
    def _start_with_settings(self, restart: bool) -> None:
        if self.busy:
            return
        args = self._collect()
        if args is None:
            return
        path = ux.write_args(args)
        self._log(f"已寫入 {path.name}：{args.to_text()}")
        if ux.ARGS_PROGRAMDATA.is_file():
            messagebox.showwarning("設定可能無效",
                                   f"{ux.ARGS_PROGRAMDATA} 存在且優先，面板的設定不會生效。", parent=self)
        self._applied_pin = args.pin
        if args.record_to:
            self._log(f"錄影將存為：{args.record_to}.h264")
            if not args.record_to.isascii():
                self._log("⚠ 錄影路徑含中文等非英文字元，UxPlay 可能無法寫入；若錄不到檔案請改用英文路徑")
        self._do(self._act_restart if restart else self._act_start)

    def _on_pick_exe(self) -> None:
        f = filedialog.askopenfilename(title="選擇 uxplay-windows.exe",
                                       filetypes=[("uxplay-windows", "uxplay-windows.exe")], parent=self)
        if f:
            self.exe = Path(f)
            self.cfg["uxplay_exe"] = f
            config.save(self.cfg)
            self.lbl_exe.configure(text=f)
            self._log(f"已設定程式位置：{f}")

    def _pick_recdir(self) -> None:
        d = filedialog.askdirectory(title="選擇錄影存放資料夾", parent=self)
        if d:
            e = ux.validate_path_token(d)
            if e:
                messagebox.showerror("路徑不適用", e, parent=self)
                return
            self.cfg["record_dir"] = d
            config.save(self.cfg)
            self.lbl_recdir.configure(text=f"存放位置：{d}")

    def _open_recdir(self) -> None:
        d = self._rec_dir()
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(d)  # noqa: S606

    def _on_toggle_auto(self) -> None:
        self.cfg["autostart_uxplay"] = self.var_auto.get()
        config.save(self.cfg)

    # ================================================================ 背景動作
    def _do(self, fn) -> None:
        if self.busy:
            return
        self.busy = True
        self._set_buttons()

        def worker():
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                self.events.put(("log", f"錯誤：{e}"))
            finally:
                self.events.put(("done", None))
        threading.Thread(target=worker, daemon=True).start()

    def _need_exe(self) -> bool:
        if self.exe and self.exe.is_file():
            return True
        self.events.put(("log", "找不到 uxplay-windows.exe，請先在「進階」指定位置"))
        return False

    def _act_start(self) -> None:
        if self._need_exe():
            self.events.put(("log", "啟動投影服務…"))
            ux.start(self.exe)

    def _act_stop(self) -> None:
        self.events.put(("log", "停止投影服務…"))
        ux.stop()
        self.events.put(("log", "已停止"))

    def _act_restart(self) -> None:
        if self._need_exe():
            self.events.put(("log", "重新啟動投影服務…"))
            ux.restart(self.exe)

    def _poll_loop(self) -> None:
        while True:
            try:
                self.events.put(("status", ux.get_status()))
            except Exception as e:  # noqa: BLE001
                self.events.put(("log", f"狀態查詢失敗：{e}"))
            time.sleep(POLL_SEC)

    def _drain_events(self) -> None:
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "log":
                    self._log(data)
                elif kind == "done":
                    self.busy = False
                elif kind == "status":
                    self._show_status(data)
        except queue.Empty:
            pass
        self._set_buttons()
        self.after(200, self._drain_events)

    # ================================================================ 狀態顯示
    def _show_status(self, s: ux.Status) -> None:
        self._running = s.running
        name = self.var_name.get().strip() or "?"
        ips = "、".join(ux.local_ipv4()) or "未知"
        if s.clients and self._since is None:
            self._since = time.time()
        elif not s.clients:
            self._since = None

        if not s.running:
            color, text = "#9e9e9e", "已停止"
            detail = "按「啟動投影服務」後，iPad 才找得到這台電腦"
        elif s.clients:
            mins, secs = divmod(int(time.time() - self._since), 60)
            color, text = "#1e88e5", f"投影中（{len(s.clients)} 台）　{mins:02d}:{secs:02d}"
            detail = f"連線裝置：{'、'.join(s.clients)}\n名稱：{name}　本機 IP：{ips}"
        else:
            color, text = "#43a047", "等待連線"
            detail = (f"iPad：控制中心 →「螢幕鏡像輸出」→ 選「{name}」\n"
                      f"本機 IP：{ips}　監聽埠：{', '.join(map(str, s.listen_ports)) or '準備中'}")
        self.dot.itemconfigure(self.dot_item, fill=color)
        self.lbl_state.configure(text=text)
        self.lbl_detail.configure(text=detail)
        self.lbl_pin.configure(text=f"PIN {self._applied_pin}" if s.running and self._applied_pin else "")

        if self._last_clients is not None and s.clients != self._last_clients:
            for c in set(s.clients) - set(self._last_clients):
                self._log(f"裝置已連線：{c}")
            for c in set(self._last_clients) - set(s.clients):
                self._log(f"裝置已離線：{c}")
        self._last_clients = s.clients

    def _set_buttons(self) -> None:
        dis = ["disabled"]
        self.btn_start.state(dis if self.busy or self._running else ["!disabled"])
        self.btn_stop.state(dis if self.busy or not self._running else ["!disabled"])
        self.btn_restart.state(dis if self.busy or not self._running else ["!disabled"])


def main() -> None:
    try:  # 高 DPI 螢幕字不模糊
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    Panel().mainloop()


if __name__ == "__main__":
    main()
