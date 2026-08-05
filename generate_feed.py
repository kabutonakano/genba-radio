"""
現場ラジオ Podcast RSS生成スクリプト（ローカル実行用）

やること:
  1. feed_config.json の設定と、episodes_script/*.json + script_latest.json のエピソード情報を集める
  2. episodes/episode_NNN.mp3 が実際に存在する回だけを対象に、Podcast形式のRSS（feed.xml）を作る
  3. feed.xml と episodes/*.mp3 を GitHub Pages で公開している前提で、
     https://{github_user}.github.io/{repo_name}/... のURLをenclosureに埋め込む

事前条件:
  - build_episode.py がすでに episodes/episode_NNN.mp3 を作っていること（ffmpeg必須）
  - feed_config.json の github_user / repo_name を自分のものに書き換えてあること
  - このリポジトリをGitHubにpushし、Settings > Pages で公開していること
     （Source: Deploy from a branch, Branch: main, Folder: / (root) を推奨）

使い方:
  python generate_feed.py
  → feed.xml が更新される。あとは git add / commit / push すれば配信に反映される。
"""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "feed_config.json"
EPISODES_SCRIPT_DIR = BASE_DIR / "episodes_script"
LATEST_SCRIPT_PATH = BASE_DIR / "script_latest.json"
AUDIO_EPISODES_DIR = BASE_DIR / "episodes"
FEED_OUT = BASE_DIR / "feed.xml"


def load_config():
    if not CONFIG_PATH.exists():
        raise SystemExit(f"エラー: {CONFIG_PATH} が見つかりません。先に作成してください。")
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if cfg.get("github_user") in (None, "", "YOUR_GITHUB_USERNAME"):
        raise SystemExit("エラー: feed_config.json の github_user を自分のGitHubユーザー名に書き換えてください。")
    return cfg


def collect_episode_metadata():
    """script_latest.json と episodes_script/*.json から、エピソード番号ごとの台本データを集める。"""
    episodes = {}

    if LATEST_SCRIPT_PATH.exists():
        data = json.loads(LATEST_SCRIPT_PATH.read_text(encoding="utf-8"))
        no = data.get("episode")
        if no is not None:
            episodes[int(no)] = data

    if EPISODES_SCRIPT_DIR.exists():
        for p in EPISODES_SCRIPT_DIR.glob("episode_*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            no = data.get("episode")
            if no is not None:
                episodes.setdefault(int(no), data)

    return episodes


def get_mp3_duration_seconds(path):
    """ffprobeがあれば秒数を取る。なければNone（itunes:durationは省略）。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


def format_duration(seconds):
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def build_item_xml(episode_no, data, mp3_path, base_url):
    title = escape(data.get("title", f"現場ラジオ 第{episode_no}回"))
    subtitle = escape(data.get("subtitle", ""))
    date_str = data.get("date")
    try:
        pub_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=6, minute=0, second=0, tzinfo=timezone(timedelta_hours(9))
        )
    except Exception:
        pub_dt = datetime.now(timezone.utc)
    pub_date = pub_dt.strftime("%a, %d %b %Y %H:%M:%S %z")

    file_size = mp3_path.stat().st_size
    mp3_url = f"{base_url}/episodes/{mp3_path.name}"
    guid = f"{base_url}/episodes/{mp3_path.name}"

    duration_tag = ""
    dur = get_mp3_duration_seconds(mp3_path)
    if dur:
        duration_tag = f"      <itunes:duration>{format_duration(dur)}</itunes:duration>\n"

    return f"""    <item>
      <title>{title}</title>
      <description>{subtitle}</description>
      <pubDate>{pub_date}</pubDate>
      <enclosure url="{escape(mp3_url)}" length="{file_size}" type="audio/mpeg" />
      <guid isPermaLink="false">{escape(guid)}</guid>
{duration_tag}    </item>"""


def timedelta_hours(h):
    from datetime import timedelta
    return timedelta(hours=h)


def main():
    cfg = load_config()
    base_url = f"https://{cfg['github_user']}.github.io/{cfg['repo_name']}"

    episodes = collect_episode_metadata()
    if not AUDIO_EPISODES_DIR.exists():
        raise SystemExit(
            "エラー: episodes/ フォルダが見つかりません。先に build_episode.py を実行して"
            "（ffmpegが使える状態で）episode_NNN.mp3 を作ってください。"
        )

    items_xml = []
    used_count = 0
    for episode_no in sorted(episodes.keys(), reverse=True):
        mp3_path = AUDIO_EPISODES_DIR / f"episode_{episode_no:03d}.mp3"
        if not mp3_path.exists():
            print(f"スキップ: 第{episode_no}回のmp3が見つかりません（{mp3_path.name}）")
            continue
        items_xml.append(build_item_xml(episode_no, episodes[episode_no], mp3_path, base_url))
        used_count += 1

    if used_count == 0:
        print("警告: 配信できるエピソードが1本もありません。episodes/episode_NNN.mp3 を確認してください。")

    image_tag = ""
    if cfg.get("podcast_image_url"):
        image_tag = f'    <itunes:image href="{escape(cfg["podcast_image_url"])}" />\n'

    feed_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{escape(cfg['podcast_title'])}</title>
    <link>{escape(base_url)}</link>
    <language>{escape(cfg['podcast_language'])}</language>
    <description>{escape(cfg['podcast_description'])}</description>
    <itunes:author>{escape(cfg['podcast_author'])}</itunes:author>
    <itunes:owner>
      <itunes:name>{escape(cfg['podcast_author'])}</itunes:name>
      <itunes:email>{escape(cfg.get('podcast_email', ''))}</itunes:email>
    </itunes:owner>
    <itunes:explicit>false</itunes:explicit>
{image_tag}{chr(10).join(items_xml)}
  </channel>
</rss>
"""

    FEED_OUT.write_text(feed_xml, encoding="utf-8")
    print(f"完了: {FEED_OUT} を更新しました（配信エピソード数: {used_count}）")
    print(f"配信ベースURL: {base_url}")
    print("この後 git add / commit / push すれば、GitHub Pages側に反映されます。")


if __name__ == "__main__":
    main()
