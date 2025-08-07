from fastapi import FastAPI, HTTPException, status, Request
from pydantic import BaseModel
import sqlite3
import requests
from datetime import datetime
from typing import Optional
import ipaddress

app = FastAPI()

# Модель для входных данных
class Complaint(BaseModel):
    text: str

# Модель для ответа
class SentimentAnalysisResult(BaseModel):
    complaint_id: int
    text: str
    timestamp: str
    sentiment: str
    ip_address: str
    ip_country: Optional[str]
    ip_region: Optional[str]
    ip_city: Optional[str]
    ip_isp: Optional[str]

# Конфигурация
API_LAYER_URL = "https://api.apilayer.com/sentiment/analysis"
API_KEY = "your_api_key_here"  # Замените на ваш реальный ключ
SPAM_API_URL = "https://api.api-ninjas.com/v1/spamdetection"
SPAM_API_KEY = "your_api_ninjas_key_here"
IP_API_URL = "http://ip-api.com/json/"
DATABASE_NAME = "complaints.db"

# Инициализация базы данных
def init_db():
    try:
        with sqlite3.connect(DATABASE_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                status TEXT DEFAULT OPEN,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                sentiment TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                ip_country TEXT,
                ip_region TEXT,
                ip_city TEXT,
                ip_isp TEXT
            )
            """)
            conn.commit()
    except sqlite3.Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database initialization failed: {str(e)}"
        )

# Проверка IP-адреса
def check_ip(ip: str) -> dict:
    try:
        # Валидация IP-адреса
        ipaddress.ip_address(ip)
        
        response = requests.get(
            f"{IP_API_URL}{ip}",
            timeout=5
        )
        response.raise_for_status()
        return response.json()
    except (ipaddress.AddressValueError, ValueError):
        return {"status": "fail", "message": "invalid IP"}
    except requests.exceptions.RequestException as e:
        print(f"IP API error: {str(e)}")
        return {"status": "fail", "message": "API error"}

# Проверка на спам
def check_spam(text: str) -> dict:
    headers = {"X-Api-Key": SPAM_API_KEY}
    try:
        response = requests.get(
            SPAM_API_URL,
            headers=headers,
            params={"text": text},
            timeout=5
        )
        response.raise_for_status()
        return response.json()
    except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
        print(f"Spam check API error: {str(e)}")
        return {"is_spam": False}

# Вызов API анализа тональности
def analyze_sentiment(text: str) -> dict:
    headers = {"apikey": API_KEY}
    try:
        response = requests.post(API_LAYER_URL, headers=headers, data=text.encode("utf-8"))
        response.raise_for_status()
        return response.json()
    except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
        print(f"Sentiment analysis API error: {str(e)}")
        return None
    
# Сохранение жалобы в базу данных
def save_complaint(
        text: str,
        sentiment: str,
        is_spam: bool,
        ip_address: str,
        ip_info: dict) -> int:
    try:
        if is_spam == False:
            with sqlite3.connect(DATABASE_NAME) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO complaints (text, sentiment, ip_address, ip_country, ip_region, ip_city, ip_isp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (text, sentiment, ip_address,
                    ip_info.get("country"),
                    ip_info.get("regionName"),
                    ip_info.get("city"),
                    ip_info.get("isp"))
                )
                conn.commit()
                return cursor.lastrowid
        else:
            print(f"Spam detected")
    except sqlite3.Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save complaint: {str(e)}"
        )

# Получение жалобы из базы данных
def get_complaint(complaint_id: int) -> dict:
    
    try:
        with sqlite3.connect(DATABASE_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, text, timestamp, sentiment, ip_address, ip_country, ip_region, ip_city, ip_isp FROM complaints WHERE id = ?",
                (complaint_id,)
            )
            result = cursor.fetchone()
            if not result:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")
            return {
                "complaint_id": result[0],
                "text": result[1],
                "timestamp": result[2],
                "sentiment": result[3],
                "ip_address": result[4],
                "ip_country": result[5],
                "ip_region": result[6],
                "ip_city": result[7],
                "ip_isp": result[8]
            }
    except sqlite3.Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )    

@app.on_event("startup")
async def startup_event():
 try:
        init_db()
 except HTTPException as e:
        print(f"Failed to initialize database: {e.detail}")
        raise e

@app.post("/analyze", response_model=SentimentAnalysisResult)
async def analyze_complaint(complaint: Complaint):
    try:
        # Получаем IP-адрес клиента
        client_ip = requests.request.client.host
        if not client_ip:
            client_ip = "127.0.0.1"
        
        # Анализ IP-адреса
        ip_info = check_ip(client_ip)

        # Проверка на спам
        spam_result = check_spam(complaint.text)
        is_spam = spam_result.get("is_spam", False)

        # Анализ тональности
        analysis_result = analyze_sentiment(complaint.text)
        # Если API недоступно, используем значения по умолчанию
        if analysis_result is None:
            sentiment = "unknown"
        else:
            # Проверка наличия ожидаемых полей в ответе
            if not all(key in analysis_result for key in ["sentiment"]):
                sentiment = "unknown"
                confidence = 0.0
            else:
                sentiment = analysis_result["sentiment"]            
    
        # Сохранение в базу данных
        complaint_id = save_complaint(
            text=complaint.text,
            sentiment=analysis_result["sentiment"],
            ip_address=client_ip,
            ip_info=ip_info if ip_info.get("status") == "success" else {}
        )
    
        # Получение сохраненной записи для ответа
        saved_complaint = get_complaint(complaint_id)
    
        return SentimentAnalysisResult(
            complaint_id=saved_complaint["complaint_id"],
            text=saved_complaint["text"],
            sentiment=saved_complaint["sentiment"],
            timestamp=saved_complaint["timestamp"],
            ip_address=saved_complaint["ip_address"],
            ip_country=saved_complaint["ip_country"],
            ip_region=saved_complaint["ip_region"],
            ip_city=saved_complaint["ip_city"],
            ip_isp=saved_complaint["ip_isp"]
        )
    except HTTPException:
        # Пробрасываем уже созданные HTTPException
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )

@app.get("/complaints/{complaint_id}", response_model=SentimentAnalysisResult)
async def get_complaint_by_id(complaint_id: int):
    try:
        complaint = get_complaint(complaint_id)
        return SentimentAnalysisResult(
            complaint_id=complaint["complaint_id"],
            text=complaint["text"],
            sentiment=complaint["sentiment"],
            timestamp=complaint["timestamp"],
            ip_address=complaint["ip_address"],
            ip_country=complaint["ip_country"],
            ip_region=complaint["ip_region"],
            ip_city=complaint["ip_city"],
            ip_isp=complaint["ip_isp"]
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )