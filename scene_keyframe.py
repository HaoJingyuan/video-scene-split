import os
import shutil
import tempfile
import uuid
from typing import List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import ffmpeg
import requests

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mpeg", ".mpg"}
DEFAULT_MAX_BYTES = 3 * 1024 * 1024 * 1024
DEFAULT_SIGN_EXPIRES = 3600


class KeyframeError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _norm_prefix(value: str) -> str:
    return (value or "").strip().strip("/")


def guess_video_ext(video_url: str) -> str:
    path = urlparse(video_url).path
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXTENSIONS:
        return ext
    return ".mp4"


def validate_video_url(video_url: str) -> str:
    url = (video_url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise KeyframeError("video_url 必须是 http/https URL", status_code=400)
    return url


def download_video(
    video_url: str,
    dest_path: str,
    timeout: Tuple[int, int] = (15, 300),
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> None:
    try:
        with requests.get(
            video_url,
            stream=True,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": "video-scene-split/1.0"},
        ) as resp:
            resp.raise_for_status()
            written = 0
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > max_bytes:
                        raise KeyframeError(
                            f"视频文件过大，超过 {max_bytes} 字节限制",
                            status_code=400,
                        )
                    f.write(chunk)
            if written <= 0:
                raise KeyframeError("下载的视频文件为空", status_code=400)
    except KeyframeError:
        raise
    except requests.RequestException as exc:
        raise KeyframeError(f"下载视频失败: {exc}", status_code=400) from exc


def scene_mid_frames(scenes) -> List[int]:
    mid_frames = []
    for start, end in scenes:
        start_i = int(start)
        end_i = int(end)
        if end_i < start_i:
            start_i, end_i = end_i, start_i
        mid_frames.append((start_i + end_i) // 2)
    return mid_frames


def _extract_selected_frames(video_path: str, frame_indices: Sequence[int], output_dir: str) -> List[str]:
    if not frame_indices:
        return []

    pattern = os.path.join(output_dir, "kf_%04d.jpg")
    select_expr = "+".join(f"eq(n,{idx})" for idx in frame_indices)
    (
        ffmpeg.input(video_path)
        .filter("select", select_expr)
        .output(pattern, vsync=0, **{"qscale:v": 2})
        .overwrite_output()
        .run(capture_stdout=True, capture_stderr=True)
    )

    extracted = [
        os.path.join(output_dir, name)
        for name in sorted(os.listdir(output_dir))
        if name.startswith("kf_") and name.endswith(".jpg")
    ]
    if len(extracted) != len(frame_indices):
        raise KeyframeError(
            f"抽帧数量与场景数不一致，期望 {len(frame_indices)}，实际 {len(extracted)}",
            status_code=500,
        )
    return extracted


def _extract_one_frame(video_path: str, frame_index: int, output_path: str) -> None:
    (
        ffmpeg.input(video_path)
        .filter("select", f"eq(n,{frame_index})")
        .output(output_path, vframes=1, vsync=0, **{"qscale:v": 2})
        .overwrite_output()
        .run(capture_stdout=True, capture_stderr=True)
    )
    if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 0:
        raise KeyframeError(f"抽帧失败: frame={frame_index}", status_code=500)


def extract_scene_keyframes(video_path: str, frame_indices: Sequence[int], output_dir: str) -> List[str]:
    os.makedirs(output_dir, exist_ok=True)
    unique_indices = list(dict.fromkeys(frame_indices))
    extract_dir = os.path.join(output_dir, "_raw")
    os.makedirs(extract_dir, exist_ok=True)

    try:
        extracted = _extract_selected_frames(video_path, unique_indices, extract_dir)
    except ffmpeg.Error:
        extracted = []
        for idx in unique_indices:
            raw_path = os.path.join(extract_dir, f"kf_{idx:08d}.jpg")
            _extract_one_frame(video_path, idx, raw_path)
            extracted.append(raw_path)

    index_to_file = dict(zip(unique_indices, extracted))
    output_paths = []
    for i, frame_index in enumerate(frame_indices, start=1):
        dest = os.path.join(output_dir, f"scene_{i:04d}.jpg")
        src = index_to_file[frame_index]
        if os.path.abspath(src) != os.path.abspath(dest):
            shutil.copy2(src, dest)
        output_paths.append(dest)
    shutil.rmtree(extract_dir, ignore_errors=True)
    return output_paths


def _tos_client(endpoint: Optional[str] = None):
    try:
        import tos
    except ImportError as exc:
        raise KeyframeError("未安装 tos SDK，无法上传或签名", status_code=500) from exc

    ak = os.getenv("TOS_ACCESS_KEY") or os.getenv("TOS_ACCESS_KEY_ID")
    sk = os.getenv("TOS_SECRET_KEY") or os.getenv("TOS_SECRET_ACCESS_KEY")
    endpoint = endpoint or os.getenv("TOS_ENDPOINT", "tos-cn-beijing.volces.com")
    region = os.getenv("TOS_REGION", "cn-beijing")
    if not ak or not sk:
        raise KeyframeError("未配置 TOS_ACCESS_KEY / TOS_SECRET_KEY，无法签名", status_code=500)
    return tos.TosClientV2(ak, sk, endpoint, region)


def _tos_http_method_get():
    import tos
    if hasattr(tos, "HttpMethodType"):
        return tos.HttpMethodType.Http_Method_Get
    from tos.enum import HttpMethodType
    return HttpMethodType.Http_Method_Get


def upload_and_sign(local_paths: Sequence[str], object_keys: Sequence[str], expires: int) -> List[str]:
    bucket = os.getenv("TOS_BUCKET", "dcc-bj-video-cut-inout")
    put_client = _tos_client()
    sign_endpoint = os.getenv("TOS_SIGN_ENDPOINT")
    sign_client = _tos_client(sign_endpoint) if sign_endpoint else put_client
    method = _tos_http_method_get()
    urls = []
    try:
        for local_path, object_key in zip(local_paths, object_keys):
            try:
                put_client.put_object_from_file(
                    bucket,
                    object_key,
                    local_path,
                    content_type="image/jpeg",
                )
            except TypeError:
                put_client.put_object_from_file(bucket, object_key, local_path)
            signed = sign_client.pre_signed_url(method, bucket, object_key, expires=expires)
            urls.append(signed.signed_url)
    except KeyframeError:
        raise
    except Exception as exc:
        raise KeyframeError(f"TOS 上传或签名失败: {exc}", status_code=500) from exc
    return urls


def build_object_key(task_id: str, filename: str) -> str:
    prefix = _norm_prefix(os.getenv("TOS_KEY_PREFIX", "feishu_movie_output"))
    return f"{prefix}/scene-keyframes/{task_id}/{filename}"


def process_video_url(
    video_url: str,
    transnet,
    expires: Optional[int] = None,
) -> dict:
    url = validate_video_url(video_url)
    if expires is None:
        expires = int(os.getenv("TOS_SIGN_EXPIRES", str(DEFAULT_SIGN_EXPIRES)))
    if expires <= 0:
        raise KeyframeError("expires 必须大于 0", status_code=400)

    task_id = uuid.uuid4().hex
    work_dir = tempfile.mkdtemp(prefix=f"scene_keyframes_{task_id}_")

    try:
        video_path = os.path.join(work_dir, f"input{guess_video_ext(url)}")
        print(f"[Keyframe] 下载视频 task_id={task_id} work_dir={work_dir} url={url}")
        download_video(url, video_path)

        print(f"[Keyframe] TransNet 推理 task_id={task_id}")
        _, single_frame_predictions, _ = transnet.predict_video(video_path)
        scenes = transnet.predictions_to_scenes(single_frame_predictions)
        mid_frames = scene_mid_frames(scenes)

        frame_dir = os.path.join(work_dir, "frames")
        print(f"[Keyframe] 抽取 {len(mid_frames)} 张场景中间帧 task_id={task_id}")
        local_paths = extract_scene_keyframes(video_path, mid_frames, frame_dir)

        object_keys = [
            build_object_key(task_id, os.path.basename(path)) for path in local_paths
        ]
        urls = upload_and_sign(local_paths, object_keys, expires)

        return {
            "task_id": task_id,
            "urls": urls,
            "scene_count": len(urls),
            "scenes": [
                {
                    "start_frame": int(start),
                    "end_frame": int(end),
                    "frame_index": mid,
                    "url": signed_url,
                }
                for (start, end), mid, signed_url in zip(scenes, mid_frames, urls)
            ],
        }
    except KeyframeError:
        raise
    except ffmpeg.Error as exc:
        stderr = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else str(exc)
        raise KeyframeError(f"ffmpeg 处理失败: {stderr[-500:]}", status_code=500) from exc
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
