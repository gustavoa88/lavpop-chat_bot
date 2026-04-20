from dataclasses import dataclass

from app.services import (
    INTERACTIVE_MENU_ID_TO_OPTION,
    normalize_phone,
    resolve_interactive_menu_selection,
)


@dataclass(frozen=True)
class ParsedMessageEvent:
    contact_name: str
    phone: str
    incoming_text: str
    msg_type: str
    message_obj: dict


def parse_meta_message_events(payload: dict) -> list[ParsedMessageEvent]:
    events: list[ParsedMessageEvent] = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = value.get("contacts", [])
            messages = value.get("messages", [])

            contact_name = ""
            if contacts:
                contact_name = ((contacts[0].get("profile") or {}).get("name") or "").strip()

            for message_obj in messages:
                msg_type = (message_obj.get("type") or "").strip().lower()
                phone = normalize_phone((message_obj.get("from") or "").strip())
                incoming_text = _extract_incoming_text(message_obj, msg_type)

                events.append(
                    ParsedMessageEvent(
                        contact_name=contact_name,
                        phone=phone,
                        incoming_text=incoming_text,
                        msg_type=msg_type,
                        message_obj=message_obj,
                    )
                )

    return events


def _extract_incoming_text(message_obj: dict, msg_type: str) -> str:
    if msg_type == "text":
        return ((message_obj.get("text") or {}).get("body") or "").strip()

    if msg_type == "button":
        return ((message_obj.get("button") or {}).get("text") or "").strip()

    if msg_type != "interactive":
        return ""

    interactive_obj = message_obj.get("interactive") or {}
    interactive_type = (interactive_obj.get("type") or "").strip().lower()

    if interactive_type == "list_reply":
        list_reply = interactive_obj.get("list_reply") or {}
        return resolve_interactive_menu_selection(
            interactive_id=(list_reply.get("id") or "").strip(),
            interactive_title=(list_reply.get("title") or "").strip(),
            interactive_description=(list_reply.get("description") or "").strip(),
        )

    if interactive_type == "button_reply":
        button_reply = interactive_obj.get("button_reply") or {}
        interactive_id = (button_reply.get("id") or "").strip()
        return INTERACTIVE_MENU_ID_TO_OPTION.get(interactive_id, (button_reply.get("title") or "").strip())

    return ""
