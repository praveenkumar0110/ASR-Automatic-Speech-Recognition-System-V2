# import os
# import re
# import whisper
# from django.http import JsonResponse
# from django.views.decorators.csrf import csrf_exempt
# from django.conf import settings
# from pymongo import MongoClient

# # ================= MongoDB =================
# client = MongoClient("mongodb://localhost:27017/")
# db = client["audio_transcript_db"]
# collection = db["audio_results"]

# # ================= Whisper =================
# model = whisper.load_model("base")


# # ================= Helper =================
# def normalize(word: str) -> str:
#     """lowercase + remove punctuation"""
#     return re.sub(r"[^\w]", "", word.lower())


# # ================= Main API =================
# @csrf_exempt
# def process_audio(request):
#     if request.method != "POST":
#         return JsonResponse({"error": "POST required"}, status=400)

#     audio_file = request.FILES.get("audio")
#     template_name = request.POST.get("template")

#     if not audio_file or not template_name:
#         return JsonResponse(
#             {"error": "audio or template missing"},
#             status=400
#         )

#     # -------- STEP 1: SAVE AUDIO --------
#     audio_dir = os.path.join(settings.MEDIA_ROOT, "audio")
#     os.makedirs(audio_dir, exist_ok=True)

#     audio_path = os.path.join(audio_dir, audio_file.name)
#     with open(audio_path, "wb+") as f:
#         for chunk in audio_file.chunks():
#             f.write(chunk)

#     # -------- STEP 2: TRANSCRIBE --------
#     result = model.transcribe(
#         audio_path,
#         word_timestamps=True
#     )

#     language = result.get("language")

#     # -------- STEP 3: BUILD FULL TRANSCRIPT ARRAY --------
#     transcript = []
#     for seg in result["segments"]:
#         for w in seg.get("words", []):
#             transcript.append({
#                 "word": normalize(w["word"]),
#                 "start": round(w["start"], 3),
#                 "end": round(w["end"], 3)
#             })

#     # -------- STEP 4: READ TEMPLATE --------
#     template_path = os.path.join(
#         settings.MEDIA_ROOT,
#         "templates_text",
#         template_name
#     )

#     if not os.path.exists(template_path):
#         return JsonResponse(
#             {"error": "Template file not found"},
#             status=404
#         )

#     with open(template_path, "r") as f:
#         template_words = {
#             normalize(w)
#             for w in f.read().split()
#             if normalize(w)
#         }

#     # -------- STEP 5: FIND COMMON WORDS --------
#     common_words = []

#     for w in transcript:
#         if w["word"] in template_words:
#             common_words.append({
#                 "word": w["word"],
#                 "start": w["start"],
#                 "end": w["end"]
#             })

#     # -------- STEP 6: SAVE TO MONGODB --------
#     doc = {
#         "audio": audio_file.name,
#         "language": language,
#         "transcript": transcript,
#         "common_words": common_words
#     }

#     inserted = collection.insert_one(doc)

#     # -------- STEP 7: RESPONSE --------
#     return JsonResponse(
#         {
#             "_id": str(inserted.inserted_id),
#             "audio": audio_file.name,
#             "language": language,
#             "transcript": transcript,
#             "common_words": common_words
#         },
#         json_dumps_params={"indent": 2}
#     )
import os
import re
import whisper
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from pymongo import MongoClient
from pydub import AudioSegment

# ================= MongoDB =================
client = MongoClient("mongodb://localhost:27017/")
db = client["audio_transcript_db"]
collection = db["audio_results"]

# ================= Whisper =================
model = whisper.load_model("base")


# ================= Helper =================
def normalize(word: str) -> str:
    """Lowercase + remove punctuation"""
    return re.sub(r"[^\w]", "", word.lower())


# ================= Main API =================
@csrf_exempt
def process_audio(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=400)

    audio_file = request.FILES.get("audio")
    template_name = request.POST.get("template")

    if not audio_file or not template_name:
        return JsonResponse(
            {"error": "audio or template missing"},
            status=400
        )

    # -------- STEP 1: SAVE AUDIO --------
    audio_dir = os.path.join(settings.MEDIA_ROOT, "audio")
    os.makedirs(audio_dir, exist_ok=True)

    audio_path = os.path.join(audio_dir, audio_file.name)
    with open(audio_path, "wb+") as f:
        for chunk in audio_file.chunks():
            f.write(chunk)

    # -------- STEP 2: TRANSCRIBE AUDIO --------
    result = model.transcribe(
        audio_path,
        word_timestamps=True
    )

    language = result.get("language")

    # -------- STEP 3: BUILD FULL TRANSCRIPT --------
    transcript = []
    for seg in result["segments"]:
        for w in seg.get("words", []):
            transcript.append({
                "word": normalize(w["word"]),
                "start": round(w["start"], 3),
                "end": round(w["end"], 3)
            })

    # -------- STEP 4: READ TEMPLATE --------
    template_path = os.path.join(
        settings.MEDIA_ROOT,
        "templates_text",
        template_name
    )

    if not os.path.exists(template_path):
        return JsonResponse(
            {"error": "Template file not found"},
            status=404
        )

    with open(template_path, "r") as f:
        template_words = {
            normalize(w)
            for w in f.read().split()
            if normalize(w)
        }

    # -------- STEP 5: FIND COMMON WORDS --------
    common_words = [
        w for w in transcript if w["word"] in template_words
    ]

    # 🔑 base name from audio (USED EVERYWHERE)
    base_name = os.path.splitext(audio_file.name)[0]

    # -------- STEP 6: SAVE COMMON WORDS TXT (UNIQUE) --------
    common_dir = os.path.join(settings.MEDIA_ROOT, "common_words")
    os.makedirs(common_dir, exist_ok=True)

    common_txt_filename = f"{base_name}_common_words.txt"
    common_txt_path = os.path.join(common_dir, common_txt_filename)

    with open(common_txt_path, "w") as f:
        for w in common_words:
            f.write(f"{w['word']} -> {w['start']}s - {w['end']}s\n")

    # -------- STEP 7: BUILD ONE COMBINED AUDIO (UNIQUE) --------
    original_audio = AudioSegment.from_file(audio_path)
    combined_audio = AudioSegment.silent(duration=0)

    for w in common_words:
        start_ms = int(w["start"] * 1000)
        end_ms = int(w["end"] * 1000)
        combined_audio += original_audio[start_ms:end_ms]

    clips_dir = os.path.join(settings.MEDIA_ROOT, "audio_clips")
    os.makedirs(clips_dir, exist_ok=True)

    combined_audio_filename = f"{base_name}_common_words.wav"
    combined_audio_path = os.path.join(
        clips_dir, combined_audio_filename
    )

    combined_audio.export(combined_audio_path, format="wav")

    # -------- STEP 8: SAVE TO MONGODB --------
    doc = {
        "audio": audio_file.name,
        "language": language,
        "transcript": transcript,
        "common_words": common_words,
        "files": {
            "common_audio": combined_audio_filename,
            "common_text": common_txt_filename
        }
    }

    inserted = collection.insert_one(doc)

    # -------- STEP 9: RESPONSE --------
    return JsonResponse(
        {
            "_id": str(inserted.inserted_id),
            "audio": audio_file.name,
            "language": language,
            "transcript": transcript,
            "common_words": common_words,
            "common_audio": combined_audio_filename,
            "common_text": common_txt_filename
        },
        json_dumps_params={"indent": 2}
    )
