#!/bin/bash
# 自动部署脚本

# 1. 进入项目目录 (根据虚拟机路径)
cd ~/ai-payment-match

# 2. 拉取最新代码
echo "正在拉取最新代码..."
git pull origin main

# 3. 确保虚拟环境存在并更新依赖
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

source venv/bin/activate
echo "安装依赖..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. 杀掉旧的 Streamlit 进程
echo "重启服务..."
pkill streamlit || true

# 5. 后台启动服务
nohup streamlit run app.py --server.port 8501 --server.address 0.0.0.0 > output.log 2>&1 &

echo "🚀 部署完成！应用已在后台运行。"
