from datetime import datetime
from os import path, remove

from celery import shared_task
from requests import post

from utils.core import core
from .models import QAEmbedding
from .services import ExcelQAProcessor


@shared_task(bind=True)
def process_excel_and_create_embeddings(self, file_path: str):
    try:
        processor = ExcelQAProcessor()

        self.update_state(state='PROGRESS', meta={'status': 'Excel o\'qilmoqda...'})
        qa_list = processor.read_excel(file_path)
        total = len(qa_list)

        embeddings_to_create = []

        for index, qa in enumerate(qa_list, 1):
            self.update_state(
                state='PROGRESS',
                meta={
                    'status': f'Embedding yaratilmoqda {index}/{total}',
                    'current': index,
                    'total': total
                }
            )

            embedding = processor.get_embedding(qa['question'])

            embeddings_to_create.append(
                QAEmbedding(
                    question=qa['question'],
                    answer=qa['answer'],
                    question_embedding=embedding
                )
            )

        QAEmbedding.objects.bulk_create(embeddings_to_create, batch_size=100)

        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        message_text = (
            f"✅ Excel fayl muvaffaqiyatli qayta ishlandi!\n\n"
            f"📊 Umumiy savol-javoblar soni: {total}\n\n"
            f"⏱ Vaqt: {current_time}"
        )

        payload = {
            "chat_id": core.ADMIN_TG_ID,
            "text": message_text,
            "protect_content": True
        }

        post(
            f"https://api.telegram.org/bot{core.CLIENT_BOT_TOKEN}/sendMessage",
            data=payload,
            timeout=5
        )

        return {
            'status': 'success',
            'message': f'{total} ta savol-javob muvaffaqiyatli yuklandi',
            'total': total
        }

    except Exception as e:
        error_text = (
            f"❌ Excel faylni qayta ishlashda xatolik yuz berdi!\n\n"
            f"Xatolik: {str(e)}"
        )

        post(
            f"https://api.telegram.org/bot{core.CLIENT_BOT_TOKEN}/sendMessage",
            data={"chat_id": core.ADMIN_TG_ID, "text": error_text, "protect_content": True},
            timeout=5
        )

        return {
            'status': 'error',
            'message': str(e)
        }

    finally:
        if path.exists(file_path):
            remove(file_path)
