from aiogram.fsm.state import State, StatesGroup


class ManualPostStates(StatesGroup):
    waiting_photos = State()
    waiting_text = State()
    preview = State()


class AutoWizardStates(StatesGroup):
    model = State()
    year = State()
    price = State()
    limit = State()
