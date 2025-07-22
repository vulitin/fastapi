from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
import sqlite3
import requests
import os
from datetime import datetime

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

# Конфигурация
API_LAYER_URL = "https://api.apilayer.com/sentiment/analysis"
API_KEY = "your_api_key_here"  # Замените на ваш реальный ключ
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
                sentiment TEXT NOT NULL
            )
            """)
            conn.commit()
    except sqlite3.Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database initialization failed: {str(e)}"
        )

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
def save_complaint(text: str, sentiment: str) -> int:
    try:
        with sqlite3.connect(DATABASE_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO complaints (text, sentiment) VALUES (?, ?)",
                (text, sentiment)
            )
            conn.commit()
            return cursor.lastrowid
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
                "SELECT id, text, sentiment, timestamp FROM complaints WHERE id = ?",
                (complaint_id,)
            )
            result = cursor.fetchone()
            if not result:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")
            return {
                "complaint_id": result[0],
                "text": result[1],
                "sentiment": result[2],
                "timestamp": result[3]
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
            sentiment=analysis_result["sentiment"]
        )
    
        # Получение сохраненной записи для ответа
        saved_complaint = get_complaint(complaint_id)
    
        return SentimentAnalysisResult(
            complaint_id=saved_complaint["complaint_id"],
            text=saved_complaint["text"],
            sentiment=saved_complaint["sentiment"],
            timestamp=saved_complaint["timestamp"]
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
            timestamp=complaint["timestamp"]
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )