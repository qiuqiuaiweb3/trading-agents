# 统一 Python 版本，减少环境差异
FROM python:3.13-slim

# 安装编译依赖、PostgreSQL 客户端库
RUN apt-get update && apt-get install -y build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

# 设定工作目录，方便 COPY 与 CMD
WORKDIR /app

# 先拷贝依赖定义文件，加速 docker layer cache
COPY pyproject.toml poetry.lock /app/

# 安装依赖并禁用虚拟环境
RUN pip install --upgrade pip && pip install poetry && poetry config virtualenvs.create false && poetry install --no-root

# 拷贝全部项目代码（记得配合 .dockerignore）
COPY . /app/

# 容器启动命令，可按模块替换
CMD ["python", "main.py"]