import os
import uuid
import time
import json
import requests
import os
from PIL import Image


def analyze_video_for_titles(api_key, video_path, transcript=None):
    """
    Transcribes a video and uses Groq to suggest viral YouTube titles.
    If transcript is provided, skips Whisper transcription.
    Returns: { "titles": [...], "transcript_summary": "...", "language": "...", "segments": [...], "video_duration": ... }
    """
    if transcript is None:
        from main import transcribe_video
        print("🎬 [Thumbnail] Transcribing video...")
        transcript = transcribe_video(video_path)
    else:
        print("🎬 [Thumbnail] Using pre-computed transcript (Whisper already done)...")

    prompt = f"""You are a YouTube title expert who creates viral, click-worthy titles.

Analyze this video and its transcript, then suggest 10 YouTube titles that would maximize CTR (click-through rate).

TRANSCRIPT:
{transcript['text']}

RULES:
- Titles must be under 70 characters
- Use power words, curiosity gaps, and emotional triggers
- Mix styles: how-to, listicle, story-driven, controversial, question-based
- Make them specific to the actual content, not generic
- Include numbers where appropriate
- Consider the language of the video (detected: {transcript['language']})
- Titles should be in the SAME LANGUAGE as the video transcript

Also provide a brief summary of the video content (2-3 sentences).

After generating all 10 titles, pick the TOP 2 you most recommend and explain concisely WHY (CTR potential, emotional hook, uniqueness, etc.). Reference them by their 0-based index in the titles array.

OUTPUT JSON:
{{
    "titles": ["title1", "title2", ...],
    "transcript_summary": "Brief summary of the video content...",
    "language": "{transcript['language']}",
    "recommended": [
        {{"index": 0, "reason": "Why this title is best..."}},
        {{"index": 3, "reason": "Why this title is second best..."}}
    ]
}}"""

    print("🤖 [Thumbnail] Asking Groq for title suggestions...")
    # Call Groq HTTP endpoint
    groq_url = os.environ.get("GROQ_API_URL")
    groq_model = os.environ.get("GROQ_MODEL", "groq-1")
    groq_key = os.environ.get("GROQ_API_KEY") or api_key
    if not groq_url or not groq_key:
        raise Exception("GROQ_API_URL or GROQ_API_KEY not configured")

    headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
    payload = {"model": groq_model, "prompt": prompt}
    resp = requests.post(groq_url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    try:
        response_text = resp.json().get("output") or resp.json().get("text") or resp.text
    except Exception:
        response_text = resp.text

    # Extract segments and duration from transcript for later use
    segments = transcript.get("segments", [])
    video_duration = segments[-1]["end"] if segments else 0

    try:
        text = response_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            text = text[start_idx:end_idx + 1]

        result = json.loads(text)
        result["transcript_summary"] = result.get("transcript_summary", "")
        result["language"] = result.get("language", transcript["language"])
        result["segments"] = segments
        result["video_duration"] = video_duration
        return result
    except json.JSONDecodeError:
        print(f"❌ [Thumbnail] Failed to parse titles JSON: {response_text}")
        return {
            "titles": ["Could not generate titles - please try again"],
            "transcript_summary": transcript["text"][:500],
            "language": transcript["language"],
            "segments": segments,
            "video_duration": video_duration
        }


def refine_titles(api_key, context, user_message, conversation_history=None):
    """
    Takes video context + user feedback and returns refined title suggestions.
    """
    groq_url = os.environ.get("GROQ_API_URL")
    groq_model = os.environ.get("GROQ_MODEL", "groq-1")
    groq_key = os.environ.get("GROQ_API_KEY") or api_key
    if not groq_key or not groq_url:
        raise Exception("GROQ_API_KEY or GROQ_API_URL not configured for refine_titles.")

    history_text = ""
    if conversation_history:
        for msg in conversation_history:
            role = msg.get("role", "user")
            history_text += f"\n{role.upper()}: {msg['content']}"

    prompt = f"""You are a YouTube title expert. Based on the video context and the user's feedback, suggest 8 new refined YouTube titles.

VIDEO CONTEXT:
{context}

CONVERSATION HISTORY:{history_text}

USER'S NEW REQUEST:
{user_message}

RULES:
- Titles must be under 70 characters
- Incorporate the user's feedback/direction
- Keep titles viral and click-worthy
- If the user asks for a specific style, follow it
- Titles should be in the same language as the original content

OUTPUT JSON:
{{
    "titles": ["title1", "title2", ...]
}}"""

    headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
    payload = {
        "model": groq_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 1500
    }
    resp = requests.post(groq_url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    try:
        data = resp.json()
        if 'choices' in data and len(data['choices']) > 0:
            response_text = data['choices'][0].get('message', {}).get('content', '')
        else:
            response_text = data.get("output") or data.get("text") or resp.text
    except Exception:
        response_text = resp.text
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            text = text[start_idx:end_idx + 1]

        return json.loads(text)
    except json.JSONDecodeError:
        print(f"❌ [Thumbnail] Failed to parse refined titles: {response_text}")
        return {"titles": ["Could not refine titles - please try again"]}


def generate_thumbnail(api_key, title, session_id, face_image_path=None, bg_image_path=None, extra_prompt="", count=3, video_context=""):
    """
    Generates YouTube thumbnails using Groq image generation.
    Returns list of saved image paths (relative URLs).
    """
    groq_url = os.environ.get("GROQ_API_URL")
    groq_image_model = os.environ.get("GROQ_IMAGE_MODEL", os.environ.get("GROQ_MODEL", "groq-1"))
    groq_key = os.environ.get("GROQ_API_KEY") or api_key

    output_dir = os.path.join("output", "thumbnails", session_id)
    os.makedirs(output_dir, exist_ok=True)

    prompt_parts = []

    # Add face image if provided
    if face_image_path and os.path.exists(face_image_path):
        face_img = Image.open(face_image_path)
        prompt_parts.append(face_img)

    # Add background image if provided
    if bg_image_path and os.path.exists(bg_image_path):
        bg_img = Image.open(bg_image_path)
        prompt_parts.append(bg_img)

    # Build video context block
    context_block = ""
    if video_context:
        context_block = f"""
VIDEO CONTEXT (use this to understand the video and design a relevant thumbnail):
{video_context}
"""

    # Build extra instructions block (high priority)
    extra_block = ""
    if extra_prompt:
        extra_block = f"""
⚠️ MANDATORY USER INSTRUCTIONS (MUST follow these exactly — they override any default behavior):
{extra_prompt}
"""

    text_prompt = f"""Generate a professional, eye-catching YouTube thumbnail image.

VIDEO TITLE (for reference — do NOT put the full title on the thumbnail): "{title}"
{context_block}
TEXT ON THE THUMBNAIL:
- Based on the title AND the video context, create a SHORT visual hook: 1 to 5 words maximum
- It should capture the core emotion, surprise, or promise of the video
- The thumbnail text should COMPLEMENT the YouTube title (which appears below), not repeat it
- Examples: "$10K EN 30 DÍAS", "ESTO FUNCIONA", "NO LO SABÍAS", "GRATIS 🔥"
- Use ALL CAPS for maximum impact, split into 2-3 lines
{extra_block}
DESIGN REQUIREMENTS:
- The text MUST be large, bold, and high-contrast (readable at small sizes)
- Use vibrant, eye-catching colors that match the video's mood
- Professional YouTube thumbnail aesthetic
- Clean composition — text and face/subject as clear focal points
- NO clutter, NO small text, NO watermarks"""

    if face_image_path and os.path.exists(face_image_path):
        text_prompt += "\n- Include the provided face/person prominently with an exaggerated expression (surprise, excitement, shock)"

    if bg_image_path and os.path.exists(bg_image_path):
        text_prompt += "\n- Use the provided background image as the base/backdrop"

    prompt_parts.append(text_prompt)

    thumbnails = []
    last_error = None

    if not groq_url or not groq_key:
        raise Exception("GROQ_API_URL or GROQ_API_KEY not configured for thumbnail generation.")

    headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}

    for i in range(count):
        print(f"🎨 [Thumbnail] Generating thumbnail {i + 1}/{count}...")
        try:
            headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
            payload = {
                "model": groq_image_model,
                "messages": [{"role": "user", "content": prompt_parts}],
                "temperature": 0.9,
                "max_tokens": 3000
            }
            resp = requests.post(groq_url, headers=headers, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            
            # Extract images from response
            imgs = []
            if 'choices' in data and len(data['choices']) > 0:
                response_text = data['choices'][0].get('message', {}).get('content', '')
            else:
                response_text = data.get("output") or data.get("text") or resp.text

            if not imgs and isinstance(data.get('parts'), list):
                for p in data.get('parts'):
                    if isinstance(p, dict) and (p.get('image') or p.get('b64') or p.get('base64')):
                        imgs.append(p.get('image') or p.get('b64') or p.get('base64'))

            import base64
            saved = False
            for idx, b64 in enumerate(imgs):
                if isinstance(b64, dict):
                    b = b64.get('b64') or b64.get('base64') or b64.get('data')
                else:
                    b = b64
                if not b:
                    continue
                img_data = base64.b64decode(b)
                filename = f"thumb_{i + 1}_{idx}.jpg"
                filepath = os.path.join(output_dir, filename)
                with open(filepath, 'wb') as f:
                    f.write(img_data)
                thumbnails.append(f"/thumbnails/{session_id}/{filename}")
                print(f"✅ [Thumbnail] Saved: {filepath}")
                saved = True
                break

            if not saved:
                # No image produced
                last_error = f"No images in response: {data}"

        except Exception as e:
            last_error = str(e)
            print(f"❌ [Thumbnail] Generation {i + 1} failed: {e}")

    if not thumbnails and last_error:
        raise RuntimeError(f"All thumbnail generations failed. Last error: {last_error}")

    return thumbnails


def generate_youtube_description(api_key, title, transcript_segments, language, video_duration):
    """
    Uses Groq to generate a YouTube description with chapter markers from transcript segments.
    Returns: { "description": "full description text with chapters" }
    """
    groq_url = os.environ.get("GROQ_API_URL")
    groq_model = os.environ.get("GROQ_MODEL", "groq-1")
    groq_key = os.environ.get("GROQ_API_KEY") or api_key

    # Format segments for the prompt
    formatted_segments = []
    for seg in transcript_segments:
        start = seg.get("start", 0)
        mins = int(start // 60)
        secs = int(start % 60)
        timestamp = f"{mins}:{secs:02d}"
        formatted_segments.append(f"[{timestamp}] {seg.get('text', '').strip()}")

    segments_text = "\n".join(formatted_segments)

    # Format total duration
    dur_mins = int(video_duration // 60)
    dur_secs = int(video_duration % 60)
    duration_str = f"{dur_mins}:{dur_secs:02d}"

    prompt = f"""You are a YouTube SEO expert. Generate a complete YouTube video description for the following video.

VIDEO TITLE: "{title}"
VIDEO LANGUAGE: {language}
VIDEO DURATION: {duration_str}

TRANSCRIPT WITH TIMESTAMPS:
{segments_text}

REQUIREMENTS:
1. Write the description in the SAME LANGUAGE as the video ({language})
2. Start with a compelling 2-3 sentence summary/hook
3. Add relevant CTAs (subscribe, like, comment)
4. Generate YouTube CHAPTERS based on the transcript timestamps:
   - First chapter MUST start at 0:00
   - Minimum 3 chapters, each at least 10 seconds apart
   - Chapter titles should be concise and descriptive
   - Format: 0:00 Chapter Title
   - Place chapters in their own section with a blank line before and after
5. Add 5-10 relevant hashtags at the end
6. Keep the total description under 5000 characters

OUTPUT: Return ONLY the description text (no JSON wrapper, no markdown code blocks). The description should be ready to paste directly into YouTube."""

    if not groq_url or not groq_key:
        raise Exception("GROQ_API_URL or GROQ_API_KEY not configured for description generation.")

    headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
    payload = {
        "model": groq_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 2500
    }
    resp = requests.post(groq_url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    try:
        data = resp.json()
        if 'choices' in data and len(data['choices']) > 0:
            description = data['choices'][0].get('message', {}).get('content', '')
        else:
            description = data.get('output') or data.get('text') or resp.text
    except Exception:
        description = resp.text
    if description.startswith("```"):
        lines = description.split("\n")
        description = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    return {"description": description}
