# 微信灵感整理（wechat-inspiration）设计文档

- 日期：2026-09-26
- 作者：（略）
- 状态：已通过设计评审，待写实现计划

## 1. 目标与背景

用户长期把「灵感」和「工具类信息」以截图、文字、文档、链接的形式发到**微信「文件传输助手」**，日积月累无法检索、无法复用。本项目做一个**本地运行**的整理系统：自动汇总这些内容，去重、识别、分类、打标签，提供网页界面浏览、搜索、沉淀。

### 成功标准
- 用户能在一个界面里按「灵感 / 工具 / 标签」浏览与全文搜索所有内容。
- 同一工具多次出现自动合并为一张卡片（名称、官网、用途、来源截图）。
- 相关灵感可聚合并由 AI 归纳为内容选题 / 素材。
- 垃圾内容（付款、闲聊、验证码等）自动识别、不入库，但可复核。
- 增量运行：重复启动只处理新增内容，不重复消耗 AI 费用。
- 原始文件只读，绝不修改或删除微信目录内任何文件。

### 非目标
- 不做微信数据库解密（用户已有工具箱 `<你的微信导出工具>` 负责）。
- 不纳入全部 128k 私聊记录（那是另一个项目的语料）。
- 不做手机端 App / 云服务；纯本机 + 浏览器。

## 2. 关键事实（已实测确认，2026-09-26）

- 微信版本 4.1.15.9（新版，4.x）。
- 用户已有解密工具箱 `<导出工具目录>/`：
  - `wxsnap.py` 从进程内存提取 SQLCipher 密钥，把数据库解密到 `plain/db_storage/`（**明文库已在硬盘**）。
  - `export_private.py` 导出私聊为可读 txt 到 `export_private/`（时间 谁: 内容）。
  - `secrets.json` 内含 `DEEPSEEK_API_KEY`；配置用 `deepseek-chat`，端点 `https://api.deepseek.com/v1/chat/completions`。
- 「文件传输助手」聊天：`export_private/文件传输助手_helper.txt`，1667 条，全部自己发送；含 385 个 `[图片]` 占位、149 行 http 链接、少量语音/视频。
- 文件传输助手图片实体在 `C:\Users\<用户名>\xwechat_files\<wxid>\msg\attach\<文件传输助手md5>\<月份>\...\Img\*.dat`：
  - **202 张**（2024-08 ~ 2025-07）：老格式，单字节 XOR，本项目可直接还原（已用 Pillow 验证 202 张全部有效，PNG 84 / JPEG 118）。
  - **332 张**（2025-08 ~ 至今，含最活跃的 2026-07/08）：新版 V2 格式，magic `07 08 56 32`，AES-128 加密，每设备独立密钥，**需从内存取图片密钥**；固定测试密钥 `cfcd208495d565ef` 已验证无效；密钥不在已解密数据库中。
- 微信文档：`...\msg\file\` 下 747 个（PDF/Word/Excel/PPT/md/txt 等），所有会话混存，无法区分来源（不破解不影响本项目）。

## 3. 数据来源与接入方式

| 来源 | 接入方式 | 谁负责 |
|---|---|---|
| 文字（文件传输助手 + 用户指定联系人） | 读 `export_private/*.txt`（用户 refresh 后重跑 export 脚本刷新） | 用户刷新，程序读取 |
| 老截图 202 张 | XOR 解码 `.dat` → 缓存为 png/jpg | 程序 |
| 新截图 332 张 | 用户运行「导图」步骤（见 §7）解出到明文文件夹 → 程序读取 | 用户运行一次，程序读取 |
| 微信文档 747 个 | 直接读 `msg\file\`，提取文本 | 程序 |
| 手机相册补充截图 | 用户拷入 `inbox/album/` 文件夹 | 用户拖入，程序读取 |

- 灵感来源默认**只算文件传输助手**；用户可在 `config.json` 的 `sources.contacts` 里加入其它联系人 txt。
- 所有输入视为只读；程序自己的缓存/数据库写在项目目录内。

## 4. 处理流程（Pipeline）

```
汇集(collect)
  → 去重(dedup)：文件 SHA-256 精确去重 + 感知哈希(pHash)近似图去重
  → 提取(extract)：图片走本地 OCR(RapidOCR, 中文)；文档抽取正文文本
  → 关联(link)：截图按时间戳对齐同会话前后文字，作为上下文
  → 判定(classify)：DeepSeek 判 类型∈{灵感,工具,垃圾} + 标题/摘要/标签[]/工具名/官网链接
        · 垃圾 → 只写指纹表(fingerprints)，不入内容库，下次跳过
        · 灵感/工具 → 写内容库(items)
  → 沉淀(index)：写入 SQLite + FTS5 全文索引
```

- **增量**：每个原子输入以稳定指纹（文件哈希 / 消息 (会话,时间戳,类型) 组合键）标识；已处理集合持久化，重复运行只处理新增。
- **成本控制**：OCR 本地免费；DeepSeek 仅处理「非重复、非明显垃圾」的新条目；批量调用；失败重试与断点续跑。
- **上线前校准**：先抽 30 张真实截图跑 DeepSeek，产出结果供用户核对质量再全量。

## 5. 数据模型（SQLite）

- `items`：id, kind(灵感/工具), title, summary, ocr_text, source_type, source_ref(原始路径/消息定位), captured_at(内容时间), created_at, image_path(缓存图), extra_json。
- `tags` / `item_tags`：标签与多对多关联。
- `tools`：合并后的工具卡：name(规范名), aliases_json, official_url, purpose, first_seen, last_seen, mention_count；`tool_items` 关联到来源 items。
- `fingerprints`：hash/组合键 → status(processed/junk) + 处理时间；用于去重与增量。
- `items_fts`（FTS5）：title + summary + ocr_text，中文分词（unicode61 / 结巴可选），供全文搜索。
- 图像 pHash 存于 items.extra_json 或独立 `phash` 表，用于近似去重。

## 6. 界面（本地网页，FastAPI 提供，双击 .bat 启动并打开浏览器）

1. **分类浏览 + 搜索**：顶部搜索框（全文）；侧栏按 灵感/工具/标签 筛选；卡片流展示缩略图+标题+摘要；点开看原图与上下文。
2. **工具清单库**：合并去重后的工具卡表格/卡片；可编辑规范名与官网；点入看所有来源截图。
3. **灵感 → 选题**：勾选/按标签聚合灵感 → 一键让 DeepSeek 归纳为若干内容选题与素材要点。
4. **垃圾复核**：列出被判为垃圾的条目，用户可「其实有用」召回入库；不删除任何原始文件。

## 7. 新截图导图步骤（用户执行，程序消费）

- 需求：解出 332 张 V2 `.dat` 为明文图片到一个文件夹。
- 方案 A（首选，复用用户现有工具）：在用户 `<你的微信导出工具>` 项目内提供 `export_images.py`，复用 `wxsnap` 已验证可用的内存密钥机制取账号密钥，加入 V2 `.dat` 解码器（`[6B签名][4B aes_size LE][4B xor_size LE][1B pad]` + AES-ECB 段/明文段/XOR 段），输出到 `export_images/<月>/*.png|jpg`。由**用户运行**（内存提取属用户在本机的操作）。
- 方案 B（兜底）：用户运行成熟开源工具 `sjzar/chatlog`，其解密图片并经本地 HTTP/导出提供；程序从其输出目录读取。
- 本项目的采集层对「明文图片文件夹」统一消费，A/B 皆可；未导图时该来源缺省为空，不阻塞其余流程。
- 注：AES 图片密钥是否等同/可由 SQLCipher DB 密钥推得，运行时验证；导图脚本对老格式(XOR)与新格式(V2)自动判别。

## 8. 技术栈

- 语言：Python 3.12（已装）。
- Web：FastAPI + uvicorn；前端单页（原生 HTML/CSS/JS 或轻量方案），由后端静态服务。
- 存储：SQLite + FTS5。
- OCR：RapidOCR（onnxruntime，本地中文，免费离线）。
- 图像：Pillow（解码/缩略图），imagehash（pHash 近似去重）。
- 加密解码：老格式单字节 XOR（自识别 magic）；V2 解码器（导图脚本侧）。
- AI：DeepSeek（OpenAI 兼容），复用 `<导出工具目录>/secrets.json` 的 `DEEPSEEK_API_KEY`；模型/端点/温度/超时走 `config.json`，模型可切换。
- 启动：`启动灵感库.bat` 起服务并打开 `http://127.0.0.1:<port>`。

## 9. 隐私与安全

- 全程本地；对外只有 DeepSeek 调用，发送内容为截图/文本与提取文字（用户知情并主动选择 DeepSeek）。
- API key 仅从本地 `secrets.json` 读取，不打印、不入库、不进日志、不进 git。
- 不参与任何微信内存密钥提取（受运行环境安全策略限制且非本项目职责）；解密由用户工具箱完成。
- 微信原始目录只读；本项目所有写操作限于自身项目目录。
- `.gitignore` 排除：`secrets.json`、`*.db`、缓存图目录、明文导出、日志。

## 10. 目录结构（建于 `<项目目录>/`）

```
<项目目录>/
  docs\superpowers\specs\2026-09-26-inspiration-box-design.md
  config.example.json          # 端口、来源、DeepSeek 参数、路径
  inbox\album\                 # 手机相册补充截图放这里
  cache\images\                # 解码/缩略图缓存
  data\inspiration.db          # SQLite（gitignore）
  src\
    collect.py                 # 汇集各来源为统一"原子输入"
    decode_dat.py              # 老格式 XOR 解码 + magic 识别
    dedup.py                   # 文件哈希 + pHash
    ocr.py                     # RapidOCR 封装
    classify.py                # DeepSeek 判定与提取
    store.py                   # SQLite/FTS 读写、增量指纹
    server.py                  # FastAPI + 页面路由/接口
    web\                       # 前端页面
  启动灵感库.bat
```

## 11. 里程碑（供实现计划展开）

1. 采集+解码+去重：跑通把 202 老图 + 文档 + filehelper 文字变成"原子输入"并去重。
2. OCR + 存储 + 搜索：本地 OCR、写 SQLite/FTS、命令行能搜。
3. DeepSeek 判定：30 张校准 → 全量分类打标；增量与成本控制。
4. 网页界面：四个页面（浏览搜索 / 工具库 / 灵感选题 / 垃圾复核）。
5. 导图对接：`export_images.py`（用户跑）+ 采集层消费明文图片文件夹，补齐 332 新图。
6. 打包启动：`.bat` 一键启动 + 使用说明。
