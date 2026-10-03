"""
video_uretim.py - Video üretim motoru arayüzü ve çalıştırıcısı.
video_motoru modülünü dışa aktarır ve doğrudan çalıştırılabilir.
"""

from video_motoru_openmontage import (
    RUNWAY_API_KEY,
    GEMINI_API_KEY,
    URETIM_MODU,
    generate_audio,
    generate_image_and_convert_to_video,
    generate_video,
    merge_media,
    concat_videos,
    run_pipeline,
)

if __name__ == "__main__":
    import sys
    sen_path = sys.argv[1] if len(sys.argv) > 1 else None
    run_pipeline(sen_path)
