"""
video_uretim.py - Video üretim motoru arayüzü ve çalıştırıcısı.
video_motoru_openmontage modülünü dışa aktarır ve doğrudan çalıştırılabilir.
"""

from video_motoru_openmontage import (
    run_pipeline,
)

if __name__ == "__main__":
    import sys

    sen_path = sys.argv[1] if len(sys.argv) > 1 else None
    run_pipeline(sen_path)
