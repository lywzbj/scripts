import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import json
import os
import random
import signal
import subprocess
import threading
import time

AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".wma", ".opus"}
PLAYLISTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playlists.json")


class AudioPlayer:
    def __init__(self, on_track_end=None):
        self._proc = None
        self._paused = False
        self._current_file = None
        self._play_start_time = 0
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

    def play(self, filepath):
        self.stop()
        self._current_file = filepath
        self._paused = False
        self._play_start_time = time.time()
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

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
        self._poll_state()

    def _build_ui(self):
        # --- Now playing ---
        now_frame = ttk.LabelFrame(self.root, text="正在播放", padding=10)
        now_frame.pack(fill="x", padx=15, pady=(15, 5))

        self.track_var = tk.StringVar(value="未在播放")
        ttk.Label(now_frame, textvariable=self.track_var, font=("", 12)).pack(
            anchor="w"
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
        ttk.Button(pl_btn_frame, text="清空列表", command=self._clear_playlist).pack(
            side="left"
        )

    # --- Playback callbacks ---

    def _on_track_end(self):
        self.root.after(0, self._auto_advance)

    def _poll_state(self):
        """Periodically update button states."""
        if self.player.is_paused:
            self.play_btn.config(text="继续")
        elif self.player.is_playing:
            self.play_btn.config(text="暂停")
        else:
            self.play_btn.config(text="播放")
        self.root.after(300, self._poll_state)

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
        if paths:
            self._refresh_listbox()
            self._refresh_display()

    def _remove_selected(self):
        sel = list(self.playlist_box.curselection())
        if not sel:
            return

        # Determine if the currently playing track is being removed
        playing_removed = self._current_index in sel and self.player.is_playing

        if playing_removed:
            self.player.stop()

        for i in reversed(sel):
            del self.playlist[i]
            if i < self._current_index:
                self._current_index -= 1

        if playing_removed:
            self._current_index = -1

        self._refresh_listbox()
        self._refresh_display()

    def _clear_playlist(self):
        if not self.playlist:
            return
        self.player.stop()
        self._current_index = -1
        self.playlist.clear()
        self._random_played.clear()
        self._refresh_listbox()
        self._refresh_display()

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
        self.playlist = list(data[name])
        # Filter out non-existent files
        self.playlist = [p for p in self.playlist if os.path.isfile(p)]
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
