import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

FEEDBACK_DIR = os.path.join(os.path.dirname(__file__), '..', 'feedback_data')
os.makedirs(FEEDBACK_DIR, exist_ok=True)


def save_feedback(uid: int, label: str, email_text: str):
    """Сохраняет обратную связь в JSON файл"""
    try:
        feedback = {
            "uid": uid,
            "label": label,
            "timestamp": datetime.now().isoformat(),
            "email": email_text[:1000]
        }

        # Сохраняем в общий файл
        all_feedback_path = os.path.join(FEEDBACK_DIR, 'all_feedback.json')
        if os.path.exists(all_feedback_path):
            with open(all_feedback_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = []

        data.append(feedback)

        with open(all_feedback_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Feedback saved for UID={uid}")
        return True

    except Exception as e:
        logger.error(f"Error saving feedback: {str(e)}")
        return False