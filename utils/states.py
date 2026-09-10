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
    waiting_regular_polls = State()  # Anonim viktorina — har savoldan keyin javob so'raladi
    set_poll_time  = State()
    upload_file    = State()
    upload_files_multi = State()  # Ko'p fayl: fayllar yuborilyapti, navbatga qo'yiladi
    multi_mode_choice  = State()  # Ko'p fayl: "Alohida" yoki "Birlashtirilgan" tanlanadi
    reupload_file  = State()
    set_subject    = State()
    set_title      = State()
    set_difficulty = State()
    set_time_limit = State()
    set_passing    = State()
    set_attempts   = State()
    set_visibility = State()
    set_ref_count  = State()   # Referal soni

class AdminPanel(StatesGroup):
    broadcast         = State()
    block_user        = State()
    delete_test       = State()
    group_broadcast   = State()
    fj_add            = State()
    find_test         = State()  # Kod orqali test qidirish
    waiting_json      = State()  # /import_json — tayyor JSON test fayllari kutilmoqda
    premium_manage    = State()  # Premium ID boshqaruvi

class ContactAdmin(StatesGroup):
    waiting_message = State()

class AllowedUsersState(StatesGroup):
    waiting_ids = State()

class EditTestTitle(StatesGroup):
    waiting_title = State()

class SplitTestSt(StatesGroup):
    waiting_count = State()
