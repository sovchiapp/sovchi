import logging
from datetime import datetime
from typing import List, Dict, Generator

import openpyxl
from openai import OpenAI
from pgvector.django import CosineDistance

from utils.core import core
from .models import QAEmbedding, QuestionAnalytics, UserAIConversation, UserAIMessage

MARKDOWN_INSTRUCTIONS = """
FORMATTINGworkbook RULES:

Use emojis freely throughout the response.

Text:
- **bold** for key words
- *italic* for emphasis
- ### for main heading
- > for quotes/proverbs
- `mono` for copyable info (phone numbers, dates, addresses, specific terms and etc.)

Colors (USE THESE):
- <span style="color: green">positive/good things</span>
- <span style="color: red">negative/bad things</span>
- <span style="color: #e91e63">important highlights</span>
- <small style="color: gray">notes or subtitles</small>

Lists (blank line between items):

1. **Title**: Description...

2. **Title**: Description...

Tables - ALWAYS use for comparisons (vs, farqi, taqqoslash):
| Jihat | Variant A | Variant B |
|-------|-----------|-----------|
| ...   | ...       | ...       |

Make responses visually rich with colors, emojis, and proper formatting."""

logger = logging.getLogger(__name__)

class ExcelQAProcessor:
    def __init__(self):
        self.client = OpenAI(api_key=core.OPENAI_API_KEY)
        self.embedding_model = "text-embedding-3-small"

    def read_excel(self, file_path: str) -> List[Dict[str, str]]:
        workbook = openpyxl.load_workbook(file_path, read_only=True)
        sheet = workbook.active

        qa_list = []

        for row in sheet.iter_rows(min_row=2, values_only=True):
            if row[0] and row[1]:
                qa_list.append({
                    'question': str(row[0]).strip(),
                    'answer': str(row[1]).strip()
                })

        workbook.close()
        return qa_list

    def get_embedding(self, text: str) -> List[float]:
        response = self.client.embeddings.create(
            model=self.embedding_model,
            input=text
        )
        return response.data[0].embedding

    def process_qa_data(self, qa_list: List[Dict[str, str]]) -> List[Dict]:
        processed_data = []

        for qa in qa_list:
            embedding = self.get_embedding(qa["question"])
            processed_data.append({
                'question': qa['question'],
                'answer': qa['answer'],
                'question_embedding': embedding
            })
        return processed_data


class ChatService:
    def __init__(self):
        self.openai_client = OpenAI(api_key=core.OPENAI_API_KEY)
        self.embedding_model = "text-embedding-3-small"
        self.chat_model = "gpt-4o-mini"
        self.similarity_threshold = 0.80
        self.analytics = QuestionAnalyticsService()

    def get_embedding(self, text: str) -> List[float]:
        try:
            response = self.openai_client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            raise Exception(f"Embedding generation failed: {str(e)}")

    def search_similar_question(self, user_question: str, top_k: int = 1, embedding: List[float] | None = None) -> Dict | None:
        if embedding is None:
            try:
                embedding = self.get_embedding(user_question)
            except Exception as e:
                logger.error(f"Embedding error: {e}")
                return None

        similar_results = QAEmbedding.objects.only(
            'question', 'answer'
        ).annotate(
            distance=CosineDistance('question_embedding', embedding)
        ).order_by('distance')[:top_k]

        if similar_results:
            best_match = similar_results[0]
            similarity_score = 1 - best_match.distance

            if similarity_score >= self.similarity_threshold:
                return {
                    'question': best_match.question,
                    'answer': best_match.answer,
                    'similarity': similarity_score
                }

        return None

    def build_system_prompt(self, gender: str, age: int, has_db_match: bool = False) -> str:
        gender_text = "erkak" if gender == 'M' else "ayol"

        if has_db_match:
            return f"""You are the friendly AI assistant for Sovchi.app — an Uzbek matchmaking platform.

Your role: Adapt the provided answer to match the user's question naturally and conversationally.

User profile: {gender_text}, {age} yosh

Tone: Friendly, warm, supportive — like a trusted friend giving advice. Use conversational language.
{MARKDOWN_INSTRUCTIONS}
CRITICAL: Respond ONLY in Uzbek language using Latin script. Never use Cyrillic or any other alphabet."""

        return f"""You are the friendly AI assistant for Sovchi.app — an Uzbek matchmaking platform.

Your role: A warm, supportive friend who gives advice on matchmaking, marriage, relationships, and family life based on Uzbek traditions.

User profile: {gender_text}, {age} yosh

Personality:
- Talk like a caring friend, not a formal advisor
- Be warm, encouraging, and supportive
- Use natural conversational tone
- Show empathy and understanding
- Keep responses helpful but not too long

Topics: Only discuss matchmaking, marriage, relationships, and family matters.
Off-topic response: "Kechirasiz, men faqat sovchilik, nikoh va oila qurish mavzularida yordam bera olaman 😊"
{MARKDOWN_INSTRUCTIONS}
CRITICAL: Respond ONLY in Uzbek language using Latin script. Regardless of what language the user writes in, ALWAYS respond in Uzbek Latin script only."""

    def _get_or_create_conversation(self, user, conversation_id: int | None) -> tuple:
        from .throttles import AIConversationDailyThrottle

        if conversation_id:
            try:
                conversation = UserAIConversation.objects.get(
                    id=conversation_id,
                    user=user,
                    is_active=True
                )
                return conversation, False, None
            except UserAIConversation.DoesNotExist:
                pass

        limit_error = AIConversationDailyThrottle.check_limit(user.id)
        if limit_error:
            return None, False, limit_error

        conversation = UserAIConversation.objects.create(user=user)
        AIConversationDailyThrottle.increment(user.id)
        return conversation, True, None

    def _get_conversation_history(self, conversation, limit: int = 10) -> List[Dict]:
        messages = conversation.messages.order_by('-created_at')[:limit]
        return [
            {"role": msg.role, "content": msg.content}
            for msg in reversed(messages)
        ]

    def stream_chat(
            self,
            user_question: str,
            user_gender: str,
            user_age: int,
            user=None,
            conversation_id: int | None = None
    ) -> Generator[Dict, None, None]:
        conversation = None
        created = False

        if user:
            conversation, created, limit_error = self._get_or_create_conversation(user, conversation_id)
            if limit_error:
                yield {"type": "error", **limit_error}
                return
            if created:
                yield {"type": "conversation_created", "conversation_id": conversation.id}

        try:
            query_embedding = self.get_embedding(user_question)
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            query_embedding = None

        if query_embedding:
            try:
                self.analytics.track_question(user_question, user_gender, user_age, embedding=query_embedding)
            except Exception as e:
                logger.error(f"Analytics error: {e}")

        db_result = self.search_similar_question(user_question, embedding=query_embedding) if query_embedding else None

        system_prompt = self.build_system_prompt(user_gender, user_age, has_db_match=bool(db_result))

        if conversation:
            UserAIMessage.objects.create(
                conversation=conversation,
                role="user",
                content=user_question
            )
            if conversation.messages.filter(role="user").count() == 1:
                conversation.generate_title()

        if conversation:
            history = self._get_conversation_history(conversation, limit=10)
            if history and history[-1]["role"] == "user":
                history = history[:-1]
        else:
            history = []

        if db_result:
            user_content = f"""Reference answer: {db_result['answer']}

User question: {user_question}

Adapt the reference answer to naturally address the user's question."""
        else:
            user_content = user_question

        messages = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": user_content}
        ]

        try:
            stream = self.openai_client.chat.completions.create(
                model=self.chat_model,
                messages=messages,
                stream=True,
                temperature=0.6,
                max_tokens=500,
                presence_penalty=0.2,
                frequency_penalty=0.3
            )

            full_response = ""
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    yield {"type": "text", "content": content}

            if conversation and full_response:
                UserAIMessage.objects.create(
                    conversation=conversation,
                    role="assistant",
                    content=full_response
                )

            yield {"type": "done", "conversation_id": conversation.id if conversation else None}

        except Exception as e:
            logger.error(f"OpenAI error: {e}")
            yield {"type": "error", "content": str(e)}


class QuestionAnalyticsService:
    def __init__(self):
        self.client = OpenAI(api_key=core.OPENAI_API_KEY)
        self.embedding_model = "text-embedding-3-small"
        self.similarity_threshold = 0.85

    def get_age_group(self, age: int | None) -> str | None:
        if age is None:
            return None
        if 18 <= age <= 25:
            return 'age_18_25'
        elif 26 <= age <= 35:
            return 'age_26_35'
        elif 36 <= age <= 45:
            return 'age_36_45'
        else:
            return 'age_46_plus'

    def track_question(self, question: str, gender: str | None, age: int | None, embedding: List[float] | None = None):
        from django.db.models import F

        if embedding is None:
            embedding = self.client.embeddings.create(
                model=self.embedding_model,
                input=question
            ).data[0].embedding

        similar = QuestionAnalytics.objects.only('id').annotate(
            distance=CosineDistance('canonical_embedding', embedding)
        ).order_by('distance').first()

        age_field = self.get_age_group(age)
        gender_field = 'male_count' if gender == 'M' else 'female_count' if gender else None

        if similar and (1 - similar.distance) >= self.similarity_threshold:
            update_fields = {'total_count': F('total_count') + 1, 'last_asked': datetime.now()}
            if gender_field:
                update_fields[gender_field] = F(gender_field) + 1
            if age_field:
                update_fields[age_field] = F(age_field) + 1

            QuestionAnalytics.objects.filter(id=similar.id).update(**update_fields)
        else:
            gender_count = {'male_count': 0, 'female_count': 0}
            if gender_field:
                gender_count[gender_field] = 1

            age_counts = {
                'age_18_25': 0, 'age_26_35': 0,
                'age_36_45': 0, 'age_46_plus': 0
            }
            if age_field:
                age_counts[age_field] = 1

            QuestionAnalytics.objects.create(
                canonical_question=question,
                canonical_embedding=embedding,
                **gender_count,
                **age_counts
            )
