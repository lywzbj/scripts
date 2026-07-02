import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import signal
import subprocess
import threading

AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".wma", ".opus"}


class AudioPlayer:
    def __init__(self, on_track_end=None):
        self._proc = None
        self._paused = False
        self._current_file = None
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
        self._proc = subprocess.Popen(
            ["afplay", filepath],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._monitor_thread = threading.Thread(
            target=self._monitor, daemon=True
        )
        self._monitor_thread.start()

    def _monitor(self):
        if self._proc:
            self._proc.wait()
        if not self._paused and self.on_track_end:
            self.on_track_end()

    def pause(self):
        if self._proc and self._proc.poll() is None:
            self._paused = True
            self._proc.send_signal(signal.SIGSTOP)

    def resume(self):
        if self._proc and self._proc.poll() is None:
            self._paused = False
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
                self._proc.wait(timeout=3)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass
        self._proc = None
        self._paused = False
        self._current_file = None


class AudioPlayerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("音频播放器")
        self.root.geometry("600x450")
        self.root.resizable(True, True)

        self.player = AudioPlayer(on_track_end=self._on_track_end)
        self.playlist = []          # list of full file paths
        self._current_index = -1

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

        self.stop_btn = ttk.Button(ctrl_frame, text="停止", command=self._stop)
        self.stop_btn.pack(side="left")

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
        self.root.after(0, self._next)

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
        if not self.playlist:
            return
        if self._current_index + 1 < len(self.playlist):
            self._play_index(self._current_index + 1)
        else:
            self.player.stop()
            self._current_index = -1
            self._refresh_display()
            self._refresh_listbox()

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
        self._refresh_listbox()
        self._refresh_display()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    AudioPlayerApp().run()
