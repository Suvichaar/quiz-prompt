import os
import json
import base64
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

# ===== 🔧 Slug and URL generator =====
def generate_slug_and_urls():
    nano = ''.join(random.choices(string.ascii_letters + string.digits, k=10)) + '_G'
    slug_full = f"generated-quiz_{nano}"
    s3_key = f"{S3_PREFIX}/{slug_full}.html"
    display_url = f"{DISPLAY_BASE}/{slug_full}.html"
    return slug_full, s3_key, display_url

# ===== 🔍 Pexels image search =====
def search_pexels_image(query):
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": query, "per_page": 1, "orientation": "portrait"}
    res = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params)
    photos = res.json().get("photos", [])
    if photos:
        return photos[0]["src"]["original"]
    return "https://via.placeholder.com/720x1280?text=No+Image"

# ===== 🧠 Azure GPT-4 Vision analysis =====
def analyze_image_with_gpt(image_bytes, context_prompt):
    image_base64 = base64.b64encode(image_bytes).decode()
    endpoint = f"{AZURE_ENDPOINT}/openai/deployments/{AZURE_DEPLOYMENT}/chat/completions?api-version={AZURE_API_VERSION}"
    headers = {"api-key": AZURE_API_KEY, "Content-Type": "application/json"}
    messages = [
        {"role": "system", "content": [{"type": "text", "text": context_prompt}]},
        {"role": "user", "content": [
            {"type": "text", "text": (
                "Generate 5 MCQ questions with 4 options each. "
                "Return the correct answer for each as a 'correct_index' (0-based index) in each question. "
                "Also return a title, cover_heading, cover_subtext, and result text. "
                "Return ONLY valid JSON. No extra text."
            )},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
        ]}
    ]
    payload = {"messages": messages, "temperature": 0.7, "max_tokens": 1800}
    res = requests.post(endpoint, headers=headers, json=payload)

    if res.status_code != 200:
        st.error(f"❌ Azure API Error {res.status_code}")
        st.text(res.text)
        return None

    try:
        content = res.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception:
        st.error("❌ Failed to parse GPT response as JSON.")
        st.code(res.text)
        return None

# ===== 🧾 HTML rendering =====
def render_quiz_html(data, image_urls, template_str):
    template = Template(template_str)
    html_data = {
        "pagetitle": data.get("title", "Untitled Quiz"),
        "storytitle": data.get("title", "Untitled Quiz"),
        "typeofquiz": "Auto Quiz",
        "potraitcoverurl": image_urls[0],
        "s1image1": image_urls[0],
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
        html_data[f"s{i}image1"] = image_urls[i - 1] if i - 1 < len(image_urls) else image_urls[0]
        html_data[f"s{i}question1"] = q.get("question", f"Question {i - 1}")
        for j in range(1, 5):
            html_data[f"s{i}option{j}"] = q.get("options", [f"Option {k}" for k in range(1, 5)])[j - 1]
        # Optionally: add correct answer to HTML as comment
        html_data[f"s{i}correct_index"] = q.get("correct_index", -1)
    return template.render(**html_data)

# ===== ☁️ Upload to S3 =====
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
st.title("🧠 Image-based Quiz Generator")

uploaded_image = st.file_uploader("📤 Upload a quiz image", type=["jpg", "jpeg", "png"])
uploaded_template = st.file_uploader("📄 Upload AMP quiz template", type="html")

if uploaded_image and uploaded_template:
    context_prompt = (
        "You are a visual quiz assistant. Generate a quiz from this image with 5 MCQ questions and results."
    )
    image_bytes = uploaded_image.read()
    template_str = uploaded_template.read().decode("utf-8")

    st.info("🧠 Analyzing image with GPT-4 Vision...")
    quiz_data = analyze_image_with_gpt(image_bytes, context_prompt)
    if not quiz_data:
        st.stop()

    st.json(quiz_data)
    
    quiz_topic = quiz_data.get("title") or quiz_data.get("cover_heading") or "quiz"

    st.info("🖼️ Fetching topic-oriented images from Pexels...")
    image_urls = []
    image_urls.append(search_pexels_image(quiz_topic))  # Cover
    for i, q in enumerate(quiz_data.get("questions", [])):
        img = search_pexels_image(q.get("question", quiz_topic))
        image_urls.append(img)
    while len(image_urls) < 5:
        image_urls.append(image_urls[0])

    # ===== Show Questions, Options, and Correct Answers =====
    st.markdown("### 📝 Questions and Correct Answers")
    for idx, q in enumerate(quiz_data.get("questions", []), 1):
        st.markdown(f"**Q{idx}: {q.get('question','')}**")
        options = q.get('options', [])
        correct_idx = q.get('correct_index', -1)
        for o_idx, opt in enumerate(options):
            marker = "✅" if o_idx == correct_idx else ""
            st.write(f"{chr(65+o_idx)}. {opt} {marker}")
        if correct_idx != -1:
            st.success(f"Correct Answer: {options[correct_idx]}")
        st.write("---")

    st.info("🧾 Rendering final HTML...")
    final_html = render_quiz_html(quiz_data, image_urls, template_str)

    st.info("☁️ Uploading to AWS S3...")
    slug_nano, s3_key, display_url = generate_slug_and_urls()
    upload_to_s3(final_html, s3_key)

    st.success("✅ HTML uploaded to S3")
    st.markdown(f"📎 [Open AMP Quiz Story]({display_url})", unsafe_allow_html=True)
    st.download_button("📥 Download HTML", data=final_html, file_name=f"{slug_nano}.html", mime="text/html")
