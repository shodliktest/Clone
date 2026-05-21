"""📌 FSM States"""
from aiogram.fsm.state import State, StatesGroup

class TestSolving(StatesGroup):
    answering   = State()
    text_answer = State()
    paused      = State()

class PollTest(StatesGroup):
    active = State()
    paused = State()

class CreateTest(StatesGroup):
    choose_method  = State()
    waiting_polls  = State()
    set_poll_time  = State()
    upload_file    = State()
    set_subject    = State()
    set_title      = State()
    set_difficulty = State()
    set_time_limit = State()
    set_passing    = State()
    set_attempts   = State()
    set_visibility = State()

class AdminPanel(StatesGroup):
    broadcast         = State()
    block_user        = State()
    delete_test       = State()
    group_broadcast   = State()

class ContactAdmin(StatesGroup):
    waiting_message = State()

class AllowedUsersState(StatesGroup):
    waiting_ids = State()

class EditTestTitle(StatesGroup):
    waiting_title = State()
