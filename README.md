# News Focus

一个聚合新闻源并按需翻译标题/摘要的网页应用。

## 本地运行

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python server.py
```

默认地址是 `http://127.0.0.1:8765`。

## Vercel 部署

项目已提供 Vercel 可识别的 Flask WSGI 入口：`server.py` 中的 `app`。

在 Vercel 导入 GitHub 仓库后，Framework Preset 选择 `Other`，Build Command 留空。

需要在 Vercel Project Settings -> Environment Variables 中配置：

```text
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

`public/` 中的文件会作为静态资源发布，后端接口由 Flask app 提供：

- `GET /api/feed`
- `GET /api/preview`
- `POST /api/translate`
