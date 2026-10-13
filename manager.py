"""
manager.py —— PyLaunch 进程管理模块（支持管理员权限启动 + PyInstaller 打包）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import psutil

IS_WINDOWS = os.name == "nt"

# --------------------------------------------------------------------------- #
# 路径解析（兼容 PyInstaller）
# --------------------------------------------------------------------------- #
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

CONFIG_FILE = BASE_DIR / "apps.json"
LOG_DIR = BASE_DIR / "logs"
DIAG_LOG = BASE_DIR / "pylaunch.log"


def _check_writable():
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        probe = BASE_DIR / ".pylaunch_probe"
        probe.write_text("1", encoding="utf-8")
        probe.unlink()
    except Exception as e:
        raise RuntimeError(
            f"程序所在目录不可写：\n{BASE_DIR}\n\n"
            f"请把 exe（或 pylaunch.py）移动到一个有写入权限的目录"
            f"（例如 D:\\tools\\），再运行。\n\n"
            f"详细错误：{e}"
        )


_check_writable()


def _diag(msg: str):
    try:
        with open(DIAG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def is_admin() -> bool:
    """当前进程是否以管理员权限运行"""
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def detect_pythonw() -> str:
    if not getattr(sys, "frozen", False):
        exe = sys.executable or ""
        low = exe.lower()
        if low.endswith("pythonw.exe"):
            return exe
        if low.endswith("python.exe"):
            cand = exe[: -len("python.exe")] + "pythonw.exe"
            if os.path.exists(cand):
                return cand
    import shutil
    pw = shutil.which("pythonw") or shutil.which("pythonw.exe")
    if pw:
        return pw
    py = shutil.which("python") or shutil.which("python.exe")
    if py:
        cand = py[: -len("python.exe")] + "pythonw.exe"
        if os.path.exists(cand):
            return cand
        return py
    return "pythonw"


def detect_python() -> str:
    if not getattr(sys, "frozen", False):
        exe = sys.executable or "python"
        low = exe.lower()
        if low.endswith("pythonw.exe"):
            cand = exe[: -len("pythonw.exe")] + "python.exe"
            if os.path.exists(cand):
                return cand
        return exe
    import shutil
    return (shutil.which("python") or shutil.which("python.exe")
            or "python")


def split_args(s: str) -> list[str]:
    out, cur, quote = [], [], None
    for ch in s:
        if quote:
            if ch == quote:
                quote = None
            else:
                cur.append(ch)
        elif ch in ('"', "'"):
            quote = ch
        elif ch.isspace():
            if cur:
                out.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def _norm(p: str) -> str:
    try:
        return os.path.normcase(os.path.realpath(p))
    except Exception:
        return os.path.normcase(p or "")


# --------------------------------------------------------------------------- #
# 管理器
# --------------------------------------------------------------------------- #
class AppManager:
    def __init__(self):
        self.apps: list[dict] = []
        self._scan_cache: dict[str, tuple[int, float]] = {}
        self._scan_time: float = 0.0

        _diag("=" * 60)
        _diag("AppManager 初始化")
        _diag(f"  frozen      = {getattr(sys, 'frozen', False)}")
        _diag(f"  is_admin    = {is_admin()}")
        _diag(f"  BASE_DIR    = {BASE_DIR}")
        _diag(f"  CONFIG_FILE = {CONFIG_FILE}")
        _diag(f"  配置存在    = {CONFIG_FILE.exists()}")
        self.load()
        _diag(f"  加载应用数  = {len(self.apps)}")
        for a in self.apps:
            _diag(f"    · {a.get('name')}  →  {a.get('script')}  "
                  f"管理员={a.get('run_as_admin', False)}")

    def load(self):
        if not CONFIG_FILE.exists():
            _diag("load: 配置文件不存在")
            self.apps = []
            return
        try:
            raw = CONFIG_FILE.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                _diag("load: 不是数组，丢弃")
                self.apps = []
            else:
                self.apps = parsed
                _diag(f"load: 读到 {len(raw)} 字节 / {len(self.apps)} 条")
        except Exception as e:
            _diag(f"load: 解析失败 {e!r}")
            self.apps = []

        for a in self.apps:
            a.setdefault("id", uuid.uuid4().hex[:12])
            a.setdefault("name", Path(a.get("script", "app")).stem)
            a.setdefault("script", "")
            a.setdefault("args", "")
            a.setdefault("cwd", "")
            a.setdefault("python", "")
            a.setdefault("env", {})
            a.setdefault("note", "")
            a.setdefault("run_as_admin", False)
            a.setdefault("last_started", 0.0)
            a.pop("auto_restart", None)

    def save(self) -> bool:
        try:
            payload = json.dumps(self.apps, ensure_ascii=False, indent=2)
            tmp = CONFIG_FILE.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            if CONFIG_FILE.exists():
                CONFIG_FILE.unlink()
            tmp.replace(CONFIG_FILE)
            _diag(f"save: 成功  {len(self.apps)} 条  {len(payload)} 字节")
            return True
        except Exception as e:
            _diag(f"save: 失败 {e!r}")
            print(f"[PyLaunch] 保存失败: {e}")
            return False

    def get(self, app_id: str) -> dict | None:
        for a in self.apps:
            if a["id"] == app_id:
                return a
        return None

    def add(self, data: dict) -> dict:
        data = dict(data)
        data["id"] = uuid.uuid4().hex[:12]
        if not data.get("name"):
            data["name"] = Path(data.get("script", "app")).stem
        data.setdefault("run_as_admin", False)
        data.setdefault("last_started", 0.0)
        self.apps.append(data)
        ok = self.save()
        _diag(f"add: {data['name']} id={data['id']} "
              f"管理员={data.get('run_as_admin')} "
              f"保存={'成功' if ok else '失败'}  总数={len(self.apps)}")
        return data

    def update(self, app_id: str, data: dict):
        app = self.get(app_id)
        if app:
            app.update(data)
            ok = self.save()
            _diag(f"update: {app_id} 保存={'成功' if ok else '失败'}")

    def remove(self, app_id: str):
        self.stop(app_id)
        before = len(self.apps)
        self.apps = [a for a in self.apps if a["id"] != app_id]
        ok = self.save()
        _diag(f"remove: {app_id}  {before}→{len(self.apps)}  "
              f"保存={'成功' if ok else '失败'}")

    def log_path(self, app_id: str) -> Path:
        return LOG_DIR / f"{app_id}.log"

    # ---------------- 进程扫描 ----------------
    def _scan(self, ttl: float = 1.5) -> dict[str, tuple[int, float]]:
        now = time.time()
        if self._scan_cache and now - self._scan_time < ttl:
            return self._scan_cache

        result: dict[str, tuple[int, float]] = {}
        for p in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
            try:
                name = (p.info.get("name") or "").lower()
                if "python" not in name:
                    continue
                cmd = p.info.get("cmdline") or []
                if len(cmd) < 2:
                    continue
                script = None
                for part in cmd[1:]:
                    lp = part.lower()
                    if lp.endswith(".py") or lp.endswith(".pyw"):
                        script = part
                        break
                if not script:
                    continue
                key = _norm(script)
                ct = p.info.get("create_time") or 0.0
                if key not in result or ct < result[key][1]:
                    result[key] = (p.info["pid"], ct)
            except (psutil.NoSuchProcess, psutil.AccessDenied,
                    psutil.ZombieProcess):
                continue

        self._scan_cache = result
        self._scan_time = now
        return result

    def invalidate(self):
        self._scan_time = 0.0

    def find_pid(self, app: dict | None) -> int | None:
        if not app or not app.get("script"):
            return None
        entry = self._scan(ttl=1.5).get(_norm(app["script"]))
        return entry[0] if entry else None

    def status(self, app_id: str) -> str:
        app = self.get(app_id)
        if not app:
            return "missing"
        return "running" if self.find_pid(app) else "stopped"

    # ---------------- 启动 ----------------
    def start(self, app_id: str) -> tuple[bool, str]:
        app = self.get(app_id)
        if not app:
            return False, "应用不存在"
        if self.find_pid(app):
            return False, "应用已在运行"

        script = Path(app["script"])
        if not script.exists():
            return False, f"脚本不存在：{script}"

        cwd = app.get("cwd") or str(script.parent)
        if not Path(cwd).exists():
            cwd = str(script.parent)

        python = app.get("python") or detect_pythonw()
        if python not in ("pythonw", "python") and not Path(python).exists():
            python = detect_pythonw()

        args = split_args(app.get("args", ""))
        use_admin = bool(app.get("run_as_admin", False))

        # ---- 日志 ----
        try:
            with open(self.log_path(app_id), "a", encoding="utf-8") as f:
                f.write(f"\n{'─' * 60}\n")
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] ▶ 启动\n")
                f.write(f"解释器:   {python}\n")
                f.write(f"脚本:     {script}\n")
                if args:
                    f.write(f"参数:     {' '.join(args)}\n")
                f.write(f"工作目录: {cwd}\n")
                if use_admin:
                    f.write(f"权限:     管理员（UAC）\n")
                f.write(f"{'─' * 60}\n")
        except Exception:
            pass

        try:
            self._spawn_detached(python, str(script), args, cwd, app)
        except Exception as e:
            _diag(f"start: 启动失败 {e!r}")
            return False, f"启动失败: {e}"

        app["last_started"] = time.time()
        self.save()
        self.invalidate()

        deadline = time.time() + 3.0
        while time.time() < deadline:
            time.sleep(0.15)
            pid = self.find_pid(app)
            if pid:
                _diag(f"start: {app['name']}  PID={pid}")
                return True, f"已启动（PID {pid}）"
        _diag(f"start: {app['name']}  3 秒内未检测到进程")
        return True, "已发起启动（未在 3 秒内检测到进程，请稍后刷新）"

    def _spawn_detached(self, python: str, script: str,
                        args: list[str], cwd: str, app: dict):
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        extra_env: dict[str, str] = {}
        for k, v in (app.get("env") or {}).items():
            extra_env[str(k)] = str(v)
            env[str(k)] = str(v)

        use_admin = bool(app.get("run_as_admin", False))

        # --- 管理员启动 ---
        if IS_WINDOWS and use_admin and not is_admin():
            # PyLaunch 本身不是管理员，但应用要求管理员 → 走 UAC
            self._spawn_via_runas(python, script, args, cwd, extra_env)
            return

        # 如果 PyLaunch 本身是管理员，普通启动的子进程自动继承管理员权限
        if IS_WINDOWS:
            cmd_list = ["cmd", "/c", "start", "", "/B", python, script] + args
            subprocess.Popen(
                cmd_list,
                cwd=cwd,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=True,
            )
        else:
            subprocess.Popen(
                [python, script] + args,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )

    def _spawn_via_runas(self, python: str, script: str,
                         args: list[str], cwd: str,
                         extra_env: dict[str, str]):
        """通过 ShellExecuteW + runas 以管理员身份启动，会弹 UAC"""
        import ctypes

        parts: list[str] = []
        for k, v in extra_env.items():
            vs = str(v).replace('"', '""')
            parts.append(f'set "{k}={vs}"')

        launch = f'start "" /B "{python}" "{script}"'
        if args:
            launch += " " + " ".join(
                f'"{a}"' if (" " in a or "\t" in a) else a for a in args
            )
        parts.append(launch)

        full = " && ".join(parts)
        params = f'/c {full}'

        ret = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "cmd.exe",
            params,
            cwd,
            0,   # SW_HIDE
        )
        if ret <= 32:
            err_msg = {
                0: "内存不足",
                2: "文件未找到",
                3: "路径未找到",
                5: "用户拒绝了 UAC 授权",
                31: "无法读取",
                32: "无法加载",
            }.get(ret, f"错误码 {ret}")
            raise RuntimeError(f"管理员权限启动失败：{err_msg}")

    # ---------------- 停止 ----------------
    def stop(self, app_id: str) -> tuple[bool, str]:
        app = self.get(app_id)
        if not app:
            return False, "应用不存在"
        pid = self.find_pid(app)
        if not pid:
            return False, "应用未在运行"
        try:
            self._kill_tree(pid)
            self.invalidate()
            _diag(f"stop: {app['name']}  PID={pid}")
            return True, f"已停止（PID {pid}）"
        except psutil.AccessDenied:
            return False, ("权限不足，无法停止该进程。\n"
                           "请点击侧栏「以管理员重启」后再试。")
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _kill_tree(pid: int, timeout: float = 3.0):
        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return
        procs = []
        try:
            procs = proc.children(recursive=True)
        except Exception:
            pass
        procs.append(proc)

        access_denied = False
        for p in procs:
            try:
                p.terminate()
            except psutil.AccessDenied:
                access_denied = True
            except Exception:
                pass

        _, alive = psutil.wait_procs(procs, timeout=timeout)
        for p in alive:
            try:
                p.kill()
            except psutil.AccessDenied:
                access_denied = True
            except Exception:
                pass

        if access_denied:
            raise psutil.AccessDenied(pid, "权限不足")

    def stop_all(self) -> int:
        n = 0
        for a in list(self.apps):
            ok, _ = self.stop(a["id"])
            if ok:
                n += 1
        return n

    def start_all(self) -> tuple[int, int]:
        started, failed = 0, 0
        for a in list(self.apps):
            ok, _ = self.start(a["id"])
            if ok:
                started += 1
            else:
                failed += 1
        return started, failed

    # ---------------- 资源统计 ----------------
    def stats(self, app_id: str) -> dict:
        app = self.get(app_id)
        if not app:
            return {}
        pid = self.find_pid(app)
        if not pid:
            return {}
        try:
            p = psutil.Process(pid)
            with p.oneshot():
                mem = p.memory_info().rss
                cpu = p.cpu_percent(interval=None)
                ct = p.create_time()
                threads = p.num_threads()
            ports: list[int] = []
            try:
                getter = getattr(p, "net_connections", None) or p.connections
                for c in getter(kind="inet"):
                    if c.status == psutil.CONN_LISTEN and c.laddr:
                        ports.append(c.laddr.port)
            except Exception:
                pass
            return {
                "pid": pid,
                "mem": mem,
                "cpu": cpu,
                "threads": threads,
                "started_at": ct,
                "uptime": time.time() - ct,
                "ports": sorted(set(ports)),
            }
        except Exception:
            return {}

    # ---------------- 导入外部进程 ----------------
    def scan_external(self) -> list[dict]:
        managed = {_norm(a["script"]) for a in self.apps if a.get("script")}
        found: dict[str, dict] = {}
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (p.info.get("name") or "").lower()
                if "python" not in name:
                    continue
                cmd = p.info.get("cmdline") or []
                if len(cmd) < 2:
                    continue
                script = None
                for part in cmd[1:]:
                    lp = part.lower()
                    if lp.endswith(".py") or lp.endswith(".pyw"):
                        script = part
                        break
                if not script:
                    continue
                key = _norm(script)
                if key in managed or key in found:
                    continue
                found[key] = {
                    "path": os.path.abspath(script),
                    "pid": p.info["pid"],
                    "args": " ".join(cmd[2:]) if len(cmd) > 2 else "",
                    "python": cmd[0],
                }
            except Exception:
                continue
        return list(found.values())