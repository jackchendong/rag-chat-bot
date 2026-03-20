# conda

```
conda create -n rag-chat-bot python=3.10
conda activate rag-chat-bot
```

# pip

```
pip install -r requirements.txt
pip show fastapi
pip list
```

如果连接 MySQL 时出现 caching_sha2_password 相关错误，需要确保已安装 cryptography（已在 requirements.txt 中）。

# 目录结构

```
app/
	api/
		routes.py
	core/
		database.py
	models/
		user.py
	service/
		chat_service.py
		user_service.py
	main.py
```

# run

```
python -m app.main
```

会自动加载项目根目录 `.env`，并读取 `SERVER_PORT`（例如 `SERVER_PORT=8000`）。
数据库使用 SQLAlchemy + MySQL，连接串通过 `DATABASE_URL` 配置。

`.env` 示例：

```
SERVER_PORT=8000
DATABASE_URL=mysql+pymysql://root:password@127.0.0.1:3306/rag_chat_bot?charset=utf8mb4
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=deepseek-chat
OPENAI_API_BASE_URL=https://api.deepseek.com/v1
```

打开 http://127.0.0.1:8000/ 会返回：

```
ok
```

RESTful 用户接口：

```
GET /users?q=adm&limit=10&offset=0
GET /users/{user_id}
POST /users
PUT /users/{user_id}
DELETE /users/{user_id}
```

对话接口：

```
POST /chat
POST /chat/stream
```

POST /chat 请求示例：

```
{
	"message": "你好，介绍一下你自己",
	"system_prompt": "你是一个简洁的助手",
	"conversation_id": "demo-1"
}
```

POST /chat 响应示例：

```
{
	"answer": "你好！我是一个 AI 助手..."
}
```

SSE 流式对话示例：

```bash
curl -N -X POST http://127.0.0.1:8000/chat/stream \
	-H "Content-Type: application/json" \
	-d '{"message":"请分三段介绍 FastAPI","system_prompt":"你是一个简洁助手","conversation_id":"demo-1"}'
```

返回格式为 SSE：

```text
data: {"delta":"..."}

data: {"delta":"..."}

data: {"done":true}
```

多轮对话说明：

```
conversation_id 相同会命中同一段内存会话历史。
当前是进程内缓存，服务重启后会话历史会丢失。
```

POST /users 请求示例：

```
{
	"username": "alice",
	"email": "alice@example.com"
}
```

PUT /users/{user_id} 请求示例：

```
{
	"username": "alice_new",
	"email": "alice_new@example.com"
}
```

查询参数说明：

```
q      按 username 模糊查询（可选）
limit  每页数量（默认 10）
offset 偏移量（默认 0）
```
