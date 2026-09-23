import os
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from inference.transnetv2 import TransNetV2
from scene_keyframe import KeyframeError, process_video_url
import numpy as np

app = FastAPI(title="视频场景分割服务", version="1.0.0")

# 全局加载模型（避免每次请求重复加载）
model = None


def get_model():
    global model
    if model is None:
        model = TransNetV2()
    return model


class VideoRequest(BaseModel):
    video_path: str


class SceneResponse(BaseModel):
    scenes_path: str
    predictions_path: str
    scene_count: int


class KeyframeRequest(BaseModel):
    video_url: str = Field(..., description="可下载的视频 http/https URL")
    expires: Optional[int] = Field(None, description="签名 URL 有效期，单位秒，默认 3600")


class SceneKeyframeItem(BaseModel):
    start_frame: int
    end_frame: int
    frame_index: int
    url: str


class KeyframeResponse(BaseModel):
    task_id: str
    urls: List[str]
    scene_count: int
    scenes: List[SceneKeyframeItem]


@app.on_event("startup")
async def startup_event():
    """服务启动时预加载模型"""
    get_model()
    print("[App] TransNetV2 模型已加载")


@app.post("/detect_scenes", response_model=SceneResponse)
async def detect_scenes(request: VideoRequest):
    """
    检测视频场景切换点
    
    - **video_path**: 视频文件的绝对路径
    - 返回: scenes.txt 和 predictions.txt 的路径
    """
    video_path = request.video_path

    out_root = os.getenv("OUT_ROOT")
    if not out_root:
        raise HTTPException(status_code=500, detail="OUT_ROOT 环境变量未配置")

    def _norm_path_for_prefix(p: str) -> str:
        p = (p or "").strip().replace("\\", "/")
        while "//" in p:
            p = p.replace("//", "/")
        return p.rstrip("/")

    expected_root = _norm_path_for_prefix(out_root)
    actual_path = _norm_path_for_prefix(video_path)
    if actual_path != expected_root and not actual_path.startswith(expected_root + "/"):
        raise HTTPException(
            status_code=400,
            detail=f"挂载路径不一致，期望: {out_root.strip()}，实际: {video_path}"
        )
    
    # 检查视频文件是否存在
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail=f"视频文件不存在: {video_path}")
    
    if not os.path.isfile(video_path):
        raise HTTPException(status_code=400, detail=f"路径不是文件: {video_path}")
    
    # 输出文件路径
    predictions_path = video_path + ".predictions.txt"
    scenes_path = video_path + ".scenes.txt"
    
    # 如果结果已存在，直接返回
    if os.path.exists(predictions_path) and os.path.exists(scenes_path):
        scene_count = len(np.loadtxt(scenes_path, dtype=np.int32, ndmin=2))
        return SceneResponse(
            scenes_path=scenes_path,
            predictions_path=predictions_path,
            scene_count=scene_count
        )
    
    try:
        # 获取模型并进行预测
        transnet = get_model()
        video_frames, single_frame_predictions, all_frame_predictions = transnet.predict_video(video_path)
        
        # 保存预测结果
        predictions = np.stack([single_frame_predictions, all_frame_predictions], 1)
        np.savetxt(predictions_path, predictions, fmt="%.6f")
        
        # 保存场景切分结果
        scenes = transnet.predictions_to_scenes(single_frame_predictions)
        np.savetxt(scenes_path, scenes, fmt="%d")
        
        return SceneResponse(
            scenes_path=scenes_path,
            predictions_path=predictions_path,
            scene_count=len(scenes)
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理视频时出错: {str(e)}")


@app.post("/extract_scene_keyframes", response_model=KeyframeResponse)
def extract_scene_keyframes(request: KeyframeRequest):
    """
    从视频 URL 提取每个场景的中间关键帧，并返回 TOS 签名 URL 列表。

    流程：下载视频 -> TransNet 场景分割 -> 每场景抽中间帧 -> 上传 TOS -> 签名。
    """
    try:
        result = process_video_url(
            request.video_url,
            get_model(),
            expires=request.expires,
        )
        return KeyframeResponse(**result)
    except KeyframeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"提取关键帧时出错: {str(exc)}")


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "healthy", "model_loaded": model is not None}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

