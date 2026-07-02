import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import requests
import re
import os
import subprocess
import threading

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com",
    "Origin": "https://www.bilibili.com",
}


class BilibiliDownloader:
    def __init__(self, progress_callback=None, log_callback=None):
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _log(self, msg):
        if self.log_callback:
            self.log_callback(msg)

    def _progress(self, pct):
        if self.progress_callback:
            self.progress_callback(pct)

    def _resolve_short_url(self, url):
        """Resolve b23.tv short links by following redirects."""
        resp = requests.get(url, headers=HEADERS, allow_redirects=False, timeout=10)
        if resp.status_code in (301, 302, 307, 308):
            location = resp.headers.get("Location", "")
            if location.startswith("/"):
                location \
                    = "https://www.bilibili.com" + location
            return location or url
        return url

    def _parse_url(self, url):
        """Extract BV/AV id from a Bilibili video URL."""
        url = url.strip()

        if "b23.tv" in url:
            self._log("解析短链接...")
            url = self._resolve_short_url(url)

        # BV号: BV1xx2xx3xx
        bv_match = re.search(r"(BV[a-zA-Z0-9]{10})", url)
        if bv_match:
            return {"bvid": bv_match.group(1)}

        # AV号: av123456 或 /av123456
        av_match = re.search(r"av(\d+)", url, re.IGNORECASE)
        if av_match:
            return {"avid": int(av_match.group(1))}

        return None

    def _get_video_info(self, params):
        """Fetch video title and cid list."""
        if "bvid" in params:
            api = f"https://api.bilibili.com/x/web-interface/view?bvid={params['bvid']}"
        else:
            api = f"https://api.bilibili.com/x/web-interface/view?aid={params['avid']}"

        resp = requests.get(api, headers=HEADERS, timeout=15)
        data = resp.json()

        if data["code"] != 0:
            raise Exception(f"获取视频信息失败: code={data['code']}, {data.get('message', '')}")

        video_data = data["data"]
        title = video_data["title"]
        bvid = video_data["bvid"]
        pages = video_data.get("pages", [{"cid": video_data["cid"], "part": title}])

        return {"title": title, "bvid": bvid, "pages": pages}

    def _get_stream_urls(self, bvid, cid):
        """Fetch dash stream URLs for video and audio."""
        api = (
            f"https://api.bilibili.com/x/player/playurl"
            f"?bvid={bvid}&cid={cid}&qn=127&fnval=4048&fourk=1"
        )
        resp = requests.get(api, headers=HEADERS, timeout=15)
        data = resp.json()

        if data["code"] != 0:
            raise Exception(f"获取播放地址失败: code={data['code']}, {data.get('message', '')}")

        dash = data["data"].get("dash")
        if not dash:
            # Fallback: no dash, maybe only durl (flv)
            durl = data["data"].get("durl")
            if durl:
                return {"flv_segments": durl}
            raise Exception("未找到可用的视频流")

        videos = dash.get("video", [])
        audios = dash.get("audio", [])

        if not videos:
            raise Exception("未找到视频流")

        # Pick highest quality video and audio
        best_video = max(videos, key=lambda v: v["bandwidth"])
        best_audio = max(audios, key=lambda a: a["bandwidth"]) if audios else None

        return {
            "video_url": best_video["base_url"],
            "video_quality": best_video.get("id"),
            "audio_url": best_audio["base_url"] if best_audio else None,
        }

    def _download_with_progress(self, url, dest, label, start_pct, end_pct):
        """Download a file and report progress within a range."""
        headers = {**HEADERS, "Referer": "https://www.bilibili.com"}
        resp = requests.get(url, headers=headers, stream=True, timeout=30)
        total = int(resp.headers.get("content-length", 0))

        if total == 0:
            self._log(f"{label}: 无法获取文件大小，开始下载...")
        else:
            self._log(f"{label}: {total / 1024 / 1024:.1f} MB")

        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if self._cancel:
                    return False
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = start_pct + (end_pct - start_pct) * (downloaded / total)
                        self._progress(pct)

        return True

    def download(self, url, save_dir):
        """Main download flow."""
        self._cancel = False
        self._progress(0)

        # Step 1: Parse URL
        self._log(">>> 解析视频地址...")
        params = self._parse_url(url)
        if not params:
            raise Exception("无法识别的B站视频地址")

        # Step 2: Get video info
        self._log(">>> 获取视频信息...")
        info = self._get_video_info(params)
        title = self._sanitize_filename(info["title"])
        bvid = info["bvid"]
        pages = info["pages"]
        self._log(f"    标题: {title}")
        self._log(f"    分P数: {len(pages)}")
        self._progress(5)

        # Step 3: Process each page
        for idx, page in enumerate(pages):
            if self._cancel:
                self._log("已取消下载")
                return

            cid = page["cid"]
            part_name = page.get("part", f"P{idx + 1}")

            if len(pages) > 1:
                self._log(f"\n>>> 正在下载 P{idx + 1}/{len(pages)}: {part_name}")
                filename = self._sanitize_filename(f"{title} - {part_name}")
            else:
                filename = title

            self._log(">>> 获取播放地址...")
            streams = self._get_stream_urls(bvid, cid)

            if "flv_segments" in streams:
                self._log(">>> 正在下载FLV流...")
                video_path = os.path.join(save_dir, f"{filename}.flv")
                segments = streams["flv_segments"]
                with open(video_path, "wb") as f:
                    for i, seg in enumerate(segments):
                        if self._cancel:
                            return
                        seg_url = seg["url"]
                        seg_resp = requests.get(seg_url, headers=HEADERS, timeout=30)
                        f.write(seg_resp.content)
                        pct = 10 + 85 * ((i + 1) / len(segments))
                        self._progress(pct)
                self._progress(95)
                self._log(f"    完成: {video_path}")
            else:
                base_start, base_end = 10, 95
                if streams["audio_url"]:
                    # Download video and audio separately
                    video_tmp = os.path.join(save_dir, f"{filename}.video.m4s")
                    audio_tmp = os.path.join(save_dir, f"{filename}.audio.m4s")

                    self._log(">>> 下载视频流...")
                    ok = self._download_with_progress(
                        streams["video_url"], video_tmp,
                        "视频流", base_start, base_start + 60
                    )
                    if not ok:
                        return

                    self._log(">>> 下载音频流...")
                    ok = self._download_with_progress(
                        streams["audio_url"], audio_tmp,
                        "音频流", base_start + 60, base_end
                    )
                    if not ok:
                        return

                    # Merge with ffmpeg
                    self._log(">>> 合并音视频...")
                    self._progress(base_end)
                    output_path = os.path.join(save_dir, f"{filename}.mp4")
                    self._merge(video_tmp, audio_tmp, output_path)

                    # Clean up temp files
                    os.remove(video_tmp)
                    os.remove(audio_tmp)
                    self._log(f"    完成: {output_path}")
                else:
                    # Video only (no separate audio)
                    video_tmp = os.path.join(save_dir, f"{filename}.video.m4s")
                    self._log(">>> 下载视频流...")
                    ok = self._download_with_progress(
                        streams["video_url"], video_tmp,
                        "视频流", base_start, base_end
                    )
                    if not ok:
                        return
                    output_path = os.path.join(save_dir, f"{filename}.mp4")
                    os.rename(video_tmp, output_path)
                    self._log(f"    完成: {output_path}")

        self._progress(100)
        self._log("\n>>> 全部下载完成!")

    def _merge(self, video_path, audio_path, output_path):
        """Merge video and audio with ffmpeg."""
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "copy",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"ffmpeg 合并失败:\n{result.stderr}")

    @staticmethod
    def _sanitize_filename(name):
        """Remove characters illegal in filenames."""
        return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("B站视频下载器")
        self.root.geometry("660x500")
        self.root.resizable(False, False)

        self.downloader = None
        self.download_thread = None

        self._build_ui()

    def _build_ui(self):
        # --- URL input ---
        url_frame = ttk.LabelFrame(self.root, text="视频地址", padding=10)
        url_frame.pack(fill="x", padx=15, pady=(15, 5))

        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(url_frame, textvariable=self.url_var, font=("", 12))
        self.url_entry.pack(fill="x")
        self.url_entry.bind("<Return>", lambda e: self._start_download())

        # --- Save path ---
        path_frame = ttk.LabelFrame(self.root, text="保存路径", padding=10)
        path_frame.pack(fill="x", padx=15, pady=5)

        path_row = ttk.Frame(path_frame)
        path_row.pack(fill="x")

        self.path_var = tk.StringVar(value=os.path.expanduser("~/Downloads"))
        self.path_entry = ttk.Entry(path_row, textvariable=self.path_var, font=("", 11))
        self.path_entry.pack(side="left", fill="x", expand=True)

        self.browse_btn = ttk.Button(path_row, text="浏览...", command=self._browse)
        self.browse_btn.pack(side="left", padx=(8, 0))

        # --- Progress bar ---
        progress_frame = ttk.Frame(self.root)
        progress_frame.pack(fill="x", padx=15, pady=(10, 5))

        self.progress = ttk.Progressbar(
            progress_frame, mode="determinate", maximum=100
        )
        self.progress.pack(fill="x")
        self.progress_var = tk.StringVar(value="就绪")
        ttk.Label(progress_frame, textvariable=self.progress_var, anchor="w").pack(
            fill="x", pady=(2, 0)
        )

        # --- Buttons ---
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", padx=15, pady=5)

        self.download_btn = ttk.Button(
            btn_frame, text="开始下载", command=self._start_download
        )
        self.download_btn.pack(side="left", padx=(0, 10))

        self.cancel_btn = ttk.Button(
            btn_frame, text="取消", command=self._cancel_download, state="disabled"
        )
        self.cancel_btn.pack(side="left")

        # --- Log area ---
        log_frame = ttk.LabelFrame(self.root, text="日志", padding=8)
        log_frame.pack(fill="both", expand=True, padx=15, pady=(5, 15))

        self.log_text = tk.Text(
            log_frame,
            height=10,
            font=("Menlo", 10),
            wrap="word",
            state="disabled",
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#d4d4d4",
        )
        self.log_text.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(self.log_text, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=scrollbar.set)

    def _browse(self):
        path = filedialog.askdirectory(initialdir=self.path_var.get())
        if path:
            self.path_var.set(path)

    def _log(self, msg):
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _update_progress(self, pct):
        self.progress["value"] = pct
        self.progress_var.set(f"进度: {pct:.0f}%")

    def _set_ui_state(self, downloading):
        state = "disabled" if downloading else "normal"
        self.url_entry.config(state=state)
        self.browse_btn.config(state=state)
        self.download_btn.config(state=state)
        self.cancel_btn.config(state="normal" if downloading else "disabled")

    def _start_download(self):
        url = self.url_var.get().strip()
        save_dir = self.path_var.get().strip()

        if not url:
            messagebox.showwarning("提示", "请输入视频地址")
            return
        if not save_dir:
            messagebox.showwarning("提示", "请选择保存路径")
            return
        if not os.path.isdir(save_dir):
            messagebox.showwarning("提示", "保存路径不存在")
            return

        # Clear log
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

        self._set_ui_state(True)
        self.progress["value"] = 0
        self.progress_var.set("准备中...")

        self.downloader = BilibiliDownloader(
            progress_callback=self._update_progress,
            log_callback=self._log,
        )

        self.download_thread = threading.Thread(
            target=self._download_task, args=(url, save_dir), daemon=True
        )
        self.download_thread.start()

    def _download_task(self, url, save_dir):
        try:
            self.downloader.download(url, save_dir)
        except Exception as e:
            self._log(f"\n[错误] {e}")
        finally:
            self.root.after(0, self._on_download_done)

    def _on_download_done(self):
        self._set_ui_state(False)
        if self.progress["value"] >= 100:
            self.progress_var.set("完成")
        elif self.progress["value"] > 0:
            self.progress_var.set("已取消")

    def _cancel_download(self):
        if self.downloader:
            self.downloader.cancel()
            self._log("\n>>> 正在取消...")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
