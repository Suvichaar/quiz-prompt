import streamlit as st
from PIL import Image
from io import BytesIO
import base64, requests, json, time, string, random, re
from datetime import datetime, timezone
import boto3

# ========== 🔐 Secrets ==========
AZURE_API_KEY     = st.secrets["AZURE_API_KEY"]
AZURE_ENDPOINT    = st.secrets["AZURE_ENDPOINT"]
AZURE_DEPLOYMENT  = st.secrets["AZURE_DEPLOYMENT"]
AZURE_API_VERSION = st.secrets["AZURE_API_VERSION"]
DAALE_KEY         = st.secrets["DAALE_KEY"]

AWS_ACCESS_KEY    = st.secrets["AWS_ACCESS_KEY"]
AWS_SECRET_KEY    = st.secrets["AWS_SECRET_KEY"]
AWS_REGION        = st.secrets["AWS_REGION"]
AWS_BUCKET        = st.secrets["AWS_BUCKET"]
S3_PREFIX         = "media"
DISPLAY_BASE      = "https://media.suvichaar.org"
DEFAULT_ERROR_IMAGE = f"{DISPLAY_BASE}/default-error.jpg"

# ========== 🔧 Utility Functions ==========
def generate_slug_and_urls(title):
    slug = ''.join(c for c in title.lower().replace(" ", "-") if c in string.ascii_lowercase + string.digits + '-')
    nano = ''.join(random.choices(string.ascii_letters + string.digits, k=10)) + '_G'
    slug_nano = f"{slug}_{nano}"
    return nano, slug_nano, f"https://suvichaar.org/stories/{slug_nano}", f"https://stories.suvichaar.org/{slug_nano}.html"

def fill_placeholders_from_html(template_html: str, replacements: dict) -> str:
    def replace_match(match):
        key = match.group(1).strip()
        return replacements.get(key, match.group(0))
    return re.sub(r"\{\{(.*?)\}\}", replace_match, template_html)

# ========== 🧠 GPT-4 Vision Prompt ==========
def analyze_image(base64_img):
    prompt = """
You are a helpful assistant. The user has uploaded a notes image.

Your job:
1. Extract a short and catchy title → storytitle
2. Break down content into 5 slide summaries (s2paragraph1 to s6paragraph1). Each must be a single sentence no longer than 200 characters.
3. For each paragraph (including the title), generate a vivid, multi-color vector-style DALL·E image prompt (1024x1024, flat illustration, minimal text, clean lines, colorful) → s1alt1 to s6alt1

Respond strictly in this JSON format:
{
  "storytitle": "...",
  "s2paragraph1": "...",
  "s3paragraph1": "...",
  "s4paragraph1": "...",
  "s5paragraph1": "...",
  "s6paragraph1": "...",
  "s1alt1": "...",
  "s2alt1": "...",
  "s3alt1": "...",
  "s4alt1": "...",
  "s5alt1": "...",
  "s6alt1": "..."
}
"""
    url = f"{AZURE_ENDPOINT}/openai/deployments/{AZURE_DEPLOYMENT}/chat/completions?api-version={AZURE_API_VERSION}"
    headers = {"Content-Type": "application/json", "api-key": AZURE_API_KEY}
    payload = {
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}]}
        ],
        "temperature": 0.7,
        "max_tokens": 1000
    }
    res = requests.post(url, headers=headers, json=payload)
    if res.status_code == 200:
        try:
            return json.loads(res.json()["choices"][0]["message"]["content"])
        except:
            st.error("⚠️ Invalid JSON returned.")
    else:
        st.error(f"❌ Error: {res.status_code} - {res.text}")
    return None

# ========== 🎨 Image Generation ==========
def generate_and_upload_images(result, slug):
    dalle_url = "https://njnam-m3jxkka3-swedencentral.cognitiveservices.azure.com/openai/deployments/dall-e-3/images/generations?api-version=2024-02-01"
    headers = {"Content-Type": "application/json", "api-key": DAALE_KEY}
    s3 = boto3.client("s3", aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY, region_name=AWS_REGION)

    for i in range(1, 7):
        prompt = result.get(f"s{i}alt1", "")
        payload = {"prompt": prompt, "n": 1, "size": "1024x1024"}

        for _ in range(3):
            res = requests.post(dalle_url, headers=headers, json=payload)
            if res.status_code == 200:
                image_url = res.json()["data"][0]["url"]
                try:
                    img_data = requests.get(image_url).content
                    img = Image.open(BytesIO(img_data)).convert("RGB")
                    img = img.resize((720, 1200))
                    buffer = BytesIO()
                    img.save(buffer, format="JPEG")
                    buffer.seek(0)
                    key = f"{S3_PREFIX}/{slug}/slide{i}.jpg"
                    s3.upload_fileobj(buffer, AWS_BUCKET, key)
                    result[f"s{i}image1"] = f"{DISPLAY_BASE}/{key}"
                    break
                except:
                    result[f"s{i}image1"] = DEFAULT_ERROR_IMAGE
            elif res.status_code == 429:
                time.sleep(10)
        else:
            result[f"s{i}image1"] = DEFAULT_ERROR_IMAGE

    try:
        if result["s1image1"] != DEFAULT_ERROR_IMAGE:
            img_data = requests.get(result["s1image1"]).content
            img = Image.open(BytesIO(img_data)).convert("RGB")
            img = img.resize((640, 853))
            buffer = BytesIO()
            img.save(buffer, format="JPEG")
            buffer.seek(0)
            key = f"{S3_PREFIX}/{slug}/portrait_cover.jpg"
            s3.upload_fileobj(buffer, AWS_BUCKET, key)
            result["potraitcoverurl"] = f"{DISPLAY_BASE}/{key}"
        else:
            result["potraitcoverurl"] = DEFAULT_ERROR_IMAGE
    except:
        result["potraitcoverurl"] = DEFAULT_ERROR_IMAGE

    return result

# ========== 🧾 SEO Metadata ==========
def generate_seo_metadata(result):
    seo_prompt = f"""
Generate SEO metadata for a web story with the following title and slide summaries.

Title: {result['storytitle']}
Slides:
- {result.get('s2paragraph1', '')}
- {result.get('s3paragraph1', '')}
- {result.get('s4paragraph1', '')}
- {result.get('s5paragraph1', '')}
- {result.get('s6paragraph1', '')}

Respond strictly in this JSON format:
{{"metadescription": "...", "metakeywords": "..." }}
"""
    url = f"{AZURE_ENDPOINT}/openai/deployments/{AZURE_DEPLOYMENT}/chat/completions?api-version={AZURE_API_VERSION}"
    headers = {"Content-Type": "application/json", "api-key": AZURE_API_KEY}
    payload = {
        "messages": [
            {"role": "system", "content": "You are an expert SEO assistant."},
            {"role": "user", "content": seo_prompt}
        ],
        "temperature": 0.5,
        "max_tokens": 300
    }
    res = requests.post(url, headers=headers, json=payload)
    if res.status_code == 200:
        try:
            metadata = json.loads(res.json()["choices"][0]["message"]["content"])
            return metadata.get("metadescription", ""), metadata.get("metakeywords", "")
        except:
            return "", ""
    return "", ""

# ========== 🖼️ Main App ==========
st.title("📚 Notes to AMP Web Story Generator")

image_file = st.file_uploader("Upload Notes Image (JPG or PNG)", type=["jpg", "jpeg", "png"])
html_template = st.file_uploader("Upload HTML Template (with {{placeholders}})", type=["html"])

if image_file and html_template and st.button("🚀 Generate Story"):
    img_bytes = image_file.read()
    image = Image.open(BytesIO(img_bytes))
    st.image(image, caption="Uploaded Image", use_column_width=True)
    base64_img = base64.b64encode(img_bytes).decode("utf-8")

    result = analyze_image(base64_img)
    if result:
        nano, slug_nano, display_url, _ = generate_slug_and_urls(result["storytitle"])
        result = generate_and_upload_images(result, slug_nano)
        meta_desc, meta_keywords = generate_seo_metadata(result)
        result["metadescription"] = meta_desc
        result["metakeywords"] = meta_keywords

        html_template_str = html_template.read().decode("utf-8")
        html_filled = fill_placeholders_from_html(html_template_str, result)
        html_filled = html_filled.replace("{{canurl}}", display_url)
        html_filled = html_filled.replace("{{potraightcoverurl}}", result.get("potraitcoverurl", DEFAULT_ERROR_IMAGE))
        now_iso = datetime.now(timezone.utc).isoformat(timespec='seconds')
        html_filled = html_filled.replace("{{publishedtime}}", now_iso)
        html_filled = html_filled.replace("{{modifiedtime}}", now_iso)

        st.download_button("📥 Download HTML", html_filled, file_name=f"{slug_nano}.html", mime="text/html")
        st.download_button("📥 Download JSON", json.dumps(result, indent=2), file_name=f"{slug_nano}.json", mime="application/json")

        st.success("🎉 Story generated successfully!")
        st.markdown(f"🌐 [Preview Web Story]({display_url})")
