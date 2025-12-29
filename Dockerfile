# Dockerfile

# Python 3.11 공식 이미지를 기반으로 시작합니다. (3.10도 괜찮습니다)
FROM python:3.11-slim

# 환경 변수 설정
ENV PYTHONUNBUFFERED True

# 작업 디렉토리를 /app 으로 설정합니다.
WORKDIR /app

# requirements.txt 파일을 먼저 복사하여 라이브러리를 설치합니다.
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 나머지 모든 프로젝트 파일을 복사합니다.
COPY . .

# Cloud Run이 지정하는 포트($PORT)에서 gunicorn을 실행합니다.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 chatbot:app