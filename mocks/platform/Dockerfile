# 基础镜像走 1ms.run 代理源（Docker Hub 直连在本机超时，参见项目记忆）
FROM docker.1ms.run/library/python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 9000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
