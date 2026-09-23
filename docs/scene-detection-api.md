# 场景分割点检测接口文档

## 1. 接口概述

本服务用于检测视频中的场景分割点。推荐接口传入可下载的视频 URL，服务会下载视频、做场景分割、抽取每个场景的中间帧，并返回 TOS 预签名 URL 列表。

旧接口仍接受已经上传到 TOS 的视频文件路径，输出两个结果文件：

- `*.scenes.txt`：场景区间结果，每行两个整数，格式为 `start_frame end_frame`
- `*.predictions.txt`：逐帧预测分数，每行两个浮点数，格式为 `single_frame_prediction all_frame_prediction`

当前线上部署使用根目录 `app.py` 中的 FastAPI 接口：

- `POST /extract_scene_keyframes`：传入视频 URL，返回每个场景中间帧的 TOS 签名 URL 列表
- `POST /detect_scenes`：传入 TOS 挂载路径，返回场景分割结果文件路径
- `GET /health`

推荐新业务使用 `/extract_scene_keyframes`。调用方只需提供可下载的视频 URL，不必先上传 TOS，也不必持有 TOS AK/SK。

## 2. TOS 上传与挂载路径

部署配置见 `deploy_script/s.yaml`，TOS 挂载关系如下：

| 项目 | 值 |
| --- | --- |
| Region | `cn-beijing` |
| Endpoint | `http://tos-cn-beijing.ivolces.com` |
| Bucket | `dcc-bj-video-cut-inout` |
| BucketPath | `/feishu_movie_output/` |
| 函数内挂载路径 | `/mnt/auto/feishu_movie_output/` |
| 读写权限 | 可读写 |

路径映射规则：

```text
tos://dcc-bj-video-cut-inout/feishu_movie_output/{object_key}
<=>
/mnt/auto/feishu_movie_output/{object_key}
```

调用方上传视频时，应上传到：

```text
tos://dcc-bj-video-cut-inout/feishu_movie_output/{业务目录}/{文件名}
```

调用接口时，`video_path` 传函数内挂载路径：

```text
/mnt/auto/feishu_movie_output/{业务目录}/{文件名}
```

推荐按任务 ID 建目录，避免不同任务结果互相覆盖：

```text
TOS 输入:
tos://dcc-bj-video-cut-inout/feishu_movie_output/scene-detection/{task_id}/input.mp4

接口入参:
/mnt/auto/feishu_movie_output/scene-detection/{task_id}/input.mp4
```

## 3. 从视频 URL 提取场景关键帧

### 请求

```http
POST /extract_scene_keyframes
Content-Type: application/json
```

请求体：

```json
{
  "video_url": "https://example.com/video.mp4",
  "expires": 3600
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `video_url` | string | 是 | 可下载的视频 `http` / `https` URL |
| `expires` | integer | 否 | 签名 URL 有效期，单位秒，默认 `3600` |

内部流程：

1. 下载 `video_url` 到临时目录
2. 用 TransNet 做场景分割
3. 每个场景抽取中间一帧（原分辨率 JPEG）
4. 上传到 TOS：`feishu_movie_output/scene-keyframes/{task_id}/scene_XXXX.jpg`
5. 返回这些图片的预签名 URL 列表

调用方不需要持有 TOS AK/SK；签名由服务端完成。

### 响应

成功响应：

```json
{
  "task_id": "a1b2c3d4e5f64789a1b2c3d4e5f64789",
  "urls": [
    "https://dcc-bj-video-cut-inout.tos-cn-beijing.volces.com/feishu_movie_output/scene-keyframes/.../scene_0001.jpg?X-Tos-Algorithm=...",
    "https://dcc-bj-video-cut-inout.tos-cn-beijing.volces.com/feishu_movie_output/scene-keyframes/.../scene_0002.jpg?X-Tos-Algorithm=..."
  ],
  "scene_count": 2,
  "scenes": [
    {
      "start_frame": 0,
      "end_frame": 120,
      "frame_index": 60,
      "url": "https://..."
    },
    {
      "start_frame": 121,
      "end_frame": 350,
      "frame_index": 235,
      "url": "https://..."
    }
  ]
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string | 本次任务 ID，也是 TOS 对象目录名 |
| `urls` | string[] | 每个场景一张中间帧的签名 URL，顺序与场景顺序一致 |
| `scene_count` | integer | 场景数量 |
| `scenes` | object[] | 每个场景的帧区间、抽帧位置和对应签名 URL |

### 调用示例

```bash
curl -X POST "${API_BASE_URL}/extract_scene_keyframes" \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "https://example.com/video.mp4"
  }'
```

## 4. 场景分割点检测

### 请求

```http
POST /detect_scenes
Content-Type: application/json
```

请求体：

```json
{
  "video_path": "/mnt/auto/feishu_movie_output/scene-detection/20260708-0001/input.mp4"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `video_path` | string | 是 | 视频在函数内的绝对路径，必须位于 `OUT_ROOT` 配置的挂载目录下 |

当前部署中 `OUT_ROOT` 为：

```text
/mnt/auto/feishu_movie_output/
```

### 响应

成功响应：

```json
{
  "scenes_path": "/mnt/auto/feishu_movie_output/scene-detection/20260708-0001/input.mp4.scenes.txt",
  "predictions_path": "/mnt/auto/feishu_movie_output/scene-detection/20260708-0001/input.mp4.predictions.txt",
  "scene_count": 12
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `scenes_path` | string | 场景分割结果文件的函数内路径 |
| `predictions_path` | string | 预测分数文件的函数内路径 |
| `scene_count` | integer | 检测出的场景数量 |

接口具有幂等特性：如果 `scenes_path` 和 `predictions_path` 已经存在，服务会直接返回已有结果，不会重复处理视频。

## 5. 结果下载

检测结果写回到输入视频同目录下，文件名为：

```text
{原视频文件名}.scenes.txt
{原视频文件名}.predictions.txt
```

以上面的请求为例，结果在函数内路径为：

```text
/mnt/auto/feishu_movie_output/scene-detection/20260708-0001/input.mp4.scenes.txt
/mnt/auto/feishu_movie_output/scene-detection/20260708-0001/input.mp4.predictions.txt
```

对应的 TOS 下载地址为：

```text
tos://dcc-bj-video-cut-inout/feishu_movie_output/scene-detection/20260708-0001/input.mp4.scenes.txt
tos://dcc-bj-video-cut-inout/feishu_movie_output/scene-detection/20260708-0001/input.mp4.predictions.txt
```

调用方可通过 TOS 控制台、TOS SDK、内部文件服务或预签名 URL 下载结果文件。

## 6. 结果文件格式

### scenes.txt

每行表示一个场景片段，两个数字分别为起始帧和结束帧，帧号从 `0` 开始。

示例：

```text
0 120
121 350
351 548
```

含义：

| 行 | start_frame | end_frame |
| --- | --- | --- |
| 1 | `0` | `120` |
| 2 | `121` | `350` |
| 3 | `351` | `548` |

如果只需要“分割点”，通常取相邻场景的边界：

```text
第 1 个分割点: 120 / 121
第 2 个分割点: 350 / 351
```

### predictions.txt

每行表示一帧的预测分数，两个数字分别为：

```text
single_frame_prediction all_frame_prediction
```

示例：

```text
0.002341 0.001927
0.003112 0.002804
0.876420 0.812991
```

业务方通常只需要消费 `*.scenes.txt`；`*.predictions.txt` 更适合用于调试、阈值分析或可视化。

## 7. 健康检查

### 请求

```http
GET /health
```

### 响应

```json
{
  "status": "healthy",
  "model_loaded": true
}
```

## 8. 调用示例

### 处理视频

```bash
curl -X POST "${API_BASE_URL}/detect_scenes" \
  -H "Content-Type: application/json" \
  -d '{
    "video_path": "/mnt/auto/feishu_movie_output/scene-detection/20260708-0001/input.mp4"
  }'
```

### 下载结果

把接口返回的函数内路径转换为 TOS 对象路径：

```text
/mnt/auto/feishu_movie_output/scene-detection/20260708-0001/input.mp4.scenes.txt
```

转换为：

```text
tos://dcc-bj-video-cut-inout/feishu_movie_output/scene-detection/20260708-0001/input.mp4.scenes.txt
```

然后使用业务系统已有的 TOS 下载方式下载。

## 9. 常见错误

| HTTP 状态码 | 场景 | 示例信息 |
| --- | --- | --- |
| `400` | `video_url` 不是 http/https | `video_url 必须是 http/https URL` |
| `400` | 视频下载失败或文件过大 | `下载视频失败: ...` / `视频文件过大...` |
| `400` | `video_path` 不在挂载根目录下 | `挂载路径不一致，期望: /mnt/auto/feishu_movie_output/，实际: ...` |
| `400` | `video_path` 指向目录而不是文件 | `路径不是文件: ...` |
| `404` | 视频文件不存在 | `视频文件不存在: ...` |
| `500` | 未配置 TOS AK/SK | `未配置 TOS_ACCESS_KEY / TOS_SECRET_KEY，无法签名` |
| `500` | `OUT_ROOT` 未配置 | `OUT_ROOT 环境变量未配置` |
| `500` | 视频解码、模型推理、抽帧或写结果失败 | `处理视频时出错: ...` / `提取关键帧时出错: ...` |

## 10. 对接注意事项

- 新接口 `/extract_scene_keyframes` 只需传视频 URL；调用方不必持有 TOS AK/SK，签名由服务端完成。
- 函数需要能访问该 URL（当前部署开启了共享公网），并已配置 `TOS_ACCESS_KEY` / `TOS_SECRET_KEY`。
- 旧接口 `/detect_scenes` 仍要求视频先上传到 `dcc-bj-video-cut-inout/feishu_movie_output/`。
- 旧接口的 `video_path` 传的是函数内路径，不是 `tos://` 地址，也不是公网 URL。
- 旧接口检测结果会写到输入视频同目录；调用方需要具备对应 TOS 路径的读取权限。
- 同名视频重复调用 `/detect_scenes` 会复用已有的 `*.scenes.txt` 和 `*.predictions.txt`。
- 如需强制重新处理旧接口结果，应先删除旧结果文件，或使用新的任务目录/新文件名。
