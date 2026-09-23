FROM --platform=linux/amd64 catchoco/video-scene-split:latest

WORKDIR /opt/application
USER root

COPY . .
RUN pip install fastapi uvicorn tos requests
# 暴露端口
EXPOSE 8000

# 启动应用
RUN chmod +x /opt/application/run.sh
CMD ["bash", "/opt/application/run.sh"]