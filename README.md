# Buzzing Focus

一个聚合多源新闻的网页应用。

## 本地运行

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python server.py
```

默认地址是 `http://127.0.0.1:8765`。

## 测试

```bash
. .venv/bin/activate
python -m unittest discover -s tests
```

## Vercel 部署

项目已提供 Vercel 可识别的 Flask WSGI 入口：`server.py` 中的 `app`。

在 Vercel 导入 GitHub 仓库后，Framework Preset 选择 `Other`，Build Command 留空。

需要在 Vercel Project Settings -> Environment Variables 中配置：

```text
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
DEEPLX_TOKEN=your_deeplx_token
```

- **DeepSeek** 驱动 `/api/summary` 的 AI 要闻总结。
- **DeepLX** 翻译非中文新闻的标题和摘要为中文（token 在
  [connect.linux.do](https://connect.linux.do) 获取）。未设置时 feed 保持原文。

`public/` 中的文件会作为静态资源发布，后端接口由 Flask app 提供：

- `GET /api/feed`
- `GET /api/preview`
