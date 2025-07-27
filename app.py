import os
import json
import random
import string
import requests
import boto3
import streamlit as st
from jinja2 import Template
from tempfile import NamedTemporaryFile

# ===== 🔐 Secrets from st.secrets =====
AZURE_API_KEY     = st.secrets["AZURE_API_KEY"]
AZURE_ENDPOINT    = st.secrets["AZURE_ENDPOINT"]
AZURE_DEPLOYMENT  = st.secrets["AZURE_DEPLOYMENT"]
AZURE_API_VERSION = st.secrets["AZURE_API_VERSION"]
PEXELS_API_KEY    = st.secrets["PEXELS_API_KEY"]

AWS_ACCESS_KEY = st.secrets["AWS_ACCESS_KEY"]
AWS_SECRET_KEY = st.secrets["AWS_SECRET_KEY"]
AWS_REGION     = st.secrets["AWS_REGION"]
AWS_BUCKET     = st.secrets["AWS_BUCKET"]
S3_PREFIX      = "suvichaarstories"
DISPLAY_BASE   = "https://suvichaar.org/stories"  # <-- for final output link

def generate_slug_and_urls():
    nano = ''.join(random.choices(string.ascii_letters + string.digits, k=10)) + '_G'
    slug_full = f"generated-quiz_{nano}"
    s3_key = f"{S3_PREFIX}/{slug_full}.html"
    display_url = f"{DISPLAY_BASE}/{slug_full}.html"
    return slug_full, s3_key, display_url

def search_pexels_image(query):
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": query, "per_page": 1, "orientation": "portrait"}
    try:
        res = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params, timeout=8)
        photos = res.json().get("photos", [])
        if photos:
            return photos[0]["src"]["original"]
    except Exception:
        pass
    return "https://via.placeholder.com/720x1280?text=No+Image"

def analyze_keyword_with_gpt(keyword, context_prompt):
    endpoint = f"{AZURE_ENDPOINT}/openai/deployments/{AZURE_DEPLOYMENT}/chat/completions?api-version={AZURE_API_VERSION}"
    headers = {"api-key": AZURE_API_KEY, "Content-Type": "application/json"}
    messages = [
        {"role": "system", "content": [{"type": "text", "text": context_prompt}]},
        {"role": "user", "content": [
            {"type": "text", "text":
                f"Using the topic: '{keyword}', generate 1 MCQ question (suitable for a quiz) with 4 options, a correct_index, and return only valid JSON like: "
                "{{'question': ..., 'options': [...], 'correct_index': ...}}. No extra text."}
        ]}
    ]
    payload = {"messages": messages, "temperature": 0.7, "max_tokens": 300}
    res = requests.post(endpoint, headers=headers, json=payload)
    if res.status_code != 200:
        return None
    try:
        content = res.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception:
        return None

def render_quiz_html(data, image_urls, template_str):
    template = Template(template_str)
    html_data = {
        "pagetitle": data.get("title", "Untitled Quiz"),
        "storytitle": data.get("title", "Untitled Quiz"),
        "typeofquiz": "Auto Quiz",
        "potraitcoverurl": image_urls[0],
        "s1image1": image_urls[0],         # Cover
        "s1title1": data.get("cover_heading", "Test Your Knowledge!"),
        "s1text1": data.get("cover_subtext", "Let's see how well you can guess."),
        "results_bg_image": image_urls[0],
        "results_prompt_text": data.get("results_text", "You've completed the quiz!"),
        "results1_image": image_urls[1], "results1_category": "Expert", "results1_text": "Incredible! You're a quiz master.",
        "results2_image": image_urls[2], "results2_category": "Smart Thinker", "results2_text": "Nice! You did well.",
        "results3_image": image_urls[3], "results3_category": "Explorer", "results3_text": "You're learning fast!",
        "results4_image": image_urls[4], "results4_category": "Beginner", "results4_text": "Keep trying, you'll get there!"
    }
    for i, q in enumerate(data.get("questions", []), start=2):
        html_data[f"s{i}image1"] = image_urls[i] if i < len(image_urls) else image_urls[0]
        html_data[f"s{i}question1"] = q.get("question", f"Question {i - 1}")
        options = q.get("options", [f"Option {k}" for k in range(1, 5)])
        correct_index = q.get("correct_index", 0)
        for j in range(1, 5):
            html_data[f"s{i}option{j}"] = options[j - 1]
            if (j - 1) == correct_index:
                html_data[f"s{i}option{j}attr"] = f'option-{j}-correct option-{j}-confetti="📚"'
            else:
                html_data[f"s{i}option{j}attr"] = ""
    return template.render(**html_data)

def upload_to_s3(content_str, s3_key):
    s3 = boto3.client("s3",
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION
    )
    with NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8") as tmp:
        tmp.write(content_str)
        tmp.flush()
        s3.upload_file(tmp.name, AWS_BUCKET, s3_key)

# ===== Streamlit UI =====
st.title("🧠 Keyword-based Quiz Generator (No Upload, Pexels Images)")

quiz_topic = st.text_input("Quiz Topic / Cover Keyword", value="EDUCATION")
keywords = []
for i in range(1, 6):
    keywords.append(st.text_input(f"Enter keyword for Question {i}:", key=f"kw{i}"))

ready = quiz_topic.strip() and all(k.strip() for k in keywords)
uploaded_template = st.file_uploader("📄 Upload AMP quiz template", type="html")

if uploaded_template and ready:
    template_str = uploaded_template.read().decode("utf-8")
    quiz_title = st.text_input("Quiz Title:", value="Quiz Based on Keywords")
    cover_heading = st.text_input("Cover Heading:", value="Test Your Knowledge!")
    cover_subtext = st.text_input("Cover Subtext:", value="Let's see how well you can guess.")
    results_text = st.text_input("Results Text:", value="You've completed the quiz!")

    context_prompt = "You are a quiz MCQ generator. For each keyword/topic, create one meaningful MCQ."

    questions = []
    image_urls = [search_pexels_image(quiz_topic)]  # Cover from quiz_topic/keyword
    st.info("Generating questions and fetching images...")
    for idx, kw in enumerate(keywords):
        st.write(f"🔍 Processing '{kw}' ...")
        # Generate question for this keyword
        q = analyze_keyword_with_gpt(kw, context_prompt)
        if not q:
            q = {"question": f"Default Question for {kw}", "options": ["Option 1", "Option 2", "Option 3", "Option 4"], "correct_index": 0}
        questions.append(q)
        image_urls.append(search_pexels_image(kw))

    quiz_data = {
        "title": quiz_title,
        "cover_heading": cover_heading,
        "cover_subtext": cover_subtext,
        "results_text": results_text,
        "questions": questions
    }

    st.json(quiz_data)

    st.info("🧾 Rendering final HTML...")
    final_html = render_quiz_html(quiz_data, image_urls, template_str)

    st.info("☁️ Uploading to AWS S3...")
    slug_nano, s3_key, display_url = generate_slug_and_urls()
    upload_to_s3(final_html, s3_key)

    st.success("✅ HTML uploaded to S3")
    st.markdown(f"📎 [Open AMP Quiz Story]({display_url})", unsafe_allow_html=True)
    st.download_button("📥 Download HTML", data=final_html, file_name=f"{slug_nano}.html", mime="text/html")
