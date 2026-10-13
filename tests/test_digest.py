"""Дайджест, разбор критичных пунктов и фильтр почты — без сети."""

from email.message import EmailMessage

from ai.digest import MAX_TEXT_CHARS, build_prompt, extract_critical
from integrations.mail import decode_str, get_text, is_service_sender

DIGEST = """🔴 КРИТИЧНО
1. Филиал 3: остановилась линия, нужен инженер — Ержан
2. Клиент ТОО «Пример» грозит расторжением договора

🟡 ВАЖНО
1. Согласовать график отпусков

⚪ ФОН
1. Поздравления с днём рождения"""


def test_extract_critical_takes_only_red_section():
    critical = extract_critical(DIGEST)
    assert len(critical) == 2
    assert critical[0].startswith("1. Филиал 3")
    assert not any("отпусков" in line for line in critical)


def test_extract_critical_empty_when_nothing_urgent():
    assert extract_critical("🔵 ИНФОРМАЦИЯ\n1. Всё спокойно") == []


def test_prompt_labels_sources_and_trims_long_text():
    messages = [
        {"source": "telegram", "sender": "Айгерим", "text": "x" * 500, "time": "09:00"},
        {"source": "email", "sender": "client@example.com", "text": "Счёт на оплату", "time": "09:10"},
        {"source": "bitrix", "sender": "Bitrix24", "text": "Задача: отгрузка", "time": "08:00"},
    ]
    prompt = build_prompt(messages)
    assert "[Telegram] Айгерим" in prompt
    assert "[Почта]" in prompt and "[Bitrix24]" in prompt
    assert "x" * MAX_TEXT_CHARS in prompt
    assert "x" * (MAX_TEXT_CHARS + 1) not in prompt, "текст режется под лимит токенов Groq"


def test_service_senders_are_skipped():
    assert is_service_sender("HeadHunter <noreply@hh.kz>")
    assert is_service_sender("Newsletter <news@shop.kz>")
    assert not is_service_sender("Марат <marat@example.com>")


def test_email_header_and_body_decoding():
    assert decode_str("=?utf-8?b?0J/RgNC40LLQtdGC?=") == "Привет"

    msg = EmailMessage()
    msg["Subject"] = "Тест"
    msg.set_content("Текст письма")
    msg.add_alternative("<p>HTML</p>", subtype="html")
    assert get_text(msg).strip() == "Текст письма"
