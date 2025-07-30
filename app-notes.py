# At top of your Streamlit app
import os, json, random, string, time, requests, boto3
from PIL import Image
from io import BytesIO
import streamlit as st
from jinja2 import Template

# === Secrets ===
AZURE_API_KEY     = st.secrets["AZURE_API_KEY"]
AZURE_ENDPOINT    = st.secrets["AZURE_ENDPOINT"]
AZURE_DEPLOYMENT  = st.secrets["AZURE_DEPLOYMENT"]
AZURE_API_VERSION = st.secrets["AZURE_API_VERSION"]
DAALE_KEY         = st.secrets["DAALE_KEY"]
AWS_ACCESS_KEY    = st.secrets["AWS_ACCESS_KEY"]
AWS_SECRET_KEY    = st.secrets["AWS_SECRET_KEY"]
AWS_REGION        = st.secrets["AWS_REGION"]
AWS_BUCKET        = st.secrets["AWS_BUCKET"]
S3_PREFIX         = "suvichaarstories"
DISPLAY_BASE      = "https://cdn.suvichaar.org"

# === Utility Functions ===
def generate_slug_and_urls():
    nano = ''.join(random.choices(string.ascii_letters + string.digits, k=10)) + '_G'
    slug = f"generated-summary_{nano}"
    return slug, f"{S3_PREFIX}/{slug}.json", f"{S3_PREFIX}/{slug}.html", f"{DISPLAY_BASE}/{slug}.json", f"{DISPLAY_BASE}/{slug}.html"

def summarize_notes_with_gpt_vision(image_urls):
    messages = [
        {"role": "system", "content": "You're an educational summarizer. Create 5 slides (title, paragraph, image_prompt)."},
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}} for url in image_urls] +
         [{"type": "text", "text": "Summarize into 5 slides: title, paragraph, and image_prompt for each."}]}
    ]
    headers = {"api-key": AZURE_API_KEY, "Content-Type": "application/json"}
    endpoint = f"{AZURE_ENDPOINT}/openai/deployments/{AZURE_DEPLOYMENT}/chat/completions?api-version={AZURE_API_VERSION}"
    res = requests.post(endpoint, headers=headers, json={"messages": messages, "temperature": 0.7, "max_tokens": 1800})
    try:
        return json.loads(res.json()["choices"][0]["message"]["content"])
    except:
        return [{"title": f"Slide {i+1}", "text": "Placeholder", "image_prompt": "Default image"} for i in range(5)]

def generate_and_resize_images(prompts, slug):
    dalle_url = "https://njnam-m3jxkka3-swedencentral.cognitiveservices.azure.com/openai/deployments/dall-e-3/images/generations?api-version=2024-02-01"
    headers = {"Content-Type": "application/json", "api-key": DAALE_KEY}
    s3 = boto3.client("s3", aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY, region_name=AWS_REGION)
    urls = []

    for i, prompt in enumerate(prompts):
        payload = {"prompt": prompt, "n": 1, "size": "1024x1024"}
        url = "https://via.placeholder.com/1024x1024?text=No+Image"
        for _ in range(3):
            res = requests.post(dalle_url, headers=headers, json=payload, timeout=30)
            if res.status_code == 200:
                url = res.json()["data"][0]["url"]
                break
            elif res.status_code == 429:
                time.sleep(10)
        try:
            img_data = requests.get(url).content
            img = Image.open(BytesIO(img_data)).convert("RGB")
            img = img.resize((720, 1200))
            buffer = BytesIO()
            img.save(buffer, format="JPEG")
            buffer.seek(0)
            key = f"{S3_PREFIX}/{slug}/slide{i+1}.jpg"
            s3.upload_fileobj(buffer, AWS_BUCKET, key)
            urls.append(f"{DISPLAY_BASE}/{slug}/slide{i+1}.jpg")
        except:
            urls.append("https://via.placeholder.com/720x1200?text=Error")
    return urls

def upload_final_outputs(slide_data, html_content, json_key, html_key):
    s3 = boto3.client("s3", aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY, region_name=AWS_REGION)
    s3.put_object(Bucket=AWS_BUCKET, Key=json_key, Body=json.dumps(slide_data), ContentType="application/json")
    s3.put_object(Bucket=AWS_BUCKET, Key=html_key, Body=html_content, ContentType="text/html")

# === Streamlit UI ===
st.title("📘 Notes to Quiz Webstory Generator")

uploaded_images = st.file_uploader("📤 Upload Notes Images (5)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
html_template = st.file_uploader("📄 Upload HTML template", type="html")

if uploaded_images and html_template:
    st.info("📡 Uploading images to a temporary CDN...")
    note_image_urls = []
    s3 = boto3.client("s3", aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY, region_name=AWS_REGION)
    slug, json_key, html_key, json_url, html_url = generate_slug_and_urls()
    for idx, img in enumerate(uploaded_images):
        key = f"{S3_PREFIX}/{slug}/note{idx+1}.jpg"
        s3.upload_fileobj(img, AWS_BUCKET, key)
        note_image_urls.append(f"{DISPLAY_BASE}/{slug}/note{idx+1}.jpg")

    st.info("🧠 Summarizing with GPT Vision...")
    slides = summarize_notes_with_gpt_vision(note_image_urls)
    prompts = [s["image_prompt"] for s in slides]

    st.info("🎨 Generating and resizing DALL·E images...")
    final_image_urls = generate_and_resize_images(prompts, slug)

    st.info("📄 Rendering HTML & uploading JSON...")
    template_str = html_template.read().decode("utf-8")
    jinja = Template(template_str)
    rendered_html = jinja.render(slides=slides, image_urls=final_image_urls)
    upload_final_outputs(slides, rendered_html, json_key, html_key)

    st.success("✅ Files uploaded!")
    st.markdown(f"🔗 [View HTML]({html_url})")
    st.markdown(f"📥 [Download JSON]({json_url})")
    st.download_button("📥 Download HTML", data=rendered_html, file_name=f"{slug}.html", mime="text/html")
