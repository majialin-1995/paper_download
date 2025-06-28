# OpenReview 论文下载工具

`download_openreview_papers.py` 是一个命令行脚本，用于从 OpenReview 网站批量下载论文 PDF，并生成对应的参考文献列表。当前支持 **GB/T 7714-2015 数字顺序** 和 **IEEE 会议论文** 两种引用格式。

## 功能特点
- 根据关键词匹配论文标题或摘要并下载 PDF；
- 自动输出 GB/T 7714 或 IEEE 样式的参考文献；
- 可限制下载数量，或选择是否包含尚在评审中的稿件。

## 安装
1. 准备 `Python 3.8+` 环境；
2. 安装依赖：
   ```bash
   pip install openreview-py tqdm pypdf
   ```
3. 配置 OpenReview 登录信息：
   ```bash
   export OPENREVIEW_USERNAME="you@example.com"
   export OPENREVIEW_PASSWORD="your_password"
   ```

## 快速开始
下面的示例从 ICLR 2025 与 NeurIPS 2024 两个会场检索包含 “reinforcement learning” 的论文，
将 PDF 保存至 `papers` 目录，并以 IEEE 风格生成参考文献：
```bash
python download_openreview_papers.py \
  --query "reinforcement learning" \
  --venues ICLR.cc/2025/Conference NeurIPS.cc/2024/Conference \
  --style ieee \
  --out papers \
  --max 40
```

## 参数说明
| 参数 | 说明 |
| ---- | ---- |
| `--query` | 必填，关键词或正则表达式，匹配论文标题或摘要（忽略大小写）。 |
| `--venues` | 必填，OpenReview 会场 ID，可同时指定多个，如 `ICLR.cc/2025/Conference`。 |
| `--out` | PDF 保存目录，默认 `papers`。 |
| `--style` | 参考文献格式，可选 `gb7714`（默认）或 `ieee`。 |
| `--max` | 限制最多下载 N 篇论文。 |
| `--include-submitted` | 包括仍在评审或已撤稿的投稿。 |

执行完成后，若存在匹配论文，会在输出目录生成 `references_<style>.txt`，其中包含对应格式的参考文献。

## 使用 DeepSeek 总结论文

`summarize_papers.py` 可以自动遍历指定目录下的 PDF，并调用 DeepSeek API 生成摘要。
在运行脚本前，请通过环境变量提供 API 密钥：

```bash
export DEEPSEEK_API_KEY="your_api_key"
python summarize_papers.py papers --out summaries
```

## 更新日志
- **v0.4** – 新增 `--style` 选项，可生成 GB/T 7714 或 IEEE 风格参考文献。
- v0.3 – 支持 GB/T 7714 格式。
- v0.2 – 修复 `details` 为空导致的问题。
- v0.1 – 初始版本。

## 根据摘要生成 PPT

`generate_ppt.py` 通过读取 `summaries` 目录下的 JSON 文件，自动将摘要内容填充到 `template.pptx` 模板中，生成适合汇报的幻灯片。若摘要并非中文，脚本会调用 DeepSeek 进行翻译。

```bash
export DEEPSEEK_API_KEY="your_api_key"  # 只有需要翻译时才必需
python generate_ppt.py summaries --out slides.pptx
```