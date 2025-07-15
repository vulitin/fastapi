from fastapi import FastAPI, HTTPException
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
    sentiment: str
    confidence: float
    timestamp: str

# Конфигурация
API_LAYER_URL = "https://api.apilayer.com/sentiment/analysis"
API_KEY = "your_api_key_here"  # Замените на ваш реальный ключ
DATABASE_NAME = "complaints.db"

# Инициализация базы данных
def init_db():
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            status TEXT DEFAULT OPEN,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            sentiment TEXT NOT NULL,
            confidence REAL NOT NULL
        )
        """)
        conn.commit()

# Вызов API анализа тональности
def analyze_sentiment(text: str) -> dict:
    headers = {"apikey": API_KEY}
    try:
        response = requests.post(API_LAYER_URL, headers=headers, data=text.encode("utf-8"))
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Sentiment analysis API error: {str(e)}")

# Сохранение жалобы в базу данных
def save_complaint(text: str, sentiment: str, confidence: float) -> int:
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO complaints (text, sentiment, confidence) VALUES (?, ?, ?)",
            (text, sentiment, confidence)
        )
        conn.commit()
        return cursor.lastrowid

# Получение жалобы из базы данных
def get_complaint(complaint_id: int) -> dict:
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, text, sentiment, confidence, timestamp FROM complaints WHERE id = ?",
            (complaint_id,)
        )
        result = cursor.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Complaint not found")
        return {
            "complaint_id": result[0],
            "text": result[1],
            "sentiment": result[2],
            "confidence": result[3],
            "timestamp": result[4]
        }

@app.on_event("startup")
async def startup_event():
    init_db()

@app.post("/analyze", response_model=SentimentAnalysisResult)
async def analyze_complaint(complaint: Complaint):
    # Анализ тональности
    analysis_result = analyze_sentiment(complaint.text)
    
    # Проверка наличия ожидаемых полей в ответе
    if not all(key in analysis_result for key in ["sentiment", "confidence"]):
        raise HTTPException(
            status_code=500,
            detail="Unexpected response from sentiment analysis API"
        )
    
    # Сохранение в базу данных
    complaint_id = save_complaint(
        text=complaint.text,
        sentiment=analysis_result["sentiment"],
        confidence=float(analysis_result["confidence"])
    )
    
    # Получение сохраненной записи для ответа
    saved_complaint = get_complaint(complaint_id)
    
    return SentimentAnalysisResult(
        complaint_id=saved_complaint["complaint_id"],
        text=saved_complaint["text"],
        sentiment=saved_complaint["sentiment"],
        confidence=saved_complaint["confidence"],
        timestamp=saved_complaint["timestamp"]
    )

@app.get("/complaints/{complaint_id}", response_model=SentimentAnalysisResult)
async def get_complaint_by_id(complaint_id: int):
    complaint = get_complaint(complaint_id)
    return SentimentAnalysisResult(
        complaint_id=complaint["complaint_id"],
        text=complaint["text"],
        sentiment=complaint["sentiment"],
        confidence=complaint["confidence"],
        timestamp=complaint["timestamp"]
    )