import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import json
import os
import random
import signal
import sqlite3
import subprocess
import threading
import time

AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".wma", ".opus"}
PLAYLISTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playlists.json")
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playlist.db")


class AudioPlayer:
    def __init__(self, on_track_end=None):
        self._proc = None
        self._paused = False
        self._current_file = None
        self._play_start_time = 0
        self._accumulated_elapsed = 0
        self._duration_cache = {}
        self.on_track_end = on_track_end
        self._monitor_thread = None

    @property
    def is_playing(self):
        return self._proc is not None and self._proc.poll() is None

    @property
    def is_paused(self):
        return self._paused

    @property
    def current_file(self):
        return self._current_file

    @property
    def elapsed(self):
        if self._play_start_time > 0:
            return self._accumulated_elapsed + (time.time() - self._play_start_time)
        return self._accumulated_elapsed

    def _get_duration(self, filepath):
        if filepath in self._duration_cache:
            return self._duration_cache[filepath]
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", filepath],
                capture_output=True, text=True, timeout=10,
            )
            dur = float(result.stdout.strip())
        except (ValueError, subprocess.TimeoutExpired, FileNotFoundError):
            dur = 0
        self._duration_cache[filepath] = dur
        return dur

    @property
    def duration(self):
        if self._current_file:
            return self._get_duration(self._current_file)
        return 0

    def play(self, filepath):
        self.stop()
        self._current_file = filepath
        self._paused = False
        self._play_start_time = time.time()
        self._accumulated_elapsed = 0
        proc = subprocess.Popen(
            ["afplay", filepath],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._proc = proc
        self._monitor_thread = threading.Thread(
            target=self._monitor, args=(proc,), daemon=True
        )
        self._monitor_thread.start()

    def _monitor(self, proc):
        proc.wait()
        if self._proc is proc and self.on_track_end:
            elapsed = time.time() - self._play_start_time
            if elapsed >= 0.5:
                self.on_track_end()

    def pause(self):
        if self._proc and self._proc.poll() is None:
            self._paused = True
            self._accumulated_elapsed += time.time() - self._play_start_time
            self._play_start_time = 0
            self._proc.send_signal(signal.SIGSTOP)

    def resume(self):
        if self._proc and self._proc.poll() is None:
            self._paused = False
            self._play_start_time = time.time()
            self._proc.send_signal(signal.SIGCONT)

    def toggle_pause(self):
        if self._paused:
            self.resume()
        else:
            self.pause()

    def stop(self):
        if self._proc:
            try:
                if self._paused:
                    self._proc.send_signal(signal.SIGCONT)
                self._proc.terminate()
            except ProcessLookupError:
                pass
        self._proc = None
        self._paused = False
        self._current_file = None
        self._play_start_time = 0
        self._accumulated_elapsed = 0


class AudioPlayerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("音频播放器")
        self.root.geometry("600x450")
        self.root.resizable(True, True)

        self.player = AudioPlayer(on_track_end=self._on_track_end)
        self.playlist = []          # list of full file paths
        self._current_index = -1
        self._play_mode = tk.StringVar(value="列表循环")
        self._random_played = set()  # indices played in current random cycle

        self._init_db()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
        self._load_playlist_from_db()
        self._poll_state()

    def _build_ui(self):
        # --- Now playing ---
        now_frame = ttk.LabelFrame(self.root, text="正在播放", padding=10)
        now_frame.pack(fill="x", padx=15, pady=(15, 5))

        self.track_var = tk.StringVar(value="未在播放")
        ttk.Label(now_frame, textvariable=self.track_var, font=("", 12)).pack(
            anchor="w"
        )

        # --- Progress ---
        progress_frame = ttk.Frame(now_frame)
        progress_frame.pack(fill="x", pady=(8, 0))

        self.progress_bar = ttk.Progressbar(
            progress_frame, mode="determinate", maximum=1000
        )
        self.progress_bar.pack(fill="x")

        self.time_var = tk.StringVar(value="00:00 / 00:00")
        ttk.Label(progress_frame, textvariable=self.time_var, anchor="e").pack(
            fill="x", pady=(2, 0)
        )

        # --- Controls ---
        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(fill="x", padx=15, pady=5)

        self.prev_btn = ttk.Button(ctrl_frame, text="上一首", command=self._prev)
        self.prev_btn.pack(side="left", padx=(0, 5))

        self.play_btn = ttk.Button(ctrl_frame, text="播放", command=self._toggle_play)
        self.play_btn.pack(side="left", padx=(0, 5))

        self.next_btn = ttk.Button(ctrl_frame, text="下一首", command=self._next)
        self.next_btn.pack(side="left", padx=(0, 5))

        self.stop_btn = ttk.Button(ctrl_frame, text="停止", command=self._stop)
        self.stop_btn.pack(side="left", padx=(0, 10))

        ttk.Label(ctrl_frame, text="模式:").pack(side="left", padx=(0, 2))
        self.mode_combo = ttk.Combobox(
            ctrl_frame,
            textvariable=self._play_mode,
            values=["列表循环", "单曲循环", "列表随机"],
            state="readonly",
            width=10,
        )
        self.mode_combo.pack(side="left", padx=(0, 10))
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_changed)

        ttk.Button(ctrl_frame, text="歌单", command=self._show_playlist_manager).pack(
            side="left"
        )

        # --- Playlist ---
        pl_frame = ttk.LabelFrame(self.root, text="播放列表", padding=10)
        pl_frame.pack(fill="both", expand=True, padx=15, pady=5)

        list_frame = ttk.Frame(pl_frame)
        list_frame.pack(fill="both", expand=True)

        self.playlist_box = tk.Listbox(
            list_frame,
            font=("", 11),
            selectmode="extended",
            activestyle="none",
            exportselection=False,
        )
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        scrollbar.config(command=self.playlist_box.yview)
        self.playlist_box.config(yscrollcommand=scrollbar.set)

        self.playlist_box.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.playlist_box.bind("<Double-1>", lambda e: self._play_selected())

        # --- Playlist buttons ---
        pl_btn_frame = ttk.Frame(pl_frame)
        pl_btn_frame.pack(fill="x", pady=(8, 0))

        ttk.Button(pl_btn_frame, text="添加歌曲", command=self._add_songs).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(pl_btn_frame, text="移除所选", command=self._remove_selected).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(pl_btn_frame, text="上移", command=self._move_up).pack(
            side="left", padx=(0, 5)
        )
        ttk.Button(pl_btn_frame, text="下移", command=self._move_down).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(pl_btn_frame, text="清空列表", command=self._clear_playlist).pack(
            side="left"
        )

    # --- Playback callbacks ---

    def _on_track_end(self):
        self.root.after(0, self._auto_advance)

    def _poll_state(self):
        """Periodically update button states and progress."""
        if self.player.is_paused:
            self.play_btn.config(text="继续")
        elif self.player.is_playing:
            self.play_btn.config(text="暂停")
        else:
            self.play_btn.config(text="播放")

        self._update_progress()
        self.root.after(300, self._poll_state)

    def _update_progress(self):
        dur = self.player.duration
        el = self.player.elapsed

        if dur > 0 and self.player.is_playing:
            pct = min(el / dur * 1000, 1000)
            self.progress_bar["value"] = pct
            self.time_var.set(
                f"{self._fmt_time(el)} / {self._fmt_time(dur)}"
            )
        elif self.player.is_paused:
            self.time_var.set(
                f"{self._fmt_time(el)} / {self._fmt_time(dur)} (已暂停)"
            )
        else:
            self.progress_bar["value"] = 0
            self.time_var.set("00:00 / 00:00")

    @staticmethod
    def _fmt_time(seconds):
        m = int(seconds) // 60
        s = int(seconds) % 60
        return f"{m:02d}:{s:02d}"

    def _refresh_display(self):
        idx = self._current_index
        if 0 <= idx < len(self.playlist):
            name = os.path.basename(self.playlist[idx])
            self.track_var.set(f"{idx + 1}/{len(self.playlist)}  {name}")
        elif self.playlist:
            self.track_var.set(f"共 {len(self.playlist)} 首歌曲，未在播放")
        else:
            self.track_var.set("未在播放")

    def _refresh_listbox(self):
        self.playlist_box.delete(0, "end")
        for fp in self.playlist:
            self.playlist_box.insert("end", os.path.basename(fp))
        if 0 <= self._current_index < len(self.playlist):
            self.playlist_box.selection_set(self._current_index)
            self.playlist_box.see(self._current_index)

    # --- Playback controls ---

    def _play_index(self, index):
        if index < 0 or index >= len(self.playlist):
            return
        self._current_index = index
        self._random_played.add(index)
        self.player.play(self.playlist[index])
        self._refresh_display()
        self._refresh_listbox()

    def _toggle_play(self):
        if self.player.is_paused:
            self.player.resume()
            self._refresh_display()
        elif self.player.is_playing:
            self.player.pause()
            self._refresh_display()
        else:
            self._play_selected()

    def _play_selected(self):
        sel = self.playlist_box.curselection()
        if sel:
            self._play_index(sel[0])
        elif self.playlist:
            self._play_index(0)

    def _stop(self):
        self.player.stop()
        self._current_index = -1
        self._random_played.clear()
        self._update_progress()
        self._refresh_display()
        self._refresh_listbox()

    def _prev(self):
        if not self.playlist:
            return
        idx = self._current_index - 1
        if idx < 0:
            idx = len(self.playlist) - 1
        self._play_index(idx)

    def _next(self):
        """Manual next track: always play the next song in list order."""
        if not self.playlist:
            return
        if self._current_index < 0:
            self._play_index(0)
        else:
            idx = self._current_index + 1
            if idx >= len(self.playlist):
                idx = 0
            self._play_index(idx)

    def _auto_advance(self):
        """Auto-advance when a track ends — respects the selected play mode."""
        if not self.playlist:
            return

        mode = self._play_mode.get()
        if mode == "单曲循环":
            if 0 <= self._current_index < len(self.playlist):
                self._play_index(self._current_index)
        elif mode == "列表随机":
            if len(self._random_played) >= len(self.playlist):
                self._random_played.clear()
            available = [
                i for i in range(len(self.playlist)) if i not in self._random_played
            ]
            idx = random.choice(available)
            self._play_index(idx)
        else:  # 列表循环
            idx = self._current_index + 1
            if idx >= len(self.playlist):
                idx = 0
            self._play_index(idx)

    def _on_mode_changed(self, event=None):
        self._random_played.clear()
        if 0 <= self._current_index < len(self.playlist):
            self._random_played.add(self._current_index)

    # --- Database ---

    def _init_db(self):
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS playlist ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  filepath TEXT NOT NULL UNIQUE,"
                "  sort_order INTEGER NOT NULL"
                ")"
            )
            conn.commit()

    def _load_playlist_from_db(self):
        self.playlist.clear()
        with sqlite3.connect(DB_FILE) as conn:
            rows = conn.execute(
                "SELECT filepath FROM playlist ORDER BY sort_order"
            ).fetchall()
        for (fp,) in rows:
            if os.path.isfile(fp):
                self.playlist.append(fp)
            else:
                self._db_delete(fp)
        self._refresh_listbox()
        self._refresh_display()

    def _db_insert(self, filepath):
        with sqlite3.connect(DB_FILE) as conn:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) FROM playlist"
            ).fetchone()[0]
            conn.execute(
                "INSERT OR IGNORE INTO playlist (filepath, sort_order) VALUES (?, ?)",
                (filepath, max_order + 1),
            )
            conn.commit()

    def _db_delete(self, filepath):
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("DELETE FROM playlist WHERE filepath = ?", (filepath,))
            conn.commit()

    def _db_clear(self):
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("DELETE FROM playlist")
            conn.commit()

    def _db_swap_order(self, fp_a, fp_b):
        with sqlite3.connect(DB_FILE) as conn:
            row_a = conn.execute(
                "SELECT sort_order FROM playlist WHERE filepath = ?", (fp_a,)
            ).fetchone()
            row_b = conn.execute(
                "SELECT sort_order FROM playlist WHERE filepath = ?", (fp_b,)
            ).fetchone()
            if row_a and row_b:
                conn.execute(
                    "UPDATE playlist SET sort_order = ? WHERE filepath = ?",
                    (row_b[0], fp_a),
                )
                conn.execute(
                    "UPDATE playlist SET sort_order = ? WHERE filepath = ?",
                    (row_a[0], fp_b),
                )
                conn.commit()

    def _db_replace_all(self, filepaths):
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("DELETE FROM playlist")
            for i, fp in enumerate(filepaths):
                conn.execute(
                    "INSERT INTO playlist (filepath, sort_order) VALUES (?, ?)",
                    (fp, i),
                )
            conn.commit()

    # --- Playlist management ---

    def _add_songs(self):
        paths = filedialog.askopenfilenames(
            title="选择音频文件",
            filetypes=[
                ("音频文件", "*.mp3 *.m4a *.aac *.flac *.wav *.ogg *.wma *.opus"),
                ("所有文件", "*.*"),
            ],
        )
        for p in paths:
            if p not in self.playlist:
                self.playlist.append(p)
                self._db_insert(p)
        if paths:
            self._refresh_listbox()
            self._refresh_display()

    def _remove_selected(self):
        sel = list(self.playlist_box.curselection())
        if not sel:
            return

        playing_removed = self._current_index in sel and self.player.is_playing
        if playing_removed:
            self.player.stop()

        removed_fps = []
        for i in reversed(sel):
            removed_fps.append(self.playlist[i])
            del self.playlist[i]
            if i < self._current_index:
                self._current_index -= 1

        if playing_removed:
            self._current_index = -1

        for fp in removed_fps:
            self._db_delete(fp)

        self._refresh_listbox()
        self._refresh_display()

    def _clear_playlist(self):
        if not self.playlist:
            return
        self.player.stop()
        self._current_index = -1
        self.playlist.clear()
        self._random_played.clear()
        self._db_clear()
        self._refresh_listbox()
        self._refresh_display()

    def _move_up(self):
        sel = self.playlist_box.curselection()
        if not sel or len(self.playlist) < 2:
            return
        i = sel[0]
        if i <= 0:
            return
        self._swap_tracks(i, i - 1)

    def _move_down(self):
        sel = self.playlist_box.curselection()
        if not sel or len(self.playlist) < 2:
            return
        i = sel[0]
        if i >= len(self.playlist) - 1:
            return
        self._swap_tracks(i, i + 1)

    def _swap_tracks(self, i, j):
        fp_a, fp_b = self.playlist[i], self.playlist[j]
        self.playlist[i], self.playlist[j] = self.playlist[j], self.playlist[i]
        self._db_swap_order(fp_a, fp_b)
        if self._current_index == i:
            self._current_index = j
        elif self._current_index == j:
            self._current_index = i
        self._refresh_listbox()
        self.playlist_box.selection_set(j)
        self.playlist_box.see(j)

    # --- Playlist file management ---

    def _load_playlists_data(self):
        if os.path.exists(PLAYLISTS_FILE):
            with open(PLAYLISTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_playlists_data(self, data):
        with open(PLAYLISTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _show_playlist_manager(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("歌单管理")
        dialog.geometry("450x380")
        dialog.resizable(True, True)
        dialog.transient(self.root)
        dialog.grab_set()

        data = self._load_playlists_data()

        ttk.Label(
            dialog, text=f"共 {len(data)} 个歌单", font=("", 10)
        ).pack(padx=15, pady=(15, 5))

        # --- Playlist list ---
        tree_frame = ttk.Frame(dialog)
        tree_frame.pack(fill="both", expand=True, padx=15, pady=5)

        columns = ("name", "count")
        tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )
        tree.heading("name", text="歌单名称")
        tree.heading("count", text="歌曲数量")
        tree.column("name", width=280, anchor="w")
        tree.column("count", width=80, anchor="center")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for name, tracks in data.items():
            tree.insert("", "end", values=(name, len(tracks)))

        tree.bind("<Double-1>", lambda e: self._load_and_play(tree, data, dialog))

        # --- Info label ---
        info_var = tk.StringVar()
        ttk.Label(dialog, textvariable=info_var, wraplength=420).pack(
            padx=15, pady=(5, 0)
        )

        def update_info():
            sel = tree.selection()
            if sel:
                name = tree.item(sel[0], "values")[0]
                count = tree.item(sel[0], "values")[1]
                info_var.set(f"已选中: {name}（{count} 首）")
            else:
                info_var.set("")

        tree.bind("<<TreeviewSelect>>", lambda e: update_info())

        # --- Buttons ---
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", padx=15, pady=(10, 15))

        def create():
            name_dialog = tk.Toplevel(dialog)
            name_dialog.title("创建歌单")
            name_dialog.geometry("320x120")
            name_dialog.resizable(False, False)
            name_dialog.transient(dialog)
            name_dialog.grab_set()

            ttk.Label(name_dialog, text="请输入歌单名称：").pack(pady=(15, 5))

            name_var = tk.StringVar()
            entry = ttk.Entry(name_dialog, textvariable=name_var, font=("", 11))
            entry.pack(fill="x", padx=20)
            entry.focus_set()

            def confirm():
                name = name_var.get().strip()
                if not name:
                    messagebox.showwarning("提示", "歌单名称不能为空", parent=name_dialog)
                    return
                data = self._load_playlists_data()
                if name in data:
                    # Overwrite: save current playlist to existing name
                    if not messagebox.askyesno(
                        "确认", f"歌单「{name}」已存在，是否用当前播放列表覆盖？",
                        parent=name_dialog,
                    ):
                        return
                data[name] = list(self.playlist)
                self._save_playlists_data(data)
                name_dialog.destroy()
                dialog.destroy()
                self._show_playlist_manager()

            entry.bind("<Return>", lambda e: confirm())
            ttk.Button(name_dialog, text="确定", command=confirm).pack(pady=10)

        ttk.Button(btn_frame, text="创建歌单", command=create).pack(
            side="left", padx=(0, 10)
        )

        def load_selected():
            self._load_and_play(tree, data, dialog)

        ttk.Button(btn_frame, text="加载歌单", command=load_selected).pack(
            side="left", padx=(0, 10)
        )

        def delete_selected():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("提示", "请先选择一个歌单", parent=dialog)
                return
            name = tree.item(sel[0], "values")[0]
            if messagebox.askyesno("确认", f"确定要删除歌单「{name}」吗？", parent=dialog):
                data = self._load_playlists_data()
                data.pop(name, None)
                self._save_playlists_data(data)
                tree.delete(sel[0])
                update_info()

        ttk.Button(btn_frame, text="删除歌单", command=delete_selected).pack(
            side="left", padx=(0, 10)
        )

        def save_current():
            if not self.playlist:
                messagebox.showinfo("提示", "当前播放列表为空", parent=dialog)
                return
            data = self._load_playlists_data()
            data["当前列表"] = list(self.playlist)
            self._save_playlists_data(data)
            dialog.destroy()
            self._show_playlist_manager()

        ttk.Button(btn_frame, text="保存当前", command=save_current).pack(side="left")

    def _load_and_play(self, tree, data, dialog):
        sel = tree.selection()
        if not sel:
            return
        name = tree.item(sel[0], "values")[0]
        self.player.stop()
        self._current_index = -1
        self.playlist = [p for p in data[name] if os.path.isfile(p)]
        self._db_replace_all(self.playlist)
        self._refresh_listbox()
        self._refresh_display()
        dialog.destroy()

    def _on_close(self):
        self.player.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    AudioPlayerApp().run()
