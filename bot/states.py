from telebot.handler_backends import State, StatesGroup


class AdminStates(StatesGroup):
    waiting_excel = State()
    broadcast_waiting_text = State()
    broadcast_waiting_media = State()
    broadcast_confirming = State()


class FeedbackStates(StatesGroup):
    waiting_text = State()
    confirming = State()

class CallbackStates(StatesGroup):
    waiting_phone = State()
