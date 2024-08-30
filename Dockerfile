# 베이스 이미지로 Python 3.11 사용
FROM python:3.11-slim

# 작업 디렉토리를 설정
WORKDIR /app

# 필요한 패키지 설치
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY . /app

# FastAPI 서버 실행
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
