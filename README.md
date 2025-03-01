# LLM-Rewrite

## 项目简介

这是一个基于 FastAPI 的 API 代理服务，搭建openai格式的api转发层，对原模型的输出进行指定风格的重写。

（开发该项目的本意是解决grok-3等模型中文文笔差的问题）

## 安装

1. 克隆仓库

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 创建并配置 `config.yaml` 文件
```bash
cp config.yaml.example config.yaml
# 编辑 config.yaml 设置你的 API 密钥和其他配置
```

## 配置说明

配置文件 `config.yaml` 包含以下主要部分：

- 服务器配置：监听地址和端口
- CORS 设置：允许的域名、方法等
- 日志配置：日志级别和格式
- 调试模式：是否启用调试输出
- 原始 API 配置：目标 API 的 URL 和密钥
- 重写 API 配置：重写 API 的 URL、密钥、模型和风格设置

你也可以通过环境变量 `CONFIG_PATH` 指定配置文件的位置：
```bash
export CONFIG_PATH=/path/to/your/config.yaml
```

## 运行服务

```bash
python main.py
```

或者使用 uvicorn 直接运行：
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## 特别说明

服务会代理所有原始 API 的端点，保证了对api的正常访问。


## 许可证

[MIT](LICENSE)