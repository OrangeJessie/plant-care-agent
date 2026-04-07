# 图片传输模式说明

`/image` 命令支持四种图片传输策略，适应不同网络环境和图片大小。

---

## 快速选择

| 场景 | 推荐模式 |
|---|---|
| 图片在本机、Agent 也在本机 | `path`（默认）|
| 图片小（< 1 MB）或局域网 | `base64` |
| 图片大或跨网络、需永久访问 | `multipart` |
| 图片已有公网 URL | `url` |

---

## 模式详解

### path（默认）

将本地路径以文本形式传给 Agent，由 Agent 调用 `plant_image_analyzer` 工具读取文件。

**适用**：Agent 与图片在同一台机器。

```bash
/image ~/Desktop/rose.jpg 叶子发黄是什么原因？
# 等价于：
/image --mode path ~/Desktop/rose.jpg 叶子发黄是什么原因？
```

发送的消息内容示例：
```
叶子发黄是什么原因？
请调用 plant_image_analyzer 工具，image_path 参数为：/Users/xxx/Desktop/rose.jpg
```

---

### base64

在客户端将图片压缩后 Base64 编码，直接嵌入多模态消息的 `content` 列表中。

**适用**：小图（压缩后 < 500 KB）、局域网、不想搭文件服务。

```bash
/image --mode base64 ~/Desktop/rose.jpg 请诊断
# 自定义压缩参数：
/image --mode base64 --maxpx 800 --quality 70 rose.jpg
```

压缩效果（参考）：

| 原图大小 | 压缩后（1024px / quality 75） | Base64 后 |
|---|---|---|
| 3 MB（手机拍摄） | ~150 KB | ~200 KB |
| 1 MB | ~80 KB | ~110 KB |

发送的消息内容（简化示意）：
```json
[
  {"type": "text", "text": "请诊断"},
  {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/..."}}
]
```

> **提示**：安装 Pillow 可启用压缩，否则直接编码原图。
> ```bash
> pip install Pillow
> ```

---

### multipart

将图片压缩后以 `multipart/form-data` 二进制上传到 NAT 的 `/static/` 端点，消息里只传返回的 URL。

**适用**：大图、外网访问、需要模型远程拉取图片。

```bash
/image --mode multipart ~/Desktop/large.jpg 这株植物状态如何？
# 自定义压缩参数：
/image --mode multipart --maxpx 1024 --quality 75 large.jpg
```

上传流程：
```
客户端压缩图片
  → PUT {NAT_CHAT_URL 的 scheme://host:port}/static/plant_images/large_a1b2c3d4.jpg
  → 消息内容: {"type": "image_url", "image_url": {"url": "http://<公网地址>/static/plant_images/..."}}
  → Agent 调用 plant_image_analyzer，工具将 URL 按 internal_base_url 重写后下载
  → 转成 Base64 data URL 交给视觉模型
```

> **云服务器注意**：客户端使用公网地址上传（如 `http://1.2.3.4:9058`），但 Agent 工具在服务器内部
> 需通过内网端口（如 `http://localhost:9000`）下载图片，否则 hairpin NAT 可能导致超时。
> 需在 `config.yml` 中配置 `internal_base_url`，见下方。

**前置条件**：需在 `config.yml` 中启用 object store 并配置内部下载地址：

```yaml
general:
  front_end:
    _type: fastapi
    object_store: plant_image_store

object_stores:
  plant_image_store:
    _type: in_memory   # 进程重启后清空；持久化见下方

functions:
  plant_image_analyzer:
    _type: plant_image_analyzer
    vision_llm_name: vision_llm
    internal_base_url: "http://localhost:9000"  # 工具下载图片时使用的内部地址
                                                # 留空则直接使用客户端传入的公网 URL
```

持久化存储（可选）：

```yaml
# S3 / MinIO（需安装 nvidia_nat_s3）
object_stores:
  plant_image_store:
    _type: s3
    endpoint_url: http://localhost:9000
    access_key: minioadmin
    secret_key: minioadmin
    bucket_name: plant-images

# Redis（需安装 nvidia_nat_redis）
object_stores:
  plant_image_store:
    _type: redis
    host: localhost
    port: 6379
    db: 0
    bucket_name: plant-images
```

---

### url

直接将 `http/https` 图片链接嵌入多模态消息，不上传任何文件。

**适用**：图片已有公网 URL（如图床、CDN）。

```bash
/image --mode url https://example.com/plant.jpg 这株植物叶片是否健康？
```

---

## 全局默认配置

通过环境变量设置默认行为，避免每次都输入 `--mode`：

```bash
# 修改默认传输模式
export NAT_IMAGE_MODE=multipart   # path | base64 | multipart | url

# 压缩参数（base64 / multipart 模式生效）
export NAT_IMAGE_MAXPX=1024       # 长边最大像素，默认 1024
export NAT_IMAGE_QUALITY=75       # JPEG 质量 1-95，默认 75

# 图片分析超时（视觉模型推理较慢，独立于普通对话超时）
export NAT_IMAGE_TIMEOUT=1800     # 默认 1800s（30 分钟）；普通对话用 NAT_CHAT_TIMEOUT=600
```

设置后直接使用，无需 `--mode`：
```bash
/image ~/Desktop/rose.jpg 叶子发黄
```

---

## 测试步骤

### 1. 验证 NAT 静态文件路由

```bash
# 启动服务
nat serve --config_file src/plant_care_agent/configs/config.yml

# 健康检查
curl -s http://localhost:8000/health

# 手动上传测试（期望返回 {"filename": "plant_images/test.jpg"}）
curl -X PUT http://localhost:8000/static/plant_images/test.jpg \
  -F "file=@/path/to/any.jpg"

# 验证可访问
curl -I http://localhost:8000/static/plant_images/test.jpg
# 期望: HTTP/1.1 200 OK
```

### 2. 测试 base64 模式

```bash
python scripts/claude_style_chat.py
```

输入：
```
/image --mode base64 ~/Desktop/rose.jpg 请诊断叶片状态
```

终端应显示：
```
base64 模式: rose.jpg  3072 KB → 142 KB
```

### 3. 测试 multipart 模式（全局默认）

```bash
export NAT_IMAGE_MODE=multipart
python scripts/claude_style_chat.py
```

输入（不加 `--mode`，使用全局默认）：
```
/image ~/Desktop/rose.jpg 请诊断
```

终端应显示：
```
multipart 模式: rose.jpg → http://localhost:8000/static/plant_images/
已上传: http://localhost:8000/static/plant_images/rose_a1b2c3d4.jpg
```

### 4. 测试 url 模式

```
/image --mode url https://upload.wikimedia.org/wikipedia/commons/thumb/4/41/Sunflower_from_Silesia2.jpg/800px-Sunflower_from_Silesia2.jpg 这是什么植物？
```

---

## 常见问题

| 现象 | 原因 | 解决方案 |
|---|---|---|
| 客户端 `TimeoutError: timed out`，服务端正常完成 | 视觉模型推理时间超过客户端 socket 超时（默认 600s） | `export NAT_IMAGE_TIMEOUT=1800`（客户端已对多模态请求自动使用此值） |
| `上传失败: HTTP 404` | NAT 未启用 object_store | 确认 `config.yml` 已添加 `general.front_end.object_store` |
| `上传失败: HTTP 422` | multipart 字段名错误 | 代码已正确使用 `name="file"`，检查 NAT 版本 |
| 上传成功，工具报"图片文件不存在" | `plant_image_analyzer` 旧版不支持 HTTP URL | 确认已更新工具代码（现支持 `http://`、`https://`、本地路径、base64） |
| 工具报 `图片下载失败: timed out` | 同步 `urllib` 阻塞了 asyncio 事件循环 | 确认已更新工具代码（已改为 `await asyncio.to_thread(...)` 非阻塞下载） |
| 工具用内网地址仍下载超时 | `internal_base_url` 端口配置有误 | 用 `curl http://localhost:<端口>/health` 确认 NAT 实际监听端口后修改 `config.yml` |
| 公网上传成功但工具下载失败（连接拒绝/超时） | 云服务器 hairpin NAT 不通，工具无法访问自己的公网 IP | 在 `config.yml` 的 `plant_image_analyzer` 下设置 `internal_base_url: "http://localhost:<内部端口>"` |
| `'list' object has no attribute 'strip'` | NAT 防御中间件或旧版 `plant_memory_wrapper` 未处理多模态 list content | 更新 NAT 框架三个 defense_middleware 文件；或将部署代码同步至本地最新版 |
| `Pillow 未安装` 警告 | 图片未压缩，体积较大 | `pip install Pillow` 后重启客户端 |
| base64 超时 | 原图过大且未安装 Pillow | 安装 Pillow 或改用 multipart 模式 |
