from app.webhook_parser import parse_meta_message_events


def test_parse_meta_message_events_extracts_text_and_contact_name():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"profile": {"name": "Maria"}}],
                            "messages": [
                                {
                                    "id": "wamid.1",
                                    "type": "text",
                                    "from": "5511999998888",
                                    "text": {"body": "Oi"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }

    events = parse_meta_message_events(payload)

    assert len(events) == 1
    assert events[0].contact_name == "Maria"
    assert events[0].phone == "5511999998888"
    assert events[0].incoming_text == "Oi"
    assert events[0].msg_type == "text"


def test_parse_meta_message_events_resolves_interactive_button_reply_to_option():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"profile": {"name": "João"}}],
                            "messages": [
                                {
                                    "id": "wamid.2",
                                    "type": "interactive",
                                    "from": "551188887777",
                                    "interactive": {
                                        "type": "button_reply",
                                        "button_reply": {
                                            "id": "menu_option_5",
                                            "title": "Atendimento",
                                        },
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }

    events = parse_meta_message_events(payload)

    assert len(events) == 1
    assert events[0].incoming_text == "5"
