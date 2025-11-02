 
# 🌐 AGENTIC AI DISASTER DETECTION SYSTEM (Flask Web App)
 

from flask import Flask, render_template, request
import feedparser, requests, time, os, json, re
import pandas as pd
import numpy as np
from datetime import datetime
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from twilio.rest import Client
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

 
# CONFIGURATION
 
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
RECIPIENT_PHONE_NUMBER = os.getenv("RECIPIENT_PHONE_NUMBER")
SPREADSHEET_URL = os.getenv("SPREADSHEET_URL")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("models/gemini-2.5-flash")

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file("credentials.json", scopes=scope)
gc = gspread.authorize(creds)
worksheet = gc.open_by_url(SPREADSHEET_URL).sheet1

 
#   HOME ROUTE (User Interaction Agent)
 
@app.route('/')
def index():
    return render_template('index.html')

 
#   PROCESS ROUTE (Full Pipeline Execution)
 
@app.route('/process', methods=['POST'])
def process():
    disaster_type = request.form['disaster_type'].strip().lower()
    location = request.form['location'].strip().title()
    query_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    query = f"{disaster_type} {location}"
    encoded_query = query.replace(' ', '+')
    articles = []

     
    #   2. DATA ACQUISITION AGENT
     
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
    feed = feedparser.parse(rss_url)
    for entry in feed.entries[:10]:
        articles.append({
            "Source": "Google News",
            "Title": entry.title,
            "Published": entry.get('published', 'Unknown date'),
            "Link": entry.link,
            "Query": query,
            "Fetched_At": query_time
        })

    NEWSAPI_KEY = "2d0d13f047c04ff1b8ef90ef795f68c2"
    newsapi_url = f"https://newsapi.org/v2/everything?q={encoded_query}&language=en&sortBy=publishedAt&pageSize=10&apiKey={NEWSAPI_KEY}"
    try:
        response = requests.get(newsapi_url)
        data = response.json()
        for article in data.get("articles", []):
            articles.append({
                "Source": article.get("source", {}).get("name", "NewsAPI"),
                "Title": article.get("title", ""),
                "Published": article.get("publishedAt", ""),
                "Link": article.get("url", ""),
                "Query": query,
                "Fetched_At": query_time
            })
    except Exception as e:
        print("NewsAPI Error:", e)

    # Gemini reasoning
    prompt = f"Summarize the latest verified information about '{disaster_type}' in '{location}' (India). Return 3-5 items in JSON."
    try:
        gemini_response = model.generate_content(prompt)
        text_response = re.sub(r"```json|```", "", gemini_response.text.strip())
        gemini_articles = json.loads(text_response)
        for g in gemini_articles:
            articles.append({
                "Source": g.get("Source", "Gemini"),
                "Title": g.get("Title", g.get("headline", "")),
                "Published": g.get("Published", g.get("date", "Unknown")),
                "Link": g.get("Link", "N/A"),
                "Query": query,
                "Fetched_At": query_time
            })
    except:
        pass

    df = pd.DataFrame(articles).drop_duplicates(subset=["Title"])
    if not df.empty:
        worksheet.append_rows(df.values.tolist(), value_input_option="RAW")

     
    #   3. INFORMATION PROCESSING AGENT
     
    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform(df['Title'])
    query_vec = vectorizer.transform([query])
    cosine_similarities = cosine_similarity(query_vec, tfidf_matrix).flatten()
    df['RelevanceScore'] = cosine_similarities
    df_sorted = df.sort_values(by='RelevanceScore', ascending=False).head(5)

    joined_text = "\n".join(df_sorted['Title'])
    summary_prompt = f"Summarize the following disaster news headlines about {disaster_type} in {location}:\n\n{joined_text}"
    summary = model.generate_content(summary_prompt).text

     
    #   4. SEVERITY ASSESSMENT AGENT
     
    severity_score = 0.3
    severity_level = "Low"
    text = summary.lower()
    if any(k in text for k in ['severe', 'evacuation', 'fatalities']):
        severity_score, severity_level = 0.9, "High"
    elif any(k in text for k in ['warning', 'heavy', 'landslide']):
        severity_score, severity_level = 0.6, "Moderate"

     
    #   5. ALERT AND NOTIFICATION AGENT
     
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    alert_msg = {
        "High": f"🚨 HIGH ALERT: Severe {disaster_type} in {location}. Move to safe zones immediately.",
        "Moderate": f"⚠️ MODERATE ALERT: {disaster_type.title()} in {location}. Stay indoors.",
        "Low": f"ℹ️ LOW ALERT: Mild {disaster_type} in {location}. Stay informed."
    }[severity_level]
    try:
        client.messages.create(body=alert_msg, from_=TWILIO_PHONE_NUMBER, to=RECIPIENT_PHONE_NUMBER)
    except:
        print("SMS sending failed (sandbox or test mode).")

     
    #   6. KNOWLEDGE UPDATE AGENT
     
    knowledge_update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Return all outputs to frontend
    return render_template('result.html',
                           disaster_type=disaster_type,
                           location=location,
                           articles=df_sorted.to_dict(orient='records'),
                           summary=summary,
                           severity=severity_level,
                           score=severity_score,
                           update_time=knowledge_update_time)
                           
if __name__ == '__main__':
    app.run(debug=True)
