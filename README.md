# OpenReview 论文下载工具（CSIM速度会草稿生成工具）

`download_openreview_papers.py` 是一个命令行脚本，用于从 OpenReview 网站批量下载论文 PDF，并生成对应的参考文献列表。当前支持 **GB/T 7714-2015 数字顺序** 和 **IEEE 会议论文** 两种引用格式。

## 功能特点
- 根据关键词匹配论文标题或摘要并下载 PDF；
- 自动输出 GB/T 7714 或 IEEE 样式的参考文献；
- 可限制下载数量，或选择是否包含尚在评审中的稿件。

## 安装
1. 准备 `Python 3.8+` 环境；
2. 克隆仓库：
   ```bash
   git clone <repo_url>
   cd paper_download
   ```
3. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
4. 配置 OpenReview 登录信息：
   ```bash
   export OPENREVIEW_USERNAME="you@example.com"
   export OPENREVIEW_PASSWORD="your_password"
   ```

## 快速开始
下面的示例从 ICLR 2025 与 NeurIPS 2024 两个会场检索包含 “reinforcement learning” 的论文，
结果会创建一个新的运行目录（如 `runs/20250628_120000`），其中包含 PDF、查询信息与参考文献：
```bash
python download_openreview_papers.py \
  --query "reinforcement learning" \
  --venues ICLR.cc/2025/Conference NeurIPS.cc/2024/Conference \
  --style ieee \
  --out runs \
  --run-name 20250628_120000 \
  --max 40
```

## 参数说明
| 参数 | 说明 |
| ---- | ---- |
| `--query` | 必填，关键词或正则表达式，匹配论文标题或摘要（忽略大小写）。 |
| `--venues` | 必填，OpenReview 会场 ID，可同时指定多个，如 `ICLR.cc/2025/Conference`。 |
| `--out` | 用于存放运行目录的父路径，默认 `runs`。 |
| `--run-name` | 运行目录名称，默认为当前时间戳。 |
| `--style` | 参考文献格式，可选 `gb7714`（默认）或 `ieee`。 |
| `--max` | 限制最多下载 N 篇论文。 |
| `--include-submitted` | 包括仍在评审或已撤稿的投稿。 |

执行完成后，若存在匹配论文，会在输出目录生成 `references_<style>.txt`，其中包含对应格式的参考文献。

## 使用 DeepSeek 总结论文

`summarize_papers.py` 可以自动遍历指定目录下的 PDF，并调用 DeepSeek API 生成摘要。
在运行脚本前，请通过环境变量提供 API 密钥：

```bash
export DEEPSEEK_API_KEY="your_api_key"
python summarize_papers.py runs/20250628_120000/papers
```



## 根据摘要生成 PPT

`generate_ppt.py` 会读取运行目录内 `summaries` 子目录的 JSON 文件，将摘要内容直接填入 `template.pptx` 模板，并在每张幻灯片右下角自动添加页码。

```bash
python generate_ppt.py runs/20250628_120000/summaries --out slides.pptx
```

## 更新日志
- **v0.6** – 生成PPT。
- v0.5 – 通过deepseek生成PPT摘要。
- v0.4 – 新增 `--style` 选项，可生成 GB/T 7714 或 IEEE 风格参考文献。
- v0.3 – 支持 GB/T 7714 格式。
- v0.2 – 修复 `details` 为空导致的问题。
- v0.1 – 初始版本。